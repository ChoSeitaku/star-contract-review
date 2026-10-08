"""认证模块：登录态识别依赖（§1.3.2 用户角色：系统管理员 / 法务审核人）。"""

from __future__ import annotations

import datetime as _dt

from fastapi import Depends, Header, HTTPException, Query, status

from . import db, security
from .utils import TIME_FORMAT, now_str


def create_session(user_id: int) -> str:
    token = security.new_token()
    expires_at = (
        _dt.datetime.now() + _dt.timedelta(seconds=security.TOKEN_TTL_SECONDS)
    ).strftime(TIME_FORMAT)
    db.insert(
        "sessions",
        {
            "token": token,
            "user_id": user_id,
            "created_at": now_str(),
            "expires_at": expires_at,
        },
    )
    return token


def destroy_session(token: str) -> None:
    db.execute("DELETE FROM sessions WHERE token = ?", (token,))


def purge_expired_sessions() -> None:
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (now_str(),))


def resolve_token(token: str | None) -> dict | None:
    """根据 token 返回用户信息，无效或过期返回 None。"""
    if not token:
        return None
    row = db.query_one(
        """
        SELECT u.id, u.username, u.display_name, u.role, u.status, s.expires_at
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = ?
        """,
        (token,),
    )
    if row is None:
        return None
    if row["expires_at"] < now_str():
        destroy_session(token)
        return None
    if row["status"] != "active":
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"] or row["username"],
        "role": row["role"],
    }


def _extract_token(authorization: str | None, token: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return token


def get_current_user(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict:
    """FastAPI 依赖：要求已登录，否则 401。"""
    user = resolve_token(_extract_token(authorization, token))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录态已过期，请重新登录",
        )
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """FastAPI 依赖：要求系统管理员角色（维护规则、重试失败任务、查看日志）。"""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该操作需要系统管理员权限",
        )
    return user


def require_reviewer(user: dict = Depends(get_current_user)) -> dict:
    """FastAPI 依赖：要求法务审核人或系统管理员角色（查看合同详情、判定误报）。"""
    if user.get("role") not in {"admin", "reviewer"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该操作需要法务审核人权限",
        )
    return user
