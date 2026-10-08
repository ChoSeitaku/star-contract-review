"""任务流水线编排（§1.3.4 任务状态与流转规则、§1.3.8 服务模块要求）。

负责把「待办拉取 → 附件下载 → 文档解析 → 规则审查 → 结果保存 → 评论回写」
串成后台任务，并维护任务状态机：

    pending ──▶ parsing ──▶ reviewing ──▶ done
                   │            │
                   └──▶ blocked ◀┘        （人工重试后回到对应阶段）

阻塞原因（§1.3.4）：附件缺失、图片无法识别、文档内容为空、接口调用失败。
回写失败不阻塞任务：任务仍进入 done，仅将 write_status 置为 failed，可单独重试。

任务执行采用线程池而非 asyncio：解析、OCR、数据库与文件操作均为阻塞式，
线程模型无需事件循环即可从同步接口安全入队，也避免跨线程调度问题。
"""

from __future__ import annotations

import json
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config, db
from .approval_adapter import ApprovalApiError, get_adapter
from .engine.aggregate import build_result
from .engine.document import DocumentParseError, ParsedDocument, Paragraph, parse_document
from .engine.fields import extract_fields
from .engine.rules import run_rules
from .utils import now_str, safe_slug, sha256_of, truncate

MAX_WORKERS = 4

_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="contract-review")
_running: set[int] = set()
_running_lock = threading.Lock()


# ---------------------------------------------------------------------------
# 状态与日志
# ---------------------------------------------------------------------------
def _get_task(task_id: int) -> dict | None:
    return db.query_one("SELECT * FROM approval_tasks WHERE id = ?", (task_id,))


def set_task_status(
    task_id: int,
    task_status: str | None = None,
    write_status: str | None = None,
    blocked_reason: str | None = None,
    failure_stage: str | None = None,
    bump_retry: bool = False,
) -> None:
    data: dict = {"updated_at": now_str()}
    if task_status is not None:
        data["task_status"] = task_status
    if write_status is not None:
        data["write_status"] = write_status
    if blocked_reason is not None:
        data["blocked_reason"] = blocked_reason
    if failure_stage is not None:
        data["failure_stage"] = failure_stage
    if bump_retry:
        data["retry_count"] = int(
            db.query_scalar("SELECT retry_count FROM approval_tasks WHERE id = ?", (task_id,), 0) or 0
        ) + 1
    db.update("approval_tasks", data, "id = ?", (task_id,))


def log_task(task_id: int, log_level: str, log_type: str, content: str) -> None:
    """写全链路日志（§1.3.8 日志模块）：同时落库与落文件。"""
    stamp = now_str()
    db.insert(
        "task_logs",
        {
            "task_id": task_id,
            "log_level": log_level,
            "log_type": log_type,
            "log_content": truncate(content, 2000),
            "created_at": stamp,
        },
    )
    try:
        log_dir = config.task_log_dir(task_id)
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "task.log", "a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {log_level:<5} {log_type:<16} {content}\n")
    except OSError:
        # 日志文件写入失败不影响主流程，数据库日志仍然完整
        pass


def _block(task_id: int, reason: str, stage: str, detail: str = "") -> None:
    """把任务置为阻塞态（§1.3.4）。"""
    set_task_status(
        task_id, task_status="blocked", blocked_reason=reason, failure_stage=stage
    )
    message = f"任务阻塞：{reason}"
    if detail:
        message += f"（{detail}）"
    log_task(task_id, "ERROR", "blocked", message)


# ---------------------------------------------------------------------------
# 任务调度
# ---------------------------------------------------------------------------
def is_active(task_id: int) -> bool:
    with _running_lock:
        return task_id in _running


def active_task_ids() -> list[int]:
    with _running_lock:
        return sorted(_running)


def enqueue(task_id: int, mode: str = "auto") -> bool:
    """把任务放入线程池执行；同一任务不会并发执行。"""
    with _running_lock:
        if task_id in _running:
            return False
        _running.add(task_id)
    _executor.submit(_run_guarded, task_id, mode)
    return True


