"""风险汇总与回写内容生成（§1.3.11 输出结果格式）。

产出四项：
  - 总风险等级：低 / 中 / 高（取命中规则的最高等级）
  - 中文摘要：对整体合同风险的总结
  - 审批关注点：列出审批人需要重点确认的事项
  - 回写内容：最终写入审批评论区的文本
"""

from __future__ import annotations

from .document import ParsedDocument
from .fields import BASIC_FIELD_DEFS, count_found
from .rules import RISK_ORDER, RuleHit, highest_risk

# 评论中最多列出的风险条数（保持评论区可读）
MAX_LISTED_RISKS = 8

# 亟需审批人确认的关键字段
CRITICAL_FIELDS = ("contract_no", "party_a", "party_b", "amount")


def _risk_label(level: str) -> str:
    return f"{level}风险"


def build_summary(
    document: ParsedDocument,
    basic: dict,
    clauses: dict,
    hits: list[RuleHit],
    overall: str,
) -> str:
    title = str(basic.get("contract_title", {}).get("value") or document.file_name)
    basic_found = count_found(basic)
    clause_found = count_found(clauses)

    counts = {"高": 0, "中": 0, "低": 0}
    for hit in hits:
        counts[hit.risk_level] = counts.get(hit.risk_level, 0) + 1

    parts = [
        f"本合同《{title}》解析出合同基本信息 {basic_found}/{len(BASIC_FIELD_DEFS)} 项、"
        f"条款 {clause_found}/{len(clauses)} 类。"
    ]

    if hits:
        parts.append(
            f"规则审查命中 {len(hits)} 条风险规则"
            f"（高风险 {counts.get('高', 0)} 条、中风险 {counts.get('中', 0)} 条、"
            f"低风险 {counts.get('低', 0)} 条），"
            f"主要风险集中在{'、'.join(hit.rule_name for hit in hits[:3])}。"
        )
    else:
        parts.append("规则审查未命中任何风险规则，合同主要条款齐备。")

    parts.append(f"总体风险等级评定为「{overall}」。")
    return "".join(parts)


def build_focus_points(
    basic: dict, clauses: dict, hits: list[RuleHit]
) -> list[dict]:
    """生成审批关注点列表。"""
    points: list[dict] = []

    for hit in hits:
        points.append(
            {
                "point": hit.rule_name,
                "detail": hit.suggestion_text,
                "risk_level": hit.risk_level,
                "rule_code": hit.rule_code,
                "evidence_position": hit.evidence_position,
            }
        )

    # 关键字段缺失单列为关注点（即使规则未覆盖）
    for key in CRITICAL_FIELDS:
        item = basic.get(key) or {}
        if item.get("status") == "found":
            continue
        if any(point["rule_code"] == f"FIELD-{key}" for point in points):
            continue
        points.append(
            {
                "point": f"{item.get('field_name') or key}未提取到",
                "detail": f"建议人工确认合同中是否载明{item.get('field_name') or key}，必要时要求申请人补充材料。",
                "risk_level": "中",
                "rule_code": f"FIELD-{key}",
                "evidence_position": "全文",
            }
        )

    # 关键条款缺失同样单列
    for clause_key, item in clauses.items():
        if item.get("status") != "missing":
            continue
        if clause_key not in {"payment", "breach", "dispute"}:
            continue
        points.append(
            {
                "point": f"{item.get('clause_name')}未提取到",
                "detail": f"建议人工确认合同是否约定{item.get('clause_name')}，缺失时要求补充后再行审批。",
                "risk_level": "中",
                "rule_code": f"CLAUSE-{clause_key}",
                "evidence_position": "全文",
            }
        )

    points.sort(key=lambda item: -RISK_ORDER.get(item.get("risk_level", "低"), 0))
    return points


def build_comment_text(
    basic: dict,
    hits: list[RuleHit],
    overall: str,
    summary: str,
    focus_points: list[dict],
    prefix: str = "【合同自动审查意见】",
    parse_note: str = "",
) -> str:
    """生成写入审批评论区的最终文本。"""
    lines: list[str] = [f"{prefix}风险等级：{overall}", ""]

    lines.append("一、总体意见")
    lines.append(summary)
    if parse_note:
        lines.append(parse_note)
    lines.append("")

    lines.append("二、风险提示")
    if hits:
        for index, hit in enumerate(hits[:MAX_LISTED_RISKS], start=1):
            position = f"（{hit.evidence_position}）" if hit.evidence_position else ""
            lines.append(f"{index}. [{hit.risk_level}] {hit.rule_name}{position}")
            lines.append(f"   原文：{hit.evidence_text}")
            lines.append(f"   建议：{hit.suggestion_text}")
        remaining = len(hits) - MAX_LISTED_RISKS
        if remaining > 0:
            lines.append(f"（其余 {remaining} 条低优先级风险详见系统审查结果明细）")
    else:
        lines.append("未命中风险规则。")
    lines.append("")

    lines.append("三、需重点关注")
    if focus_points:
        for point in focus_points[:6]:
            lines.append(f"- [{point['risk_level']}] {point['point']}")
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("—— 本意见由合同审批审查系统自动生成，仅供审批参考，不替代人工审批。")
    return "\n".join(lines)


def build_result(
    document: ParsedDocument,
    basic: dict,
    clauses: dict,
    hits: list[RuleHit],
    prefix: str = "【合同自动审查意见】",
    parse_note: str = "",
) -> dict:
    """汇总风险等级、摘要、关注点与回写内容。"""
    overall = highest_risk([hit.risk_level for hit in hits])
    summary = build_summary(document, basic, clauses, hits, overall)
    focus_points = build_focus_points(basic, clauses, hits)
    comment_text = build_comment_text(
        basic, hits, overall, summary, focus_points, prefix=prefix, parse_note=parse_note
    )
    return {
        "overall_risk_level": overall,
        "summary_text": summary,
        "focus_points": focus_points,
        "comment_text": comment_text,
    }
