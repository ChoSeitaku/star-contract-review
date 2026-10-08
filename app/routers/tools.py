"""工具服务接口（§1.3.10 工具接口要求）。

7 个工具函数的 HTTP 封装，函数签名与 services/tools.py 一一对应，
便于外部系统按工具方式调用。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from .. import auth
from ..approval_adapter import ApprovalApiError
from ..schemas import (
    DownloadAttachmentRequest,
    ParseDocumentRequest,
    PullRequest,
    RunRulesRequest,
    SaveReviewResultRequest,
    WriteCommentRequest,
)
from ..services import tools

router = APIRouter(prefix="/api/tools", tags=["工具服务"])


def _handle(exc: Exception) -> HTTPException:
    """把工具层异常转换成合适的 HTTP 状态码。"""
    if isinstance(exc, ApprovalApiError):
        # 审批系统接口调用失败：上游不可用
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    if isinstance(exc, tools.ToolError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"工具执行失败：{exc}"
    )


@router.post("/list-pending-approvals", summary="拉取待处理审批单列表（含去重保存）")
def list_pending_approvals(
    payload: PullRequest, user: dict = Depends(auth.get_current_user)
) -> dict:
    try:
        return tools.list_pending_contract_approvals(payload.limit)
    except Exception as exc:
        raise _handle(exc) from exc


@router.get("/approvals/{instance_id}", summary="查询单个审批单详情")
def get_approval(instance_id: str, user: dict = Depends(auth.get_current_user)) -> dict:
    try:
        return tools.get_contract_approval(instance_id)
    except Exception as exc:
        raise _handle(exc) from exc


@router.post("/download-attachment", summary="下载合同附件并返回本地路径与校验信息")
def download_attachment(
    payload: DownloadAttachmentRequest, user: dict = Depends(auth.get_current_user)
) -> dict:
    try:
        return tools.download_contract_attachment(
            payload.instance_id, payload.attachment_id, payload.file_name
        )
    except Exception as exc:
        raise _handle(exc) from exc


@router.post("/parse-document", summary="解析合同文档并返回结构化字段")
def parse_document(
    payload: ParseDocumentRequest, user: dict = Depends(auth.get_current_user)
) -> dict:
    try:
        return tools.parse_contract_document(payload.document_id)
    except Exception as exc:
        raise _handle(exc) from exc


@router.post("/run-rules", summary="执行规则审查并返回命中结果与风险结论")
def run_rules(
    payload: RunRulesRequest, user: dict = Depends(auth.get_current_user)
) -> dict:
    try:
        return tools.run_contract_rules(payload.case_id)
    except Exception as exc:
        raise _handle(exc) from exc


@router.post("/save-review-result", summary="保存审查结果")
def save_review_result(
    payload: SaveReviewResultRequest, user: dict = Depends(auth.get_current_user)
) -> dict:
    try:
        return tools.save_review_result(
            payload.case_id,
            payload.overall_risk_level,
            payload.summary_text,
            payload.focus_points_json,
            payload.comment_text,
        )
    except Exception as exc:
        raise _handle(exc) from exc


@router.post("/write-comment", summary="将审查意见写回审批评论区")
def write_comment(
    payload: WriteCommentRequest, user: dict = Depends(auth.get_current_user)
) -> dict:
    try:
        return tools.write_approval_comment(payload.instance_id, payload.review_id)
    except Exception as exc:
        raise _handle(exc) from exc