def _run_guarded(task_id: int, mode: str) -> None:
    try:
        if mode == "comment":
            _process_comment_only(task_id)
        else:
            _process(task_id)
    except Exception as exc:  # 兜底：任何未预期异常都必须留下痕迹，绝不静默
        detail = traceback.format_exc(limit=3)
        try:
            _block(task_id, "审查异常", "review", f"{exc}")
            log_task(task_id, "ERROR", "unhandled", detail)
        except Exception:
            pass
    finally:
        with _running_lock:
            _running.discard(task_id)


def shutdown() -> None:
    """停止接收新任务并等待在途任务结束。"""
    _executor.shutdown(wait=True, cancel_futures=True)


def _process(task_id: int) -> None:
    task = _get_task(task_id)
    if task is None:
        return
    status = (task.get("task_status") or "").strip()
    if status in {"pending", "parsing"}:
        _run_parsing(task_id)
    elif status == "reviewing":
        _run_reviewing(task_id)
    # blocked / done：不自动重跑，需人工重试


# ---------------------------------------------------------------------------
# 阶段一：附件下载 + 文档解析
# ---------------------------------------------------------------------------
def _run_parsing(task_id: int) -> None:
    task = _get_task(task_id)
    if task is None:
        return
    instance_id = task["instance_id"]

    set_task_status(task_id, task_status="parsing")
    log_task(task_id, "INFO", "stage_enter", "进入解析阶段：下载合同附件并解析文档")

    adapter = get_adapter()

    # --- 审批详情 ---------------------------------------------------------
    try:
        detail = adapter.fetch_detail(instance_id)
    except ApprovalApiError as exc:
        _block(task_id, "接口调用失败", "download", str(exc))
        return

    attachments = detail.get("attachments") or []
    if not attachments:
        _block(task_id, "附件缺失", "download", f"审批单 {instance_id} 未提供任何合同附件")
        return

    attachment = attachments[0]

    # --- 附件下载 ---------------------------------------------------------
    try:
        local_path, sha256, file_size, verified = _download_attachment(
            task_id, instance_id, attachment
        )
    except ApprovalApiError as exc:
        _block(task_id, "接口调用失败", "download", str(exc))
        return
    except OSError as exc:
        _block(task_id, "附件缺失", "download", f"附件写入本地失败：{exc}")
        return

    # --- 文档解析 ---------------------------------------------------------
    try:
        document = parse_document(local_path)
        basic, clauses = extract_fields(document)
    except DocumentParseError as exc:
        _record_failed_parse(task_id, attachment.get("attachment_id"), exc.message, exc.detail)
        _block(task_id, exc.message, "parse", exc.detail)
        return

    parse_id = _save_parse(task_id, document, basic, clauses, sha256, file_size, verified)
    log_task(
        task_id,
        "INFO",
        "stage_ok",
        f"解析完成：类型 {document.parse_type}，{document.page_count} 页，"
        f"{len(document.paragraphs)} 段，解析记录 #{parse_id}",
    )

    _run_reviewing(task_id)


