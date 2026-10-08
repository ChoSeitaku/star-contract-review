"""种子数据：审查规则与模拟审批单（启动时幂等写入）。

- 规则集覆盖需求 §1.3.6 要求的全部风险主题：预付款比例、付款周期、自动续约、
  违约责任、管辖地、主体信息缺失、金额缺失、保密缺失、数据处理、知识产权、
  验收标准缺失、交付条款缺失。
- 模拟审批单覆盖闭环演示所需的全部终态：正常（docx / 文本 PDF / 扫描件 OCR）、
  以及三类解析期阻塞（附件缺失、文档内容为空、图片无法识别）。
"""

from __future__ import annotations

import json

from . import db
from .utils import now_str

# ---------------------------------------------------------------------------
# 审查规则（§1.3.6 审查规则要求）
# match_target: field:{key} / clause:{key} / full_text
# match_mode:   regex（正则）/ contains（包含）/ missing（缺失即命中）
# ---------------------------------------------------------------------------
RULES: tuple[dict, ...] = (
    {
        "rule_code": "PAY-001",
        "rule_name": "预付款比例过高",
        "risk_level": "高",
        "match_mode": "regex",
        "match_target": "clause:payment",
        "match_text": r"(预付款|首付款)[^。]{0,40}?([3-9]\d)\s*%|([3-9]\d)\s*%[^。]{0,40}?(预付款|首付款)",
        "suggestion_text": "建议将预付款比例压降至 30% 以内，并设置进度款与验收后尾款节点，降低资金占用风险。",
    },
    {
        "rule_code": "PAY-002",
        "rule_name": "付款周期过长",
        "risk_level": "中",
        "match_mode": "regex",
        "match_target": "clause:payment",
        "match_text": r"(6\d|[7-9]\d|\d{3,})\s*个?\s*(工作日|日|天)",
        "suggestion_text": "建议将付款周期缩短至 60 日以内，并明确逾期付款的违约责任，改善现金流表现。",
    },
    {
        "rule_code": "PAY-003",
        "rule_name": "一次性付款",
        "risk_level": "低",
        "match_mode": "contains",
        "match_target": "clause:payment",
        "match_text": "一次性支付|一次性付清|一次性结清",
        "suggestion_text": "建议改为分阶段付款，将付款节点与交付、验收进度挂钩。",
    },
    {
        "rule_code": "REN-001",
        "rule_name": "自动续约条款",
        "risk_level": "中",
        "match_mode": "contains",
        "match_target": "full_text",
        "match_text": "自动续约|自动顺延|到期后自动续展",
        "suggestion_text": "建议明确续约的书面通知期限与不续约的退出机制，避免被动续期。",
    },
    {
        "rule_code": "BRE-001",
        "rule_name": "违约责任条款缺失",
        "risk_level": "高",
        "match_mode": "missing",
        "match_target": "clause:breach",
        "match_text": "违约责任",
        "suggestion_text": "建议补充违约责任条款，明确双方违约情形、违约金计算方式及赔偿范围。",
    },
    {
        "rule_code": "BRE-002",
        "rule_name": "违约金比例过高",
        "risk_level": "高",
        "match_mode": "regex",
        "match_target": "full_text",
        "match_text": r"(违约金|罚息)[^。]{0,40}?([3-9]\d)\s*%|([3-9]\d)\s*%[^。]{0,40}?(违约金|罚息)",
        "suggestion_text": "建议核实违约金比例的合理性（通常不超过合同总额的 30%），并调整为双方对等约定。",
    },
    {
        "rule_code": "DISP-001",
        "rule_name": "争议管辖地缺失",
        "risk_level": "中",
        "match_mode": "missing",
        "match_target": "clause:dispute",
        "match_text": "争议解决|管辖|仲裁",
        "suggestion_text": "建议补充争议解决条款，明确管辖法院或仲裁机构，避免争议发生时管辖不明。",
    },
    {
        "rule_code": "DISP-002",
        "rule_name": "管辖地约定不利",
        "risk_level": "中",
        "match_mode": "contains",
        "match_target": "clause:dispute",
        "match_text": "乙方所在地|对方所在地|供方所在地",
        "suggestion_text": "建议争取约定甲方所在地法院管辖或选择中立仲裁机构，降低异地诉讼成本。",
    },
    {
        "rule_code": "PART-001",
        "rule_name": "签约主体信息缺失",
        "risk_level": "高",
        "match_mode": "missing",
        "match_target": "field:party_a",
        "match_text": "甲方",
        "suggestion_text": "建议补充完整的签约主体名称、统一社会信用代码及联系人信息，确保合同主体适格。",
    },
    {
        "rule_code": "AMT-001",
        "rule_name": "合同金额缺失",
        "risk_level": "高",
        "match_mode": "missing",
        "match_target": "field:amount",
        "match_text": "合同金额",
        "suggestion_text": "建议补充合同总金额，并注明含税/不含税及适用税率，避免结算争议。",
    },
    {
        "rule_code": "CUR-001",
        "rule_name": "币种未明确",
        "risk_level": "低",
        "match_mode": "missing",
        "match_target": "field:currency",
        "match_text": "币种",
        "suggestion_text": "建议明确结算币种及汇率折算规则，规避汇率波动风险。",
    },
    {
        "rule_code": "CONF-001",
        "rule_name": "保密条款缺失",
        "risk_level": "中",
        "match_mode": "missing",
        "match_target": "clause:confidentiality",
        "match_text": "保密",
        "suggestion_text": "建议补充保密条款，明确保密信息范围、保密期限及违反保密义务的违约责任。",
    },
    {
        "rule_code": "DATA-001",
        "rule_name": "数据处理条款缺失",
        "risk_level": "高",
        "match_mode": "missing",
        "match_target": "clause:data",
        "match_text": "数据",
        "suggestion_text": "建议补充数据处理条款，明确数据使用范围、留存期限、安全义务与合规责任，满足数据合规要求。",
    },
    {
        "rule_code": "IP-001",
        "rule_name": "知识产权归属缺失",
        "risk_level": "中",
        "match_mode": "missing",
        "match_target": "clause:ip",
        "match_text": "知识产权|著作权|专利",
        "suggestion_text": "建议补充知识产权归属条款，明确成果物及背景知识产权的权属与使用许可范围。",
    },
    {
        "rule_code": "ACC-001",
        "rule_name": "验收标准缺失",
        "risk_level": "中",
        "match_mode": "missing",
        "match_target": "clause:acceptance",
        "match_text": "验收",
        "suggestion_text": "建议补充验收标准条款，明确验收流程、验收时限、判定标准及不合格的处理方式。",
    },
    {
        "rule_code": "DEL-001",
        "rule_name": "交付条款缺失",
        "risk_level": "中",
        "match_mode": "missing",
        "match_target": "clause:delivery",
        "match_text": "交付",
        "suggestion_text": "建议补充交付条款，明确交付内容、交付时间、交付方式及交付验收衔接安排。",
    },
)


