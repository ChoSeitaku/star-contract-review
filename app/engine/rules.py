"""规则匹配引擎（§1.3.6 审查规则要求）。

支持三种匹配模式：
  - `regex`    正则匹配，命中即产生风险
  - `contains` 包含匹配（`|` 分隔多个候选词），命中即产生风险
  - `missing`  缺失匹配，目标条款/字段未提取到时产生风险

规则的匹配目标 `match_target` 支持：
  - `full_text`     全文逐段检索
  - `field:{key}`   某个基本信息字段
  - `clause:{key}`  某一类条款

命中结果统一携带：规则名称、风险等级、命中证据（原文片段）、证据位置、建议说明。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .document import ParsedDocument

RISK_ORDER: dict[str, int] = {"高": 3, "中": 2, "低": 1}

# 证据片段最大长度
EVIDENCE_LIMIT = 200

# 句末标点（用于把命中点扩展为完整句子）
SENTENCE_BOUNDARY = "。；;！？!?\n"


@dataclass
class RuleHit:
    """一条规则命中结果。"""

    rule_code: str
    rule_name: str
    risk_level: str
    match_mode: str
    match_target: str
    evidence_text: str
    evidence_position: str
    suggestion_text: str

    def as_row(self) -> dict:
        return {
            "rule_code": self.rule_code,
            "rule_name": self.rule_name,
            "risk_level": self.risk_level,
            "evidence_text": self.evidence_text,
            "evidence_position": self.evidence_position,
            "suggestion_text": self.suggestion_text,
        }


def _clip(text: str, limit: int = EVIDENCE_LIMIT) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _sentence_around(text: str, start: int, end: int) -> str:
    """把命中位置扩展为所在句子，作为可读的原文证据片段。"""
    left = start
    while left > 0 and text[left - 1] not in SENTENCE_BOUNDARY:
        left -= 1
    right = end
    while right < len(text) and text[right] not in SENTENCE_BOUNDARY:
        right += 1
    snippet = text[left:right].strip()
    return _clip(snippet) or _clip(text)


def _compile(rule: dict) -> re.Pattern | None:
    """把规则编译为正则；编译失败返回 None（规则被跳过并记录原因）。"""
    mode = (rule.get("match_mode") or "").strip().lower()
    raw = rule.get("match_text") or ""
    try:
        if mode == "contains":
            alternatives = [item.strip() for item in raw.split("|") if item.strip()]
            if not alternatives:
                return None
            return re.compile("|".join(re.escape(item) for item in alternatives))
        if mode == "regex":
            return re.compile(raw) if raw else None
    except re.error:
        return None
    return None


def _target_text(rule: dict, basic: dict, clauses: dict, full_text: str) -> tuple[str, str, str]:
    """返回 (检索文本, 位置, 说明)。位置为空表示需要按段落定位。"""
    target = (rule.get("match_target") or "full_text").strip()

    if target.startswith("field:"):
        key = target.split(":", 1)[1]
        item = basic.get(key) or {}
        if item.get("status") == "found":
            return str(item.get("value") or ""), str(item.get("position") or ""), "field"
        return "", "", "field_missing"

    if target.startswith("clause:"):
        key = target.split(":", 1)[1]
        item = clauses.get(key) or {}
        if item.get("status") == "found":
            return str(item.get("value") or ""), str(item.get("position") or ""), "clause"
        return "", "", "clause_missing"

    return full_text, "", "full_text"


def _locate_position(document: ParsedDocument, needle: str) -> tuple[str, str]:
    """在文档段落中定位命中文本，返回 (位置, 所在段落原文)。"""
    probe = needle[:40]
    if probe:
        for para in document.paragraphs:
            if probe in para.text:
                return para.position, para.text
    return "", ""


def run_rules(
    rules: list[dict],
    document: ParsedDocument,
    basic: dict,
    clauses: dict,
) -> tuple[list[RuleHit], list[str]]:
    """执行规则匹配，返回 (命中列表, 警告列表)。"""
    full_text = document.full_text
    hits: list[RuleHit] = []
    warnings: list[str] = []

    for rule in rules:
        if (rule.get("rule_status") or "enabled").lower() != "enabled":
            continue

        mode = (rule.get("match_mode") or "").strip().lower()
        code = rule.get("rule_code") or ""
        name = rule.get("rule_name") or ""
        level = rule.get("risk_level") or "低"
        suggestion = rule.get("suggestion_text") or ""

        target_text, target_position, target_kind = _target_text(
            rule, basic, clauses, full_text
        )

        # 缺失模式：目标条款/字段未提取到即为命中
        if mode == "missing":
            keywords = rule.get("match_text") or ""
            evidence = ""
            if target_kind == "clause_missing":
                key = (rule.get("match_target") or "").split(":", 1)[-1]
                label = (clauses.get(key) or {}).get("clause_name") or key
                evidence = f"全文未发现「{label}」相关约定（检索关键词：{keywords}）"
            elif target_kind == "field_missing":
                key = (rule.get("match_target") or "").split(":", 1)[-1]
                label = (basic.get(key) or {}).get("field_name") or key
                evidence = f"合同中未提取到「{label}」（检索关键词：{keywords}）"
            elif target_kind == "field" and not target_text.strip():
                evidence = f"合同中未提取到该字段内容（检索关键词：{keywords}）"

            if evidence:
                hits.append(
                    RuleHit(
                        rule_code=code,
                        rule_name=name,
                        risk_level=level,
                        match_mode=mode,
                        match_target=rule.get("match_target") or "",
                        evidence_text=evidence,
                        evidence_position="全文",
                        suggestion_text=suggestion,
                    )
                )
            continue

        pattern = _compile(rule)
        if pattern is None:
            warnings.append(f"规则 {code} 的匹配表达式无效，已跳过：{rule.get('match_text')!r}")
            continue

        # 全文字段：逐段检索，便于精确定位证据位置
        if target_kind == "full_text":
            for para in document.paragraphs:
                match = pattern.search(para.text)
                if match:
                    hits.append(
                        RuleHit(
                            rule_code=code,
                            rule_name=name,
                            risk_level=level,
                            match_mode=mode,
                            match_target=rule.get("match_target") or "",
                            evidence_text=_sentence_around(para.text, match.start(), match.end()),
                            evidence_position=para.position,
                            suggestion_text=suggestion,
                        )
                    )
                    break
            continue

        # 字段/条款目标：目标缺失时按缺失处理，避免重复命中
        if not target_text.strip():
            continue

        match = pattern.search(target_text)
        if not match:
            continue

        evidence = _sentence_around(target_text, match.start(), match.end())
        position = target_position
        if target_kind == "clause":
            # 条款内命中：尝试精确定位到具体段落
            located, _ = _locate_position(document, evidence)
            if located:
                position = located

        hits.append(
            RuleHit(
                rule_code=code,
                rule_name=name,
                risk_level=level,
                match_mode=mode,
                match_target=rule.get("match_target") or "",
                evidence_text=evidence,
                evidence_position=position or "全文",
                suggestion_text=suggestion,
            )
        )

    hits.sort(key=lambda item: (-RISK_ORDER.get(item.risk_level, 0), item.rule_code))
    return hits, warnings


def highest_risk(levels: list[str]) -> str:
    """取最高风险等级；无输入时返回「低」。"""
    if not levels:
        return "低"
    return max(levels, key=lambda item: RISK_ORDER.get(item, 0))