def _download_attachment(
    task_id: int, instance_id: str, attachment: dict
) -> tuple[Path, str, int, bool]:
    """下载附件到任务工作目录，返回 (本地路径, sha256, 字节数, 校验是否一致)。"""
    file_name = attachment.get("file_name") or "contract"
    attachment_id = str(attachment.get("attachment_id") or "")

    data, expected_sha, size = get_adapter().fetch_attachment(
        instance_id, attachment_id, file_name
    )

    target_dir = config.task_workspace_dir(task_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_slug(file_name, fallback="contract", max_len=80)
    target.write_bytes(data)

    actual_sha = sha256_of(target)
    verified = actual_sha == expected_sha

    row = db.query_one(
        "SELECT id FROM approval_attachments WHERE task_id = ? AND attachment_id = ?",
        (task_id, attachment_id),
    )
    payload = {
        "task_id": task_id,
        "file_name": file_name,
        "file_type": attachment.get("file_type") or "contract",
        "file_path": str(target),
        "download_status": "success" if verified else "failed",
        "attachment_id": attachment_id,
        "sha256": actual_sha,
        "file_size": size,
    }
    if row is None:
        payload["created_at"] = now_str()
        db.insert("approval_attachments", payload)
    else:
        db.update("approval_attachments", payload, "id = ?", (row["id"],))

    log_task(
        task_id,
        "INFO",
        "stage_ok",
        f"附件下载完成：{file_name}（{size} 字节，sha256 {actual_sha[:16]}…，校验{'通过' if verified else '不一致'}）",
    )
    return target, actual_sha, size, verified


def _record_failed_parse(
    task_id: int, attachment_id: str | None, reason: str, detail: str
) -> None:
    """解析失败也要落库（§1.3.5 不允许只返回空结果）。"""
    payload = {
        "task_id": task_id,
        "basic_info_json": "{}",
        "clause_info_json": "{}",
        "parse_status": "failed",
        "parse_error": f"{reason}：{detail}" if detail else reason,
        "document_id": f"DOC-{task_id:04d}",
        "parse_type": "",
        "full_text": "",
        "page_count": 0,
        "paragraphs_json": "[]",
        "created_at": now_str(),
    }
    existing = db.query_one("SELECT id FROM contract_parses WHERE task_id = ?", (task_id,))
    if existing is None:
        db.insert("contract_parses", payload)
    else:
        payload.pop("created_at")
        db.update("contract_parses", payload, "id = ?", (existing["id"],))


def _save_parse(
    task_id: int,
    document: ParsedDocument,
    basic: dict,
    clauses: dict,
    sha256: str,
    file_size: int,
    verified: bool,
) -> int:
    payload = {
        "task_id": task_id,
        "basic_info_json": json.dumps(basic, ensure_ascii=False),
        "clause_info_json": json.dumps(clauses, ensure_ascii=False),
        "parse_status": "success",
        "parse_error": "",
        "document_id": f"DOC-{task_id:04d}",
        "parse_type": document.parse_type,
        "full_text": document.full_text,
        "page_count": document.page_count,
        "paragraphs_json": json.dumps(
            [{"page_no": p.page_no, "index": p.index, "text": p.text} for p in document.paragraphs],
            ensure_ascii=False,
        ),
        "created_at": now_str(),
    }

    existing = db.query_one("SELECT id FROM contract_parses WHERE task_id = ?", (task_id,))
    if existing is None:
        parse_id = db.insert("contract_parses", payload)
    else:
        parse_id = int(existing["id"])
        payload.pop("created_at")
        db.update("contract_parses", payload, "id = ?", (parse_id,))

    if not verified:
        log_task(task_id, "WARN", "stage_ok", f"附件校验值不一致（预期 {sha256[:16]}…，实际以本地文件为准）")
    return parse_id


# ---------------------------------------------------------------------------
# 阶段二：规则审查 + 结果保存 + 评论回写
# ---------------------------------------------------------------------------
def _load_parse(task_id: int) -> tuple[dict, ParsedDocument] | None:
    row = db.query_one("SELECT * FROM contract_parses WHERE task_id = ?", (task_id,))
    if row is None or row["parse_status"] != "success":
        return None

    basic = json.loads(row["basic_info_json"] or "{}")
    clauses = json.loads(row["clause_info_json"] or "{}")
    try:
        raw_paragraphs = json.loads(row["paragraphs_json"] or "[]")
    except json.JSONDecodeError:
        raw_paragraphs = []

    paragraphs = [
        Paragraph(
            page_no=int(item.get("page_no", 1)),
            index=int(item.get("index", 1)),
            text=str(item.get("text", "")),
        )
        for item in raw_paragraphs
    ]

    # 兼容仅有全文的解析记录：按行还原段落，保证规则仍可全文匹配
    if not paragraphs and (row["full_text"] or "").strip():
        paragraphs = [
            Paragraph(page_no=1, index=index, text=line.strip())
            for index, line in enumerate(
                (line for line in row["full_text"].splitlines() if line.strip()), start=1
            )
        ]

    document = ParsedDocument(
        file_name=_attachment_name(task_id) or f"DOC-{task_id:04d}",
        source_path="",
        parse_type=row["parse_type"] or "",
        page_count=int(row["page_count"] or 0),
        paragraphs=paragraphs,
    )
    return {"row": row, "basic": basic, "clauses": clauses, "document": document}


def _attachment_name(task_id: int) -> str:
    return str(
        db.query_scalar(
            "SELECT file_name FROM approval_attachments WHERE task_id = ? ORDER BY id DESC LIMIT 1",
            (task_id,),
            "",
        )
        or ""
    )


def evaluate_rules(case_id: int) -> dict:
    """按解析记录执行规则审查，落库命中结果并返回风险结论。

    §1.3.10 `run_contract_rules(case_id)` 的服务实现，case_id 即 contract_parses.id。
    重复执行幂等：先清理该任务的历史命中再写入。
    """
    parse_row = db.query_one("SELECT * FROM contract_parses WHERE id = ?", (case_id,))
    if parse_row is None:
        raise ValueError(f"解析记录不存在：case_id={case_id}")
    if parse_row["parse_status"] != "success":
        raise ValueError(
            f"解析记录未成功，无法执行规则审查：{parse_row['parse_error'] or '原因未知'}"
        )

    task_id = int(parse_row["task_id"])
    loaded = _load_parse(task_id)
    if loaded is None:
        raise ValueError(f"解析记录不可用：case_id={case_id}")

    document: ParsedDocument = loaded["document"]
    basic: dict = loaded["basic"]
    clauses: dict = loaded["clauses"]

    rules = db.query_all("SELECT * FROM review_rules ORDER BY id ASC")
    hits, warnings = run_rules(rules, document, basic, clauses)
    for warning in warnings:
        log_task(task_id, "WARN", "stage_ok", warning)

    db.execute("DELETE FROM rule_hits WHERE task_id = ?", (task_id,))
    rule_index = {row["rule_code"]: row["id"] for row in rules}
    for hit in hits:
        db.insert(
            "rule_hits",
            {
                "task_id": task_id,
                "rule_id": rule_index.get(hit.rule_code, 0),
                "evidence_text": hit.evidence_text,
                "evidence_position": hit.evidence_position,
                "hit_status": "hit",
                "rule_code": hit.rule_code,
                "rule_name": hit.rule_name,
                "risk_level": hit.risk_level,
                "suggestion_text": hit.suggestion_text,
                "created_at": now_str(),
            },
        )

    parse_note = ""
    if document.parse_type == "pdf_ocr":
        parse_note = "（本文档为扫描件，字段经 OCR 识别提取，关键信息建议人工复核）"

    result = build_result(
        document,
        basic,
        clauses,
        hits,
        prefix=config.get_config("comment_prefix", "【合同自动审查意见】"),
        parse_note=parse_note,
    )

    return {
        "task_id": task_id,
        "case_id": case_id,
        "document": document,
        "basic": basic,
        "clauses": clauses,
        "hits": hits,
        "parse_note": parse_note,
        "overall_risk_level": result["overall_risk_level"],
        "summary_text": result["summary_text"],
        "focus_points": result["focus_points"],
        "comment_text": result["comment_text"],
    }


def _run_reviewing(task_id: int) -> None:
    task = _get_task(task_id)
    if task is None:
        return

    set_task_status(task_id, task_status="reviewing")
    log_task(task_id, "INFO", "stage_enter", "进入审查阶段：执行规则匹配并生成审查意见")

    parse_row = db.query_one("SELECT id FROM contract_parses WHERE task_id = ?", (task_id,))
    if parse_row is None:
        _block(task_id, "解析结果缺失", "review", "未找到可用的解析记录，无法执行规则审查")
        return

    try:
        evaluation = evaluate_rules(int(parse_row["id"]))
    except ValueError as exc:
        _block(task_id, "解析结果缺失", "review", str(exc))
        return

    log_task(
        task_id,
        "INFO",
        "stage_ok",
        f"规则审查完成：命中 {len(evaluation['hits'])} 条风险规则",
    )

    review_id = save_review_result(
        task_id=task_id,
        overall_risk_level=evaluation["overall_risk_level"],
        summary_text=evaluation["summary_text"],
        focus_points_json=json.dumps(evaluation["focus_points"], ensure_ascii=False),
        comment_text=evaluation["comment_text"],
    )
    log_task(
        task_id,
        "INFO",
        "stage_ok",
        f"审查结果已保存：总风险等级 {evaluation['overall_risk_level']}，结果记录 #{review_id}",
    )

    # 回写失败不阻塞任务（§1.3.4 回写状态独立于任务状态）
    write_comment(task_id, review_id, task["instance_id"])
    set_task_status(task_id, task_status="done")
    log_task(task_id, "INFO", "stage_ok", "任务完成")


def save_review_result(
    task_id: int,
    overall_risk_level: str,
    summary_text: str,
    focus_points_json: str,
    comment_text: str,
) -> int:
    """保存审查结果（§1.3.10 save_review_result）。"""
    payload = {
        "task_id": task_id,
        "overall_risk_level": overall_risk_level,
        "summary_text": summary_text,
        "focus_points_json": focus_points_json,
        "comment_text": comment_text,
        "created_at": now_str(),
    }
    existing = db.query_one("SELECT id FROM review_results WHERE task_id = ?", (task_id,))
    if existing is None:
        return db.insert("review_results", payload)
    payload.pop("created_at")
    db.update("review_results", payload, "id = ?", (existing["id"],))
    return int(existing["id"])


def write_comment(task_id: int, review_id: int, instance_id: str) -> bool:
    """把审查意见写回审批评论区，并记录回写日志。"""
    row = db.query_one("SELECT comment_text FROM review_results WHERE id = ?", (review_id,))
    comment_text = (row or {}).get("comment_text") or ""

    attempt = db.count("comment_logs", "task_id = ?", (task_id,)) + 1
    set_task_status(task_id, write_status="writing")
    log_task(task_id, "INFO", "comment_write", f"第 {attempt} 次回写审批评论（{len(comment_text)} 字）")

    base = {
        "task_id": task_id,
        "attempt_no": attempt,
        "review_id": review_id,
        "instance_id": instance_id,
    }

    try:
        response = get_adapter().write_comment(instance_id, comment_text)
    except Exception as exc:
        set_task_status(task_id, write_status="failed")
        db.insert(
            "comment_logs",
            {
                **base,
                "write_status": "failed",
                "write_response_text": f"回写失败：{exc}",
                "created_at": now_str(),
            },
        )
        log_task(task_id, "ERROR", "comment_failed", f"评论回写失败（第 {attempt} 次）：{exc}")
        return False

    set_task_status(task_id, write_status="success")
    db.insert(
        "comment_logs",
        {
            **base,
            "write_status": "success",
            "write_response_text": response,
            "created_at": now_str(),
        },
    )
    log_task(task_id, "INFO", "comment_success", response)
    return True


def _process_comment_only(task_id: int) -> None:
    """仅重试评论回写，不重跑审查流程。"""
    task = _get_task(task_id)
    if task is None:
        return
    review = db.query_one(
        "SELECT id FROM review_results WHERE task_id = ? ORDER BY id DESC LIMIT 1", (task_id,)
    )
    if review is None:
        log_task(task_id, "ERROR", "comment_failed", "未找到审查结果，无法重试回写")
        return
    write_comment(task_id, int(review["id"]), task["instance_id"])


def write_comment_for_review(review_id: int, instance_id: str | None = None) -> dict:
    """按审查结果编号回写审批评论（§1.3.10 write_approval_comment）。"""
    row = db.query_one(
        """
        SELECT r.id AS review_id, r.task_id, t.instance_id, t.write_status
        FROM review_results r
        JOIN approval_tasks t ON t.id = r.task_id
        WHERE r.id = ?
        """,
        (review_id,),
    )
    if row is None:
        raise ValueError(f"审查结果不存在：review_id={review_id}")

    actual_instance = row["instance_id"]
    if instance_id and instance_id != actual_instance:
        raise ValueError(
            f"审批单不匹配：审查结果 #{review_id} 属于 {actual_instance}，请求方传入 {instance_id}"
        )

    success = write_comment(int(row["task_id"]), int(row["review_id"]), actual_instance)
    return {
        "review_id": int(row["review_id"]),
        "task_id": int(row["task_id"]),
        "instance_id": actual_instance,
        "write_status": "success" if success else "failed",
    }


# ---------------------------------------------------------------------------
# 对外操作：拉取 / 重试
# ---------------------------------------------------------------------------
def pull_pending(limit: int = 10) -> dict:
    """拉取待处理审批单并按唯一业务标识去重（§1.3.4）。

    已存在且处于 pending/parsing/reviewing 的任务只刷新元数据并确保其在执行队列中；
    已完成或已阻塞的任务只刷新元数据，等待人工处理，不重复创建。
    """
    adapter = get_adapter()
    items = adapter.fetch_pending(limit)

    created: list[dict] = []
    updated: list[dict] = []
    skipped: list[dict] = []

    for item in items:
        approval_code = item.get("approval_code") or ""
        if not approval_code:
            continue

        existing = db.query_one(
            "SELECT * FROM approval_tasks WHERE approval_code = ?", (approval_code,)
        )

        if existing is None:
            task_id = db.insert(
                "approval_tasks",
                {
                    "approval_code": approval_code,
                    "approval_title": item.get("approval_title") or "",
                    "applicant_name": item.get("applicant_name") or "",
                    "task_status": "pending",
                    "write_status": "not_written",
                    "instance_id": item.get("instance_id") or "",
                    "applied_at": item.get("applied_at") or "",
                    "created_at": now_str(),
                    "updated_at": now_str(),
                },
            )
            log_task(
                task_id,
                "INFO",
                "pull_created",
                f"拉取到新审批单：{approval_code}《{item.get('approval_title')}》"
                f"申请人 {item.get('applicant_name')}，附件 {item.get('attachment_count', 0)} 个",
            )
            created.append({"task_id": task_id, "approval_code": approval_code})
            enqueue(task_id)
            continue

        # 已存在：只刷新元数据，不新建任务
        db.update(
            "approval_tasks",
            {
                "approval_title": item.get("approval_title") or existing["approval_title"],
                "applicant_name": item.get("applicant_name") or existing["applicant_name"],
                "applied_at": item.get("applied_at") or existing["applied_at"],
                "instance_id": item.get("instance_id") or existing["instance_id"],
                "updated_at": now_str(),
            },
            "id = ?",
            (existing["id"],),
        )

        status = existing["task_status"]
        if status in {"blocked", "done"}:
            skipped.append(
                {
                    "task_id": existing["id"],
                    "approval_code": approval_code,
                    "task_status": status,
                    "reason": "已完成" if status == "done" else "已阻塞，等待人工重试",
                }
            )
            continue

        if enqueue(existing["id"]):
            log_task(
                existing["id"],
                "INFO",
                "pull_created",
                f"重复拉取：任务已在 {status} 状态，重新加入执行队列",
            )
        updated.append(
            {"task_id": existing["id"], "approval_code": approval_code, "task_status": status}
        )

    return {
        "fetched": len(items),
        "items": items,
        "created_count": len(created),
        "updated_count": len(updated),
        "skipped_count": len(skipped),
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }


def retry_task(task_id: int) -> dict:
    """人工重试阻塞任务（§1.3.4）：按失败阶段回到 parsing 或 reviewing。"""
    task = _get_task(task_id)
    if task is None:
        raise ValueError(f"任务不存在：{task_id}")
    if task["task_status"] != "blocked":
        raise ValueError(f"仅阻塞状态的任务可以重试，当前状态：{task['task_status']}")

    stage = (task.get("failure_stage") or "parse").strip()
    target_status = "reviewing" if stage == "review" else "parsing"

    set_task_status(
        task_id,
        task_status=target_status,
        blocked_reason="",
        failure_stage="",
        bump_retry=True,
    )
    log_task(
        task_id,
        "INFO",
        "retry",
        f"人工重试（第 {int(task['retry_count']) + 1} 次）："
        f"原阻塞原因「{task['blocked_reason']}」，从 {target_status} 阶段重新执行",
    )
    enqueue(task_id)
    return {"task_id": task_id, "task_status": target_status, "stage": stage}


def retry_comment(task_id: int) -> dict:
    """重试评论回写（任务已完成但回写失败）。"""
    task = _get_task(task_id)
    if task is None:
        raise ValueError(f"任务不存在：{task_id}")
    if task["write_status"] != "failed":
        raise ValueError(f"仅回写失败的任务可以重试回写，当前回写状态：{task['write_status']}")

    set_task_status(task_id, write_status="writing")
    log_task(task_id, "INFO", "comment_write", "人工触发评论回写重试")
    enqueue(task_id, mode="comment")
    return {"task_id": task_id, "write_status": "writing"}
