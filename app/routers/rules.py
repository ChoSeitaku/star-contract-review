"""审查规则维护接口（§1.3.2 系统管理员维护规则）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import auth, db
from ..schemas import RuleUpsertRequest
from ..utils import now_str

router = APIRouter(prefix="/api/rules", tags=["审查规则"])

RISK_ORDER_SQL = "CASE risk_level WHEN '高' THEN 1 WHEN '中' THEN 2 ELSE 3 END"


def _get_or_404(rule_id: int) -> dict:
    row = db.query_one("SELECT * FROM review_rules WHERE id = ?", (rule_id,))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规则不存在")
    return row


@router.get("", summary="规则列表")
def list_rules(
    rule_status: str | None = Query(default=None),
    user: dict = Depends(auth.get_current_user),
) -> dict:
    sql = "SELECT * FROM review_rules"
    params: list = []
    if rule_status:
        sql += " WHERE rule_status = ?"
        params.append(rule_status)
    sql += f" ORDER BY {RISK_ORDER_SQL}, rule_code"
    rows = db.query_all(sql, tuple(params))
    return {"total": len(rows), "rules": rows}


@router.post("", summary="新增规则（管理员）", status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: RuleUpsertRequest, user: dict = Depends(auth.require_admin)
) -> dict:
    if db.query_one("SELECT id FROM review_rules WHERE rule_code = ?", (payload.rule_code,)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"规则编码已存在：{payload.rule_code}",
        )
    rule_id = db.insert(
        "review_rules",
        {
            "rule_code": payload.rule_code,
            "rule_name": payload.rule_name,
            "risk_level": payload.risk_level,
            "rule_status": payload.rule_status,
            "match_mode": payload.match_mode,
            "match_text": payload.match_text,
            "suggestion_text": payload.suggestion_text,
            "match_target": payload.match_target,
            "updated_at": now_str(),
        },
    )
    return _get_or_404(rule_id)


@router.put("/{rule_id}", summary="更新规则（管理员）")
def update_rule(
    rule_id: int, payload: RuleUpsertRequest, user: dict = Depends(auth.require_admin)
) -> dict:
    _get_or_404(rule_id)

    duplicate = db.query_one(
        "SELECT id FROM review_rules WHERE rule_code = ? AND id != ?",
        (payload.rule_code, rule_id),
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"规则编码已被占用：{payload.rule_code}",
        )

    db.update(
        "review_rules",
        {
            "rule_code": payload.rule_code,
            "rule_name": payload.rule_name,
            "risk_level": payload.risk_level,
            "rule_status": payload.rule_status,
            "match_mode": payload.match_mode,
            "match_text": payload.match_text,
            "suggestion_text": payload.suggestion_text,
            "match_target": payload.match_target,
            "updated_at": now_str(),
        },
        "id = ?",
        (rule_id,),
    )
    return _get_or_404(rule_id)


@router.post("/{rule_id}/toggle", summary="启用/停用规则（管理员）")
def toggle_rule(rule_id: int, user: dict = Depends(auth.require_admin)) -> dict:
    rule = _get_or_404(rule_id)
    new_status = "disabled" if rule["rule_status"] == "enabled" else "enabled"
    db.update(
        "review_rules",
        {"rule_status": new_status, "updated_at": now_str()},
        "id = ?",
        (rule_id,),
    )
    return _get_or_404(rule_id)


@router.delete("/{rule_id}", summary="删除规则（管理员）")
def delete_rule(rule_id: int, user: dict = Depends(auth.require_admin)) -> dict:
    _get_or_404(rule_id)
    db.execute("DELETE FROM review_rules WHERE id = ?", (rule_id,))
    return {"message": "规则已删除", "rule_id": rule_id}
