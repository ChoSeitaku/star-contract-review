"""系统与认证接口（§1.3.2 用户角色：系统管理员维护审批接入配置）。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, status

from .. import auth, config, db, security, seed
from ..schemas import (
    ConfigUpdateRequest,
    InitRequest,
    LoginRequest,
    MockApprovalCreateRequest,
)
from ..utils import now_str

router = APIRouter(prefix="/api/system", tags=["系统"])


@router.post("/init", summary="初始化系统（创建管理员与法务审核人账户）")
def init_system(payload: InitRequest) -> dict:
    if db.count("users") > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="系统已初始化，请直接登录"
        )

    stamp = now_str()
    db.insert(
        "users",
        {
            "username": payload.admin_username,
            "password_hash": security.hash_password(payload.admin_password),
            "display_name": "系统管理员",
            "role": "admin",
            "status": "active",
            "created_at": stamp,
        },
    )
    db.insert(
        "users",
        {
            "username": payload.reviewer_username,
            "password_hash": security.hash_password(payload.reviewer_password),
            "display_name": "法务审核人",
            "role": "reviewer",
            "status": "active",
            "created_at": stamp,
        },
    )
    return {
        "message": "初始化完成",
        "accounts": [
            {"username": payload.admin_username, "role": "admin"},
            {"username": payload.reviewer_username, "role": "reviewer"},
        ],
    }


@router.post("/login", summary="登录")
def login(payload: LoginRequest) -> dict:
    user = db.query_one("SELECT * FROM users WHERE username = ?", (payload.username,))
    if user is None or not security.verify_password(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )
    if user["status"] != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账户已被禁用")

    auth.purge_expired_sessions()
    token = auth.create_session(int(user["id"]))
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"] or user["username"],
            "role": user["role"],
        },
    }


@router.post("/logout", summary="退出登录")
def logout(
    authorization: str | None = Header(default=None),
    user: dict = Depends(auth.get_current_user),
) -> dict:
    if authorization and authorization.lower().startswith("bearer "):
        auth.destroy_session(authorization[7:].strip())
    return {"message": "已退出登录"}


@router.get("/me", summary="当前登录用户")
def me(user: dict = Depends(auth.get_current_user)) -> dict:
    return {"user": user}


@router.get("/config", summary="查看系统配置（管理员）")
def list_config(user: dict = Depends(auth.require_admin)) -> dict:
    rows = db.query_all("SELECT * FROM system_configs ORDER BY config_key")
    return {"configs": rows}


@router.put("/config", summary="更新系统配置（管理员）")
def update_config(
    payload: ConfigUpdateRequest, user: dict = Depends(auth.require_admin)
) -> dict:
    unknown = [key for key in payload.configs if key not in config.DEFAULT_CONFIGS]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的配置项：{', '.join(unknown)}",
        )
    for key, value in payload.configs.items():
        config.set_config(key, str(value))
    return {"message": "配置已更新", "updated": list(payload.configs)}


@router.post("/mock-approvals", summary="新增模拟审批单（管理员，用于演示）")
def create_mock_approval(
    payload: MockApprovalCreateRequest, user: dict = Depends(auth.require_admin)
) -> dict:
    """创建一条待处理的模拟审批单，便于演示阻塞与重试场景。"""
    exists = db.query_one(
        "SELECT id FROM mock_approvals WHERE approval_code = ?", (payload.approval_code,)
    )
    if exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"审批编号已存在：{payload.approval_code}",
        )

    try:
        form_data = json.loads(payload.form_data_json or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"form_data_json 非法：{exc}"
        ) from exc

    instance_id = f"AP-{payload.approval_code.replace('HT-', '').replace('-', '')}"
    if db.query_one("SELECT id FROM mock_approvals WHERE instance_id = ?", (instance_id,)):
        instance_id = f"{instance_id}-{db.count('mock_approvals') + 1}"

    stamp = now_str()
    db.insert(
        "mock_approvals",
        {
            "instance_id": instance_id,
            "approval_code": payload.approval_code,
            "approval_title": payload.approval_title,
            "applicant_name": payload.applicant_name,
            "department": payload.department,
            "approval_status": "pending",
            "current_node": "法务审核",
            "form_data_json": json.dumps(form_data, ensure_ascii=False),
            "comment_area": "",
            "applied_at": stamp,
            "created_at": stamp,
        },
    )

    if payload.attachment_file:
        source = config.CONTRACT_DIR / payload.attachment_file
        if not source.is_file():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"附件源文件不存在：{payload.attachment_file}",
            )
        db.insert(
            "mock_approval_attachments",
            {
                "instance_id": instance_id,
                "attachment_id": f"ATT-{instance_id}",
                "file_name": payload.attachment_file,
                "file_type": "contract",
                "source_path": payload.attachment_file,
                "created_at": stamp,
            },
        )

    return {
        "message": "模拟审批单已创建",
        "instance_id": instance_id,
        "approval_code": payload.approval_code,
        "attachment_file": payload.attachment_file,
    }


@router.post("/mock-reset", summary="重置模拟审批数据（管理员，用于重跑演示）")
def reset_mock(user: dict = Depends(auth.require_admin)) -> dict:
    """把系统恢复到初始可演示状态（保留用户账户与审查规则）。

    除清空审查任务与审批评论外，还会删除演示过程中新增的模拟审批单，
    保证重复运行演示脚本时结果完全一致。
    """
    for table in (
        "task_logs",
        "comment_logs",
        "rule_hits",
        "review_results",
        "contract_parses",
        "approval_attachments",
        "approval_tasks",
    ):
        db.execute(f"DELETE FROM {table}")

    # 移除演示期间新增的审批单，仅保留种子数据
    seed_ids = [item["instance_id"] for item in seed.MOCK_APPROVALS]
    placeholders = ", ".join("?" for _ in seed_ids)
    db.execute(
        f"DELETE FROM mock_approval_attachments WHERE instance_id NOT IN ({placeholders})",
        tuple(seed_ids),
    )
    db.execute(
        f"DELETE FROM mock_approvals WHERE instance_id NOT IN ({placeholders})",
        tuple(seed_ids),
    )

    # 恢复种子审批单（补回被删除的项，并清空评论区）
    seed.seed_mock_approvals()
    db.execute("UPDATE mock_approvals SET comment_area = '', approval_status = 'pending'")

    return {
        "message": "模拟数据已重置",
        "approval_tasks": db.count("approval_tasks"),
        "mock_approvals": db.count("mock_approvals"),
    }
