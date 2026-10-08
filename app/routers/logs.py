"""运行日志接口（§1.3.2 系统管理员查看运行日志）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from .. import auth, db

router = APIRouter(prefix="/api/logs", tags=["运行日志"])


@router.get("/tasks", summary="全链路任务日志（管理员）")
def task_logs(
    task_id: int | None = Query(default=None),
    log_type: str | None = Query(default=None),
    log_level: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    user: dict = Depends(auth.require_admin),
) -> dict:
    sql = """
        SELECT l.*, t.approval_code, t.approval_title
        FROM task_logs l
        LEFT JOIN approval_tasks t ON t.id = l.task_id
    """
    conditions: list[str] = []
    params: list = []
    if task_id is not None:
        conditions.append("l.task_id = ?")
        params.append(task_id)
    if log_type:
        conditions.append("l.log_type = ?")
        params.append(log_type)
    if log_level:
        conditions.append("l.log_level = ?")
        params.append(log_level)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY l.id DESC LIMIT ?"
    params.append(limit)

    rows = db.query_all(sql, tuple(params))
    return {"total": len(rows), "logs": rows}


@router.get("/comments", summary="评论回写日志（管理员）")
def comment_logs(
    task_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    user: dict = Depends(auth.require_admin),
) -> dict:
    sql = """
        SELECT c.*, t.approval_code, t.approval_title
        FROM comment_logs c
        LEFT JOIN approval_tasks t ON t.id = c.task_id
    """
    params: list = []
    if task_id is not None:
        sql += " WHERE c.task_id = ?"
        params.append(task_id)
    sql += " ORDER BY c.id DESC LIMIT ?"
    params.append(limit)

    rows = db.query_all(sql, tuple(params))
    return {"total": len(rows), "logs": rows}