# ---------------------------------------------------------------------------
# 模拟审批单（§1.3.2 审批系统）
# ---------------------------------------------------------------------------
MOCK_APPROVALS: tuple[dict, ...] = (
    {
        "instance_id": "AP-001",
        "approval_code": "HT-2024-001",
        "approval_title": "XX系统软件开发服务合同",
        "applicant_name": "张伟",
        "department": "技术部",
        "applied_at": "2024-01-05 09:20:00",
        "form_data": {
            "合同类型": "软件开发",
            "合同金额（元）": "980000",
            "对方单位": "云启软件服务有限公司",
            "是否涉及数据处理": "是",
            "紧急程度": "普通",
        },
        "attachments": [
            {
                "attachment_id": "ATT-001",
                "file_name": "software_dev_contract.docx",
                "file_type": "contract",
                "source_path": "software_dev_contract.docx",
            }
        ],
    },
    {
        "instance_id": "AP-002",
        "approval_code": "HT-2024-002",
        "approval_title": "设备采购合同",
        "applicant_name": "李娜",
        "department": "采购部",
        "applied_at": "2024-03-08 14:05:00",
        "form_data": {
            "合同类型": "设备采购",
            "合同金额（元）": "1200000",
            "对方单位": "恒信机电设备有限公司",
            "是否涉及数据处理": "否",
            "紧急程度": "普通",
        },
        "attachments": [
            {
                "attachment_id": "ATT-002",
                "file_name": "equipment_purchase.pdf",
                "file_type": "contract",
                "source_path": "equipment_purchase.pdf",
            }
        ],
    },
    {
        "instance_id": "AP-003",
        "approval_code": "HT-2024-003",
        "approval_title": "服务外包框架合同",
        "applicant_name": "王强",
        "department": "运维部",
        "applied_at": "2024-04-02 10:40:00",
        "form_data": {
            "合同类型": "服务外包",
            "合同金额（元）": "500000",
            "对方单位": "博远信息技术有限公司",
            "是否涉及数据处理": "是",
            "紧急程度": "加急",
        },
        "attachments": [
            {
                "attachment_id": "ATT-003",
                "file_name": "outsourcing_scan.pdf",
                "file_type": "scan",
                "source_path": "outsourcing_scan.pdf",
            }
        ],
    },
    {
        "instance_id": "AP-004",
        "approval_code": "HT-2024-004",
        "approval_title": "年度框架协议",
        "applicant_name": "赵敏",
        "department": "商务部",
        "applied_at": "2024-05-11 16:30:00",
        "form_data": {
            "合同类型": "框架协议",
            "合同金额（元）": "待定",
            "对方单位": "待确认",
            "是否涉及数据处理": "否",
            "紧急程度": "普通",
        },
        # 刻意不提供附件：演示「附件缺失」阻塞
        "attachments": [],
    },
    {
        "instance_id": "AP-005",
        "approval_code": "HT-2024-005",
        "approval_title": "空白模板合同",
        "applicant_name": "陈静",
        "department": "行政部",
        "applied_at": "2024-05-20 11:15:00",
        "form_data": {
            "合同类型": "其他",
            "合同金额（元）": "0",
            "对方单位": "待确认",
            "是否涉及数据处理": "否",
            "紧急程度": "普通",
        },
        "attachments": [
            {
                "attachment_id": "ATT-005",
                "file_name": "blank_template.docx",
                "file_type": "contract",
                "source_path": "blank_template.docx",
            }
        ],
    },
    {
        "instance_id": "AP-006",
        "approval_code": "HT-2024-006",
        "approval_title": "扫描版劳动合同",
        "applicant_name": "刘洋",
        "department": "人力资源部",
        "applied_at": "2024-06-03 09:05:00",
        "form_data": {
            "合同类型": "劳动合同",
            "合同金额（元）": "180000",
            "对方单位": "张某某",
            "是否涉及数据处理": "否",
            "紧急程度": "普通",
        },
        "attachments": [
            {
                "attachment_id": "ATT-006",
                "file_name": "labor_scan.pdf",
                "file_type": "scan",
                "source_path": "labor_scan.pdf",
            }
        ],
    },
    {
        "instance_id": "AP-007",
        "approval_code": "HT-2024-007",
        "approval_title": "信息技术咨询服务合同",
        "applicant_name": "孙婷",
        "department": "战略部",
        "applied_at": "2024-06-12 13:50:00",
        "form_data": {
            "合同类型": "咨询服务",
            "合同金额（元）": "200000",
            "对方单位": "明远管理咨询有限公司",
            "是否涉及数据处理": "是",
            "紧急程度": "普通",
        },
        "attachments": [
            {
                "attachment_id": "ATT-007",
                "file_name": "simple_service_contract.docx",
                "file_type": "contract",
                "source_path": "simple_service_contract.docx",
            }
        ],
    },
)


