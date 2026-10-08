"""请求模型（Pydantic）。响应统一使用普通字典，与项目既有约定保持一致。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

RiskLevel = Literal["低", "中", "高"]
RuleStatus = Literal["enabled", "disabled"]
MatchMode = Literal["regex", "contains", "missing"]
HitStatus = Literal["hit", "dismissed"]


class InitRequest(BaseModel):
    admin_username: str = Field(default="admin", min_length=1, max_length=60)
    admin_password: str = Field(default="admin123", min_length=6, max_length=128)
    reviewer_username: str = Field(default="reviewer", min_length=1, max_length=60)
    reviewer_password: str = Field(default="reviewer123", min_length=6, max_length=128)

    @field_validator("admin_username", "reviewer_username")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=128)


class PullRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=200)


class DownloadAttachmentRequest(BaseModel):
    instance_id: str = Field(min_length=1, max_length=60)
    attachment_id: str = Field(min_length=1, max_length=60)
    file_name: str = Field(default="contract", max_length=200)


class ParseDocumentRequest(BaseModel):
    document_id: str = Field(min_length=1, max_length=60)


class RunRulesRequest(BaseModel):
    case_id: int = Field(ge=1)


class SaveReviewResultRequest(BaseModel):
    case_id: int = Field(ge=1)
    overall_risk_level: RiskLevel
    summary_text: str = Field(default="", max_length=4000)
    focus_points_json: str = Field(default="[]", max_length=20000)
    comment_text: str = Field(default="", max_length=20000)


class WriteCommentRequest(BaseModel):
    instance_id: str = Field(min_length=1, max_length=60)
    review_id: int = Field(ge=1)


class RuleUpsertRequest(BaseModel):
    rule_code: str = Field(min_length=1, max_length=40)
    rule_name: str = Field(min_length=1, max_length=120)
    risk_level: RiskLevel = "中"
    rule_status: RuleStatus = "enabled"
    match_mode: MatchMode = "contains"
    match_text: str = Field(default="", max_length=1000)
    suggestion_text: str = Field(default="", max_length=2000)
    match_target: str = Field(default="full_text", max_length=120)

    @field_validator("rule_code", "rule_name")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class ConfigUpdateRequest(BaseModel):
    configs: dict[str, str]


class MockApprovalCreateRequest(BaseModel):
    """演示用：新增一条模拟审批单。"""

    approval_code: str = Field(min_length=1, max_length=60)
    approval_title: str = Field(min_length=1, max_length=200)
    applicant_name: str = Field(default="演示申请人", max_length=60)
    department: str = Field(default="演示部门", max_length=60)
    attachment_file: str = Field(default="", max_length=200)
    form_data_json: str = Field(default="{}", max_length=4000)


class HitStatusRequest(BaseModel):
    hit_status: HitStatus
