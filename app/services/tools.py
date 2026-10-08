"""合同审批审查 —— 7 个工具函数（§1.3.10 工具接口要求）。

    1. list_pending_contract_approvals(limit)
    2. get_contract_approval(instance_id)
    3. download_contract_attachment(instance_id, attachment_id, file_name)
    4. parse_contract_document(document_id)
    5. run_contract_rules(case_id)
    6. save_review_result(case_id, overall_risk_level, summary_text, focus_points_json, comment_text)
    7. write_approval_comment(instance_id, review_id)

每个函数同时被 HTTP 路由（app/routers/tools.py）与演示脚本
（demo/run_demo.py）复用，保证「工具调用说明」与实际行为一致。
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import config, db, pipeline
from ..approval_adapter import get_adapter
from ..engine.document import DocumentParseError, parse_document
from ..engine.fields import BASIC_FIELD_DEFS, extract_fields
from ..utils import now_str, safe_slug, sha256_of, truncate


class ToolError(Exception):
    """工具调用失败（参数非法或前置条件不满足）。"""


# ---------------------------------------------------------------------------
# 1. 待办拉取
# ---------------------------------------------------------------------------
def list_pending_contract_approvals(limit: int = 10) -> dict:
    """拉取待处理审批单列表，并按唯一业务标识（approval_code）去重保存。

    返回字段包含审批编号、标题、申请人、申请时间、附件数量，以及本次去重结果。
    """
    if limit <= 0:
        raise ToolError("limit 必须为正整数")

    result = pipeline.pull_pending(limit)

    items = [
        {
            "instance_id": item.get("instance_id"),
            "approval_code": item.get("approval_code"),
            "approval_title": item.get("approval_title"),
            "applicant_name": item.get("applicant_name"),
            "applied_at": item.get("applied_at"),
            "attachment_count": item.get("attachment_count", 0),
            "approval_status": item.get("approval_status"),
        }
        for item in result.get("items", [])
    ]

    return {
        "tool": "list_pending_contract_approvals",
        "fetched": result["fetched"],
        "created_count": result["created_count"],
        "updated_count": result["updated_count"],
        "skipped_count": result["skipped_count"],
        "created": result["created"],
        "updated": result["updated"],
        "skipped": result["skipped"],
        "items": items,
    }


# ---------------------------------------------------------------------------
# 2. 审批详情
# ---------------------------------------------------------------------------
def get_contract_approval(instance_id: str) -> dict:
    """查询单个审批单详情：审批信息、表单数据、附件信息与当前处理状态。"""
    if not instance_id:
        raise ToolError("instance_id 不能为空")

    detail = get_adapter().fetch_detail(instance_id)

    task = db.query_one(
        """
        SELECT id, task_status, write_status, blocked_reason, failure_stage,
               retry_count, created_at, updated_at
        FROM approval_tasks WHERE approval_code = ?
        """,
        (detail["approval_code"],),
    )

    return {
        "tool": "get_contract_approval",
        "approval": {
            "instance_id": detail["instance_id"],
            "approval_code": detail["approval_code"],
            "approval_title": detail["approval_title"],
            "applicant_name": detail["applicant_name"],
            "department": detail["department"],
            "applied_at": detail["applied_at"],
            "approval_status": detail["approval_status"],
            "current_node": detail["current_node"],
        },
        "form_data": detail["form_data"],
        "attachments": detail["attachments"],
        "attachment_count": detail["attachment_count"],
        "comment_area": detail["comment_area"],
        "process_status": {
            "task_id": task["id"] if task else None,
            "task_status": task["task_status"] if task else "not_pulled",
            "write_status": task["write_status"] if task else "not_written",
            "blocked_reason": task["blocked_reason"] if task else "",
            "failure_stage": task["failure_stage"] if task else "",
            "retry_count": task["retry_count"] if task else 0,
        },
    }


# ---------------------------------------------------------------------------
# 3. 附件下载
# ---------------------------------------------------------------------------
def download_contract_attachment(
    instance_id: str, attachment_id: str, file_name: str
) -> dict:
    """按审批编号与附件编号下载合同附件，返回本地文件路径与校验信息。"""
    if not instance_id or not attachment_id:
        raise ToolError("instance_id 与 attachment_id 均不能为空")

    data, expected_sha, size = get_adapter().fetch_attachment(
        instance_id, attachment_id, file_name
    )

    target_dir = config.WORKSPACE_DIR / "_downloads" / safe_slug(instance_id, "instance")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_slug(file_name or "contract", fallback="contract", max_len=80)
    target.write_bytes(data)

    actual_sha = sha256_of(target)
    return {
        "tool": "download_contract_attachment",
        "instance_id": instance_id,
        "attachment_id": attachment_id,
        "file_name": file_name,
        "local_path": str(target),
        "sha256": actual_sha,
        "file_size": size,
        "verified": actual_sha == expected_sha,
        "download_status": "success" if actual_sha == expected_sha else "failed",
        "downloaded_at": now_str(),
    }


# ---------------------------------------------------------------------------
# 4. 文档解析
# ---------------------------------------------------------------------------
def parse_contract_document(document_id: str) -> dict:
    """解析已下载的合同文档，输出结构化字段、原文片段与定位信息。

    解析失败时返回 parse_status=failed 并携带失败原因，不抛出异常，
    以便调用方直接读取原因（§1.3.5 不允许只返回空结果）。
    """
    if not document_id:
        raise ToolError("document_id 不能为空")

    parse_row = db.query_one(
        "SELECT * FROM contract_parses WHERE document_id = ? ORDER BY id DESC LIMIT 1",
        (document_id,),
    )
    if parse_row is None:
        raise ToolError(f"解析记录不存在：document_id={document_id}")

    attachment = db.query_one(
        "SELECT * FROM approval_attachments WHERE task_id = ? ORDER BY id DESC LIMIT 1",
        (parse_row["task_id"],),
    )
    if attachment is None or not attachment["file_path"]:
        raise ToolError(f"未找到已下载的合同附件：document_id={document_id}")

    local_path = Path(attachment["file_path"])

    try:
        document = parse_document(local_path)
    except DocumentParseError as exc:
        return {
            "tool": "parse_contract_document",
            "document_id": document_id,
            "task_id": parse_row["task_id"],
            "file_name": attachment["file_name"],
            "parse_status": "failed",
            "parse_error": f"{exc.message}：{exc.detail}" if exc.detail else exc.message,
            "basic_info": {},
            "clause_info": {},
        }

    basic, clauses = extract_fields(document)
    return {
        "tool": "parse_contract_document",
        "document_id": document_id,
        "task_id": parse_row["task_id"],
        "file_name": attachment["file_name"],
        "parse_status": "success",
        "parse_error": "",
        "parse_type": document.parse_type,
        "ocr_engine": document.ocr_engine,
        "page_count": document.page_count,
        "paragraph_count": len(document.paragraphs),
        "basic_info": basic,
        "clause_info": clauses,
        "basic_found": sum(1 for v in basic.values() if v["status"] == "found"),
        "basic_total": len(BASIC_FIELD_DEFS),
        "clause_found": sum(1 for v in clauses.values() if v["status"] == "found"),
        "clause_total": len(clauses),
        "warnings": document.warnings,
    }


# ---------------------------------------------------------------------------
# 5. 规则审查
# ---------------------------------------------------------------------------
def run_contract_rules(case_id: int) -> dict:
    """对解析结果执行规则匹配，输出风险等级、命中证据和处理建议。

    case_id 为解析记录编号（contract_parses.id）。命中结果会写入 rule_hits，
    重复调用幂等。
    """
    if not case_id:
        raise ToolError("case_id 不能为空")

    evaluation = pipeline.evaluate_rules(int(case_id))
    hits = evaluation["hits"]

    counts = {"高": 0, "中": 0, "低": 0}
    for hit in hits:
        counts[hit.risk_level] = counts.get(hit.risk_level, 0) + 1

    return {
        "tool": "run_contract_rules",
        "case_id": evaluation["case_id"],
        "task_id": evaluation["task_id"],
        "overall_risk_level": evaluation["overall_risk_level"],
        "summary_text": evaluation["summary_text"],
        "focus_points": evaluation["focus_points"],
        "hit_count": len(hits),
        "risk_counts": counts,
        "hits": [
            {
                "rule_code": hit.rule_code,
                "rule_name": hit.rule_name,
                "risk_level": hit.risk_level,
                "evidence_text": hit.evidence_text,
                "evidence_position": hit.evidence_position,
                "suggestion_text": hit.suggestion_text,
            }
            for hit in hits
        ],
        "comment_text": evaluation["comment_text"],
    }


# ---------------------------------------------------------------------------
# 6. 结果保存
# ---------------------------------------------------------------------------
def save_review_result(
    case_id: int,
    overall_risk_level: str,
    summary_text: str,
    focus_points_json: str,
    comment_text: str,
) -> dict:
    """保存审查结果、命中规则摘要与回写内容。"""
    if not case_id:
        raise ToolError("case_id 不能为空")
    if overall_risk_level not in {"低", "中", "高"}:
        raise ToolError("overall_risk_level 只能是 低 / 中 / 高")

    parse_row = db.query_one("SELECT task_id FROM contract_parses WHERE id = ?", (case_id,))
    if parse_row is None:
        raise ToolError(f"解析记录不存在：case_id={case_id}")

    try:
        focus_points = json.loads(focus_points_json) if focus_points_json else []
    except json.JSONDecodeError as exc:
        raise ToolError(f"focus_points_json 不是合法 JSON：{exc}") from exc

    review_id = pipeline.save_review_result(
        task_id=int(parse_row["task_id"]),
        overall_risk_level=overall_risk_level,
        summary_text=summary_text,
        focus_points_json=json.dumps(focus_points, ensure_ascii=False),
        comment_text=comment_text,
    )

    hit_count = db.count("rule_hits", "task_id = ?", (parse_row["task_id"],))
    pipeline.log_task(
        int(parse_row["task_id"]),
        "INFO",
        "stage_ok",
        f"审查结果已通过工具保存：结果记录 #{review_id}，命中 {hit_count} 条",
    )

    return {
        "tool": "save_review_result",
        "review_id": review_id,
        "case_id": case_id,
        "task_id": parse_row["task_id"],
        "overall_risk_level": overall_risk_level,
        "focus_point_count": len(focus_points),
        "hit_count": hit_count,
        "comment_length": len(comment_text or ""),
    }


# ---------------------------------------------------------------------------
# 7. 评论回写
# ---------------------------------------------------------------------------
def write_approval_comment(instance_id: str, review_id: int) -> dict:
    """将最终审查意见写回审批评论区，并返回回写结果。"""
    if not instance_id:
        raise ToolError("instance_id 不能为空")
    if not review_id:
        raise ToolError("review_id 不能为空")

    outcome = pipeline.write_comment_for_review(int(review_id), instance_id)

    review = db.query_one(
        "SELECT comment_text FROM review_results WHERE id = ?", (review_id,)
    )
    detail = get_adapter().fetch_detail(instance_id)

    return {
        "tool": "write_approval_comment",
        "review_id": outcome["review_id"],
        "task_id": outcome["task_id"],
        "instance_id": outcome["instance_id"],
        "write_status": outcome["write_status"],
        "comment_preview": truncate((review or {}).get("comment_text") or "", 200),
        "approval_comment_area": truncate(detail.get("comment_area") or "", 500),
    }
