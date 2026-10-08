"""审批任务接口（§1.3.3 服务入口需求 / §1.3.7 调用端能力要求）。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import auth, db, pipeline
from ..approval_adapter import get_adapter
from ..engine.rules import RISK_ORDER
from ..schemas import HitStatusRequest, PullRequest
from ..services import tools
from ..utils import now_str, truncate

router = APIRouter(prefix="/api/tasks", tags=["审批任务"])

STATUS_LABELS = {
    "pending": "待处理",
    "parsing": "解析中",
    "reviewing": "审查中",
    "blocked": "已阻塞",
    "done": "已完成",
}
WRITE_LABELS = {
    "not_written": "未回写",
    "writing": "回写中",
    "success": "回写成功",
    "failed": "回写失败",
}


def _get_task_or_404(task_id: int) -> dict:
    row = db.query_one("SELECT * FROM approval_tasks WHERE id = ?", (task_id,))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return row


def _decorate(task: dict, risk: str | None = None) -> dict:
    return {
        **task,
        "task_status_label": STATUS_LABELS.get(task["task_status"], task["task_status"]),
        "write_status_label": WRITE_LABELS.get(task["write_status"], task["write_status"]),
        "overall_risk_level": risk or "",
        "is_active": pipeline.is_active(int(task["id"])),
    }


def _decode(raw: str | None, fallback):
    try:
        return json.loads(raw) if raw else fallback
    except json.JSONDecodeError:
        return fallback


@router.post("/pull", summary="拉取待办审批单（供调用端使用）")
def pull(payload: PullRequest, user: dict = Depends(auth.get_current_user)) -> dict:
    try:
        return tools.list_pending_contract_approvals(payload.limit)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("", summary="任务列表")
def list_tasks(
    task_status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user: dict = Depends(auth.get_current_user),
) -> dict:
    sql = """
        SELECT t.*, r.overall_risk_level, p.parse_type,
               (SELECT COUNT(*) FROM rule_hits h WHERE h.task_id = t.id AND h.hit_status = 'hit')
                   AS hit_count
        FROM approval_tasks t
        LEFT JOIN review_results r ON r.task_id = t.id
        LEFT JOIN contract_parses p ON p.task_id = t.id
    """
    conditions: list[str] = []
    params: list = []
    if task_status:
        conditions.append("t.task_status = ?")
        params.append(task_status)
    if keyword:
        conditions.append("(t.approval_code LIKE ? OR t.approval_title LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY t.id DESC LIMIT ?"
    params.append(limit)

    rows = db.query_all(sql, tuple(params))
    tasks = [_decorate(row, row.get("overall_risk_level")) for row in rows]

    counts = {
        item["task_status"]: item["total"]
        for item in db.query_all(
            "SELECT task_status, COUNT(*) AS total FROM approval_tasks GROUP BY task_status"
        )
    }
    return {
        "total": len(tasks),
        "status_counts": counts,
        "tasks": tasks,
    }


@router.get("/{task_id}", summary="任务详情（审批信息 + 解析结果 + 命中 + 结果 + 日志）")
def task_detail(task_id: int, user: dict = Depends(auth.get_current_user)) -> dict:
    task = _get_task_or_404(task_id)

    # 审批系统详情（接口异常时不影响本地数据的展示）
    approval = None
    adapter_error = ""
    try:
        approval = get_adapter().fetch_detail(task["instance_id"])
    except Exception as exc:
        adapter_error = str(exc)

    attachments = db.query_all(
        "SELECT * FROM approval_attachments WHERE task_id = ? ORDER BY id ASC", (task_id,)
    )

    parse_row = db.query_one("SELECT * FROM contract_parses WHERE task_id = ?", (task_id,))
    parse_info = None
    if parse_row:
        parse_info = {
            "id": parse_row["id"],
            "document_id": parse_row["document_id"],
            "parse_status": parse_row["parse_status"],
            "parse_error": parse_row["parse_error"],
            "parse_type": parse_row["parse_type"],
            "page_count": parse_row["page_count"],
            "created_at": parse_row["created_at"],
            "basic_info": _decode(parse_row["basic_info_json"], {}),
            "clause_info": _decode(parse_row["clause_info_json"], {}),
            "full_text": parse_row["full_text"],
        }

    hits = db.query_all(
        """
        SELECT * FROM rule_hits WHERE task_id = ?
        ORDER BY CASE risk_level WHEN '高' THEN 1 WHEN '中' THEN 2 ELSE 3 END, rule_code
        """,
        (task_id,),
    )

    result_row = db.query_one("SELECT * FROM review_results WHERE task_id = ?", (task_id,))
    result = None
    if result_row:
        result = {
            "id": result_row["id"],
            "overall_risk_level": result_row["overall_risk_level"],
            "summary_text": result_row["summary_text"],
            "focus_points": _decode(result_row["focus_points_json"], []),
            "comment_text": result_row["comment_text"],
            "created_at": result_row["created_at"],
        }

    comment_logs = db.query_all(
        "SELECT * FROM comment_logs WHERE task_id = ? ORDER BY id ASC", (task_id,)
    )
    logs = db.query_all(
        "SELECT * FROM task_logs WHERE task_id = ? ORDER BY id DESC LIMIT 200", (task_id,)
    )

    risk = result["overall_risk_level"] if result else ""
    # 已判定误报的命中不计入总风险，此处按现存命中重算，供调用端核对
    active_levels = [row["risk_level"] for row in hits if row["hit_status"] != "dismissed"]
    recomputed = max(active_levels, key=lambda item: RISK_ORDER.get(item, 0)) if active_levels else "低"

    return {
        "task": _decorate(task, risk),
        "approval": approval,
        "adapter_error": adapter_error,
        "attachments": attachments,
        "parse": parse_info,
        "hits": hits,
        "hit_count": len(hits),
        "result": result,
        "recomputed_risk_level": recomputed,
        "comment_logs": comment_logs,
        "logs": logs,
    }


@router.put("/{task_id}/hits/{hit_id}", summary="判定命中为误报（法务审核人）")
def update_hit_status(
    task_id: int,
    hit_id: int,
    payload: HitStatusRequest,
    user: dict = Depends(auth.require_reviewer),
) -> dict:
    """法务审核人把命中标记为误报，总风险等级按剩余命中重算。

    已写回审批系统的评论作为历史记录保留，不会被改写。
    """
    _get_task_or_404(task_id)
    hit = db.query_one(
        "SELECT * FROM rule_hits WHERE id = ? AND task_id = ?", (hit_id, task_id)
    )
    if hit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="命中记录不存在")

    db.update(
        "rule_hits", {"hit_status": payload.hit_status}, "id = ?", (hit_id,)
    )
    pipeline.log_task(
        task_id,
        "INFO",
        "stage_ok",
        f"{user.get('display_name') or user['username']} 将命中「{hit['rule_name']}」"
        f"标记为{'误报' if payload.hit_status == 'dismissed' else '有效'}",
    )

    remaining = db.query_all(
        "SELECT risk_level FROM rule_hits WHERE task_id = ? AND hit_status != 'dismissed'",
        (task_id,),
    )
    levels = [row["risk_level"] for row in remaining]
    overall = max(levels, key=lambda item: RISK_ORDER.get(item, 0)) if levels else "低"

    db.update(
        "review_results",
        {"overall_risk_level": overall},
        "task_id = ?",
        (task_id,),
    )
    return {
        "hit_id": hit_id,
        "hit_status": payload.hit_status,
        "remaining_hits": len(remaining),
        "overall_risk_level": overall,
    }


@router.post("/{task_id}/retry", summary="重试阻塞任务（管理员）")
def retry_task(task_id: int, user: dict = Depends(auth.require_admin)) -> dict:
    _get_task_or_404(task_id)
    try:
        return pipeline.retry_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{task_id}/retry-comment", summary="重试评论回写（管理员）")
def retry_comment(task_id: int, user: dict = Depends(auth.require_admin)) -> dict:
    _get_task_or_404(task_id)
    try:
        return pipeline.retry_comment(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{task_id}/comment-preview", summary="查看回写内容与审批评论区现状")
def comment_preview(task_id: int, user: dict = Depends(auth.get_current_user)) -> dict:
    task = _get_task_or_404(task_id)
    result = db.query_one(
        "SELECT * FROM review_results WHERE task_id = ? ORDER BY id DESC LIMIT 1", (task_id,)
    )
    return {
        "comment_text": (result or {}).get("comment_text") or "",
        "write_status": task["write_status"],
        "write_status_label": WRITE_LABELS.get(task["write_status"], task["write_status"]),
        "approval_comment_area": truncate(
            (db.query_one(
                "SELECT comment_area FROM mock_approvals WHERE instance_id = ?",
                (task["instance_id"],),
            ) or {}).get("comment_area")
            or "",
            2000,
        ),
        "comment_logs": db.query_all(
            "SELECT * FROM comment_logs WHERE task_id = ? ORDER BY id ASC", (task_id,)
        ),
        "updated_at": now_str(),
    }