def seed_rules() -> int:
    """写入缺失的审查规则（按 rule_code 幂等），返回新增条数。"""
    created = 0
    for rule in RULES:
        exists = db.query_one(
            "SELECT id FROM review_rules WHERE rule_code = ?", (rule["rule_code"],)
        )
        if exists:
            continue
        db.insert(
            "review_rules",
            {
                "rule_code": rule["rule_code"],
                "rule_name": rule["rule_name"],
                "risk_level": rule["risk_level"],
                "rule_status": "enabled",
                "match_mode": rule["match_mode"],
                "match_text": rule["match_text"],
                "suggestion_text": rule["suggestion_text"],
                "match_target": rule["match_target"],
                "updated_at": now_str(),
            },
        )
        created += 1
    return created


def seed_mock_approvals() -> int:
    """写入缺失的模拟审批单与附件（按 instance_id 幂等），返回新增审批单数。"""
    created = 0
    stamp = now_str()
    for item in MOCK_APPROVALS:
        exists = db.query_one(
            "SELECT id FROM mock_approvals WHERE instance_id = ?", (item["instance_id"],)
        )
        if exists:
            continue
        db.insert(
            "mock_approvals",
            {
                "instance_id": item["instance_id"],
                "approval_code": item["approval_code"],
                "approval_title": item["approval_title"],
                "applicant_name": item["applicant_name"],
                "department": item["department"],
                "approval_status": "pending",
                "current_node": "法务审核",
                "form_data_json": json.dumps(item["form_data"], ensure_ascii=False),
                "comment_area": "",
                "applied_at": item["applied_at"],
                "created_at": stamp,
            },
        )
        for attachment in item["attachments"]:
            db.insert(
                "mock_approval_attachments",
                {
                    "instance_id": item["instance_id"],
                    "attachment_id": attachment["attachment_id"],
                    "file_name": attachment["file_name"],
                    "file_type": attachment["file_type"],
                    "source_path": attachment["source_path"],
                    "created_at": stamp,
                },
            )
        created += 1
    return created


def seed_all() -> None:
    """启动时调用：幂等写入全部种子数据。"""
    rules = seed_rules()
    approvals = seed_mock_approvals()
    if rules or approvals:
        print(f"[star-contract-review] 种子数据写入完成：规则 +{rules}，模拟审批单 +{approvals}")
