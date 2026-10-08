"""审批系统适配层（§1.3.8 拉取模块 / 回写模块）。

本模块是整个系统与「审批系统」之间的唯一边界：待办拉取、审批详情查询、
附件下载、评论回写全部经由适配器完成。默认实现 `MockApprovalAdapter` 基于
本地模拟审批表，便于离线演示；对接真实审批系统时，只需实现同一套
`ApprovalAdapter` 接口并在 `get_adapter()` 中替换即可，上层流水线无需改动。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from . import config, db
from .utils import now_str, sha256_of_bytes


class ApprovalApiError(Exception):
    """审批系统接口调用失败（§1.3.4 阻塞原因之一）。"""


class ApprovalAdapter(ABC):
    """审批系统适配器接口。"""

    @abstractmethod
    def fetch_pending(self, limit: int) -> list[dict]:
        """拉取待处理审批单列表（§1.3.3 待办拉取工具）。"""

    @abstractmethod
    def fetch_detail(self, instance_id: str) -> dict:
        """查询单个审批单详情（§1.3.3 审批详情工具）。"""

    @abstractmethod
    def fetch_attachment(
        self, instance_id: str, attachment_id: str, file_name: str
    ) -> tuple[bytes, str, int]:
        """下载附件内容，返回 (字节内容, sha256, 字节数)。"""

    @abstractmethod
    def write_comment(self, instance_id: str, comment_text: str) -> str:
        """将审查意见写回审批评论区，返回回写响应文本。"""


class MockApprovalAdapter(ApprovalAdapter):
    """基于本地模拟审批表的适配器实现。"""

    def _guard_fetch(self) -> None:
        if config.get_bool_config("adapter_fail_enabled"):
            raise ApprovalApiError("模拟审批系统接口调用失败（adapter_fail_enabled=true）")

    def _guard_write(self) -> None:
        if config.get_bool_config("adapter_fail_write_enabled"):
            raise ApprovalApiError("模拟审批系统评论回写接口调用失败（adapter_fail_write_enabled=true）")

    # -- 拉取 ---------------------------------------------------------------
    def fetch_pending(self, limit: int) -> list[dict]:
        self._guard_fetch()
        rows = db.query_all(
            """
            SELECT instance_id, approval_code, approval_title, applicant_name,
                   department, applied_at, approval_status, current_node
            FROM mock_approvals
            WHERE approval_status = 'pending'
            ORDER BY applied_at ASC, id ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )
        results = []
        for row in rows:
            attachment_count = db.count(
                "mock_approval_attachments", "instance_id = ?", (row["instance_id"],)
            )
            results.append({**row, "attachment_count": attachment_count})
        return results

    # -- 详情 ---------------------------------------------------------------
    def fetch_detail(self, instance_id: str) -> dict:
        self._guard_fetch()
        row = db.query_one(
            "SELECT * FROM mock_approvals WHERE instance_id = ?", (instance_id,)
        )
        if row is None:
            raise ApprovalApiError(f"审批单不存在：{instance_id}")

        attachments = db.query_all(
            """
            SELECT attachment_id, file_name, file_type, source_path
            FROM mock_approval_attachments
            WHERE instance_id = ?
            ORDER BY id ASC
            """,
            (instance_id,),
        )
        try:
            form_data = json.loads(row["form_data_json"] or "{}")
        except json.JSONDecodeError:
            form_data = {}

        return {
            "instance_id": row["instance_id"],
            "approval_code": row["approval_code"],
            "approval_title": row["approval_title"],
            "applicant_name": row["applicant_name"],
            "department": row["department"],
            "approval_status": row["approval_status"],
            "current_node": row["current_node"],
            "applied_at": row["applied_at"],
            "form_data": form_data,
            "comment_area": row["comment_area"],
            "attachment_count": len(attachments),
            "attachments": attachments,
        }

    # -- 附件 ---------------------------------------------------------------
    def fetch_attachment(
        self, instance_id: str, attachment_id: str, file_name: str
    ) -> tuple[bytes, str, int]:
        self._guard_fetch()
        row = db.query_one(
            """
            SELECT source_path, file_name FROM mock_approval_attachments
            WHERE instance_id = ? AND attachment_id = ?
            """,
            (instance_id, attachment_id),
        )
        if row is None:
            raise ApprovalApiError(
                f"附件不存在：instance_id={instance_id}, attachment_id={attachment_id}"
            )

        source = config.CONTRACT_DIR / row["source_path"]
        if not source.is_file():
            raise ApprovalApiError(f"附件源文件缺失：{source}")

        data = source.read_bytes()

        max_mb = config.get_int_config("max_attachment_mb", 20)
        if max_mb > 0 and len(data) > max_mb * 1024 * 1024:
            raise ApprovalApiError(f"附件体积超过上限 {max_mb}MB：{file_name}")

        return data, sha256_of_bytes(data), len(data)

    # -- 回写 ---------------------------------------------------------------
    def write_comment(self, instance_id: str, comment_text: str) -> str:
        self._guard_write()
        row = db.query_one(
            "SELECT comment_area FROM mock_approvals WHERE instance_id = ?", (instance_id,)
        )
        if row is None:
            raise ApprovalApiError(f"审批单不存在：{instance_id}")

        stamp = now_str()
        block = f"[{stamp}] 合同审查系统：\n{comment_text}"
        existing = (row["comment_area"] or "").strip()
        merged = f"{existing}\n\n{block}" if existing else block

        db.update(
            "mock_approvals", {"comment_area": merged}, "instance_id = ?", (instance_id,)
        )
        return f"评论回写成功：审批单 {instance_id} 于 {stamp} 收到审查意见（{len(comment_text)} 字）"


_adapter: ApprovalAdapter | None = None


def get_adapter() -> ApprovalAdapter:
    """返回当前生效的审批系统适配器。

    接入真实审批系统时，在此处按配置返回对应的适配器实现即可。
    """
    global _adapter
    if _adapter is None:
        _adapter = MockApprovalAdapter()
    return _adapter
