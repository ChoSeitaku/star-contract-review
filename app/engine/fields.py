"""字段与条款提取（§1.3.5 合同解析字段要求）。

从解析后的段落结构中提取：
  - 合同基本信息 8 项：合同标题、合同编号、签约主体、对方名称、金额、币种、生效时间、到期时间
  - 条款信息 8 类：付款、交付、验收、违约、保密、数据、知识产权、争议解决

每个字段统一保留 `value / evidence / position / status`，其中 position 为
「第N页/第M段」或「第N页/第X条」，status 为 found / missing。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field

from .document import Paragraph, ParsedDocument

# ---------------------------------------------------------------------------
# 定义
# ---------------------------------------------------------------------------
BASIC_FIELD_DEFS: tuple[tuple[str, str], ...] = (
    ("contract_title", "合同标题"),
    ("contract_no", "合同编号"),
    ("party_a", "签约主体"),
    ("party_b", "对方名称"),
    ("amount", "金额"),
    ("currency", "币种"),
    ("effective_date", "生效时间"),
    ("expire_date", "到期时间"),
)

CLAUSE_DEFS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("payment", "付款条款", ("付款", "支付", "结算", "账期")),
    ("delivery", "交付条款", ("交付", "供货", "移交")),
    ("acceptance", "验收条款", ("验收",)),
    ("breach", "违约条款", ("违约",)),
    ("confidentiality", "保密条款", ("保密",)),
    ("data", "数据条款", ("数据",)),
    ("ip", "知识产权条款", ("知识产权", "著作权", "专利")),
    ("dispute", "争议解决条款", ("争议", "管辖", "仲裁", "诉讼")),
)

# 条款标题形如「第三条 付款方式」或「三、付款方式」
CLAUSE_HEADING_RE = re.compile(r"^\s*(?:第\s*([一二三四五六七八九十百零\d]+)\s*条|[（(]?([一二三四五六七八九十]+)[）)]?\s*、)")
CLAUSE_NUMBER_RE = re.compile(r"^\s*第\s*([一二三四五六七八九十百零\d]+)\s*条")

CURRENCY_MAP = (
    ("人民币", "人民币"),
    ("美元", "美元"),
    ("欧元", "欧元"),
    ("港币", "港币"),
    ("日元", "日元"),
    ("英镑", "英镑"),
    ("CNY", "人民币"),
    ("USD", "美元"),
    ("EUR", "欧元"),
)

SNIPPET_LIMIT = 160


def _snippet(text: str, limit: int = SNIPPET_LIMIT) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


# ---------------------------------------------------------------------------
# 段落分节
# ---------------------------------------------------------------------------
@dataclass
class Section:
    """一个条款小节：标题 + 正文段落。"""

    heading: str
    head_para: Paragraph | None
    body_paras: list[Paragraph] = dataclass_field(default_factory=list)

    @property
    def clause_no(self) -> str:
        match = CLAUSE_NUMBER_RE.match(self.heading or "")
        return f"第{match.group(1)}条" if match else ""

    @property
    def body_text(self) -> str:
        return "\n".join(p.text for p in self.body_paras)

    @property
    def text(self) -> str:
        parts = [self.heading] if self.heading else []
        parts.extend(p.text for p in self.body_paras)
        return "\n".join(part for part in parts if part)

    @property
    def position(self) -> str:
        anchor = self.head_para or (self.body_paras[0] if self.body_paras else None)
        if anchor is None:
            return ""
        if self.clause_no:
            return f"第{anchor.page_no}页/{self.clause_no}"
        return anchor.position


def build_sections(paragraphs: list[Paragraph]) -> list[Section]:
    """按条款标题把段落切分为小节；首个标题之前的内容归入前言小节。"""
    sections: list[Section] = []
    current = Section(heading="", head_para=None)

    for para in paragraphs:
        if CLAUSE_HEADING_RE.match(para.text):
            sections.append(current)
            current = Section(heading=para.text, head_para=para)
        else:
            current.body_paras.append(para)
    sections.append(current)

    return [s for s in sections if s.heading or s.body_paras]


# ---------------------------------------------------------------------------
# 条款提取
# ---------------------------------------------------------------------------
def _extract_clauses(sections: list[Section]) -> dict[str, dict]:
    claimed: set[int] = set()
    assignment: dict[str, int] = {}

    def match_section(keywords: tuple[str, ...], use_body: bool) -> int | None:
        for position, section in enumerate(sections):
            if position in claimed:
                continue
            haystack = section.body_text if use_body else section.heading
            if any(keyword in haystack for keyword in keywords):
                return position
        return None

    # 第一轮：标题直接命中（最可靠）
    for key, _name, keywords in CLAUSE_DEFS:
        index = match_section(keywords, use_body=False)
        if index is not None:
            claimed.add(index)
            assignment[key] = index

    # 第二轮：正文命中，且该小节未被占用
    for key, _name, keywords in CLAUSE_DEFS:
        if key in assignment:
            continue
        index = match_section(keywords, use_body=True)
        if index is not None:
            claimed.add(index)
            assignment[key] = index

    result: dict[str, dict] = {}
    for key, name, keywords in CLAUSE_DEFS:
        index = assignment.get(key)
        if index is None:
            result[key] = {
                "clause_key": key,
                "clause_name": name,
                "value": "",
                "evidence": "",
                "position": "",
                "status": "missing",
                "keywords": "、".join(keywords),
            }
            continue

        section = sections[index]
        full = section.text.strip()
        result[key] = {
            "clause_key": key,
            "clause_name": name,
            "value": full,
            "evidence": _snippet(full),
            "position": section.position,
            "status": "found",
            "keywords": "、".join(keywords),
        }
    return result


# ---------------------------------------------------------------------------
# 基本信息提取
# ---------------------------------------------------------------------------
def _locate(paragraphs: list[Paragraph], pattern: re.Pattern) -> tuple[re.Match, Paragraph] | None:
    for para in paragraphs:
        match = pattern.search(para.text)
        if match:
            return match, para
    return None


def _field(
    key: str,
    name: str,
    value: str,
    evidence: str,
    position: str,
    status: str,
) -> dict:
    return {
        "field_key": key,
        "field_name": name,
        "value": value,
        "evidence": evidence if status == "found" else "",
        "position": position if status == "found" else "",
        "status": status,
    }


def _match_title(paragraphs: list[Paragraph]) -> tuple[str, Paragraph] | None:
    """合同标题：首个以「合同 / 协议」结尾的短段落。"""
    for para in paragraphs:
        text = para.text.strip()
        if not text or len(text) > 40:
            continue
        if re.search(r"(合同|协议)$", text) and not re.search(r"[：:]", text):
            return text, para
    return None


def _extract_basic(paragraphs: list[Paragraph]) -> dict[str, dict]:
    result: dict[str, dict] = {}

    # 合同标题
    matched = _match_title(paragraphs)
    if matched:
        result["contract_title"] = _field(
            "contract_title", "合同标题", matched[0], matched[0], matched[1].position, "found"
        )

    # 单值字段：正则 -> (字段键, 字段名, 取值函数)
    patterns: tuple[tuple[str, str, re.Pattern, object], ...] = (
        (
            "contract_no",
            "合同编号",
            re.compile(r"合同编号\s*[：:]\s*([A-Za-z0-9\-_/]+)"),
            lambda m: m.group(1),
        ),
        (
            "party_a",
            "签约主体",
            re.compile(r"甲方(?:[（(][^）)]{0,12}[）)])?\s*[：:]\s*([^\s，,；;。]{2,40})"),
            lambda m: m.group(1),
        ),
        (
            "party_b",
            "对方名称",
            re.compile(r"乙方(?:[（(][^）)]{0,12}[）)])?\s*[：:]\s*([^\s，,；;。]{2,40})"),
            lambda m: m.group(1),
        ),
        (
            "amount",
            "金额",
            re.compile(r"(?:合同总金额|合同金额|合同总价|总金额)\s*[：:]\s*([^\n]+)"),
            None,  # 需要二次抽取数字，单独处理
        ),
        (
            "effective_date",
            "生效时间",
            re.compile(r"自\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*起\s*生效"),
            lambda m: f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
        ),
        (
            "expire_date",
            "到期时间",
            re.compile(r"有效期至\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"),
            lambda m: f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
        ),
    )

    for key, name, pattern, getter in patterns:
        found = _locate(paragraphs, pattern)
        if found is None:
            result[key] = _field(key, name, "", "", "", "missing")
            continue
        match, para = found
        if key == "amount":
            value = _extract_amount(match.group(1))
            if not value:
                result[key] = _field(key, name, "", "", "", "missing")
                continue
        else:
            value = getter(match)  # type: ignore[operator]
        result[key] = _field(key, name, value, para.text.strip(), para.position, "found")

    # 币种：全文检索
    result["currency"] = _extract_currency(paragraphs)

    # 保证字段顺序与定义一致
    ordered: dict[str, dict] = {}
    for key, name in BASIC_FIELD_DEFS:
        ordered[key] = result.get(key, _field(key, name, "", "", "", "missing"))
    return ordered


def _extract_amount(raw: str) -> str:
    """从金额描述中抽取数值，例如「人民币玖拾捌万元整（¥980,000）」-> 980000。"""
    match = re.search(r"[¥￥]?\s*(\d[\d,]*(?:\.\d+)?)", raw)
    if match:
        return match.group(1).replace(",", "")
    match = re.search(r"([零壹贰叁肆伍陆柒捌玖拾佰仟万亿元整圆角分]+)", raw)
    if match:
        return match.group(1)
    return ""


def _extract_currency(paragraphs: list[Paragraph]) -> dict:
    for para in paragraphs:
        for token, name in CURRENCY_MAP:
            if token in para.text:
                return _field("currency", "币种", name, para.text.strip(), para.position, "found")
    return _field("currency", "币种", "", "", "", "missing")


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------
def extract_fields(document: ParsedDocument) -> tuple[dict, dict]:
    """返回 (基本信息字段, 条款信息字段)。"""
    sections = build_sections(document.paragraphs)
    basic = _extract_basic(document.paragraphs)
    clauses = _extract_clauses(sections)
    return basic, clauses


def count_found(fields: dict) -> int:
    return sum(1 for item in fields.values() if item.get("status") == "found")
