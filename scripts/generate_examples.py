"""生成示例合同文件（§1.3.12 验收标准：示例合同文件）。

生成内容：
  examples/contracts/software_dev_contract.docx   软件开发合同（高风险）
  examples/contracts/equipment_purchase.pdf       设备采购合同（文本型 PDF，中风险）
  examples/contracts/outsourcing_scan.pdf         服务外包合同（扫描件，走 OCR 路径）
  examples/contracts/simple_service_contract.docx 咨询合同（低风险）
  examples/contracts/blank_template.docx          空白模板（触发「文档内容为空」阻塞）
  examples/contracts/labor_scan.pdf               劳动合同扫描件（无标注，触发「图片无法识别」阻塞）
  examples/contracts/ocr_labels/*.pageN.txt       扫描件 OCR 标注（模拟识别结果）

用法：
    .venv/Scripts/python.exe scripts/generate_examples.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import pymupdf  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app import config  # noqa: E402
from app.utils import safe_slug  # noqa: E402

# 扫描件渲染参数（A4 @150dpi）
PAGE_SIZE = (1240, 1754)
MARGIN_X = 90
MARGIN_Y = 120
LINE_HEIGHT = 34
FONT_SIZE = 22

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
)


# ---------------------------------------------------------------------------
# 合同正文（段落列表；扫描件按页拆分）
# ---------------------------------------------------------------------------
SOFTWARE_DEV = {
    "file": "software_dev_contract.docx",
    "kind": "docx",
    "paragraphs": [
        "XX系统软件开发服务合同",
        "合同编号：HT-2024-001",
        "甲方（委托方）：星辰科技有限公司",
        "乙方（受托方）：云启软件服务有限公司",
        "合同总金额：人民币玖拾捌万元整（¥980,000）",
        "第一条 项目内容",
        "乙方向甲方提供 XX 系统的软件开发、部署与上线支持服务。",
        "第二条 付款方式",
        "本合同签订后 10 个工作日内，甲方向乙方支付合同总额 40% 的预付款；项目验收合格后 45 个工作日内支付剩余款项。",
        "第三条 交付条款",
        "乙方应于 2024 年 6 月 30 日前完成系统开发并交付甲方使用。",
        "第四条 违约责任",
        "任何一方违反本合同约定的，应向对方支付合同总额 50% 的违约金。",
        "第五条 争议解决",
        "因本合同产生的争议，双方应友好协商解决；协商不成的，提交乙方所在地人民法院管辖。",
        "第六条 生效与期限",
        "本合同自 2024 年 1 月 1 日起生效，有效期至 2025 年 12 月 31 日。",
    ],
}

EQUIPMENT_PURCHASE = {
    "file": "equipment_purchase.pdf",
    "kind": "text_pdf",
    "paragraphs": [
        "设备采购合同",
        "合同编号：HT-2024-002",
        "甲方（采购方）：星辰科技有限公司",
        "乙方（供应商）：恒信机电设备有限公司",
        "合同总金额：人民币壹佰贰拾万元整（¥1,200,000）",
        "第一条 采购内容",
        "甲方向乙方采购数控加工设备 5 台，用于生产线改造。",
        "第二条 交付条款",
        "乙方应于 2024 年 5 月 31 日前将全部设备运送至甲方指定地点并完成安装调试。",
        "第三条 验收条款",
        "设备到货后 15 个工作日内，甲方按照国家标准组织验收；验收不合格的，乙方应在 10 日内完成更换。",
        "第四条 付款方式",
        "设备验收合格后，甲方于 90 个工作日内支付合同款项。",
        "第五条 违约责任",
        "乙方逾期交付的，每逾期一日按合同总额的 0.5% 支付违约金；甲方逾期付款的，按同等标准支付违约金。",
        "第六条 保密条款",
        "双方对在履行本合同过程中知悉的对方商业秘密承担保密义务，保密期限为本合同终止后三年。",
        "第七条 知识产权条款",
        "本合同项下设备涉及的既有知识产权归原权利人所有，双方互不侵犯。",
        "第八条 数据条款",
        "设备运行产生的数据归甲方所有，乙方不得擅自收集、使用或对外提供。",
        "第九条 争议解决",
        "因本合同产生争议的，双方协商解决；协商不成的，提交甲方所在地人民法院管辖。",
        "第十条 生效与期限",
        "本合同自 2024 年 3 月 1 日起生效，有效期至 2026 年 2 月 28 日。",
    ],
}

OUTSOURCING_SCAN = {
    "file": "outsourcing_scan.pdf",
    "kind": "scanned_pdf",
    "pages": [
        [
            "服务外包框架合同",
            "合同编号：HT-2024-003",
            "甲方（委托方）：星辰科技有限公司",
            "乙方（服务方）：博远信息技术有限公司",
            "合同总金额：人民币伍拾万元整（¥500,000）",
            "第一条 服务内容",
            "乙方向甲方提供信息系统运维与技术支持服务。",
            "第二条 交付条款",
            "乙方按月提交服务报告，并于每月 5 日前完成上月服务交付。",
            "第三条 付款方式",
            "甲方于每月 10 日前支付上月服务费用，付款周期为 30 日。",
        ],
        [
            "第四条 保密条款",
            "乙方对甲方业务数据及商业秘密承担保密义务，保密期限为合同终止后五年。",
            "第五条 验收条款",
            "甲方按月对服务质量进行验收，验收标准依照附件《服务水平协议》执行。",
            "第六条 违约责任",
            "乙方未按期提供服务的，按当月服务费的 20% 支付违约金。",
            "第七条 数据条款",
            "乙方在服务过程中接触的甲方数据，仅限用于本合同约定目的，不得留存或另作他用。",
            "第八条 争议解决",
            "因本合同产生的争议，双方协商不成的，提交乙方所在地仲裁委员会仲裁。",
            "第九条 续约条款",
            "本合同期满后，如双方均未提出书面异议，本合同自动续约一年。",
            "第十条 生效与期限",
            "本合同自 2024 年 4 月 1 日起生效，有效期至 2025 年 3 月 31 日。",
        ],
    ],
    "write_labels": True,
}

LABOR_SCAN = {
    "file": "labor_scan.pdf",
    "kind": "scanned_pdf",
    # 该扫描件刻意不提供 OCR 标注，用于演示「图片无法识别」阻塞
    "pages": [
        [
            "劳动合同书",
            "合同编号：HT-2024-006",
            "甲方（用人单位）：星辰科技有限公司",
            "乙方（劳动者）：张某某",
        ],
    ],
    "write_labels": False,
}

SIMPLE_SERVICE = {
    "file": "simple_service_contract.docx",
    "kind": "docx",
    "paragraphs": [
        "信息技术咨询服务合同",
        "合同编号：HT-2024-007",
        "甲方（委托方）：星辰科技有限公司",
        "乙方（服务方）：明远管理咨询有限公司",
        "合同总金额：人民币贰拾万元整（¥200,000）",
        "第一条 服务内容",
        "乙方向甲方提供信息化建设咨询服务。",
        "第二条 交付条款",
        "乙方于 2024 年 8 月 31 日前提交咨询报告。",
        "第三条 验收条款",
        "甲方在收到咨询报告后 10 个工作日内完成验收。",
        "第四条 付款方式",
        "合同签订后支付合同总额 20% 的预付款，验收合格后 30 日内支付余款。",
        "第五条 违约责任",
        "任何一方违约的，应向对方支付合同总额 10% 的违约金。",
        "第六条 保密条款",
        "双方对合同履行过程中知悉的商业秘密承担保密义务，保密期限为三年。",
        "第七条 数据条款",
        "乙方处理甲方数据应遵守相关法律法规，不得超范围使用。",
        "第八条 知识产权条款",
        "咨询成果的知识产权归甲方所有。",
        "第九条 争议解决",
        "因本合同产生的争议，提交甲方所在地人民法院管辖。",
        "第十条 生效与期限",
        "本合同自 2024 年 6 月 1 日起生效，有效期至 2025 年 5 月 31 日。",
    ],
}

BLANK_TEMPLATE = {
    "file": "blank_template.docx",
    "kind": "blank_docx",
    "paragraphs": [],
}

ALL_CONTRACTS = (
    SOFTWARE_DEV,
    EQUIPMENT_PURCHASE,
    OUTSOURCING_SCAN,
    SIMPLE_SERVICE,
    BLANK_TEMPLATE,
    LABOR_SCAN,
)


# ---------------------------------------------------------------------------
# 生成实现
# ---------------------------------------------------------------------------
def _resolve_font(size: int = FONT_SIZE) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    raise RuntimeError("未找到可用的中文字体，无法生成扫描件示例")


def _write_docx(path: Path, paragraphs: list[str]) -> None:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Pt

    document = Document()
    style = document.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(11)
    # python-docx 需显式设置东亚字体，否则中文字形回退
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    for text in paragraphs:
        document.add_paragraph(text)
    document.save(str(path))


def _write_text_pdf(path: Path, paragraphs: list[str]) -> None:
    """生成带文本层的 PDF（可被 pymupdf 直接提取）。"""
    doc = pymupdf.open()
    font_size = 12
    line_height = 22
    top = 72
    left = 64
    max_y = 780

    page = doc.new_page()
    y = top
    for text in paragraphs:
        if y > max_y:
            page = doc.new_page()
            y = top
        page.insert_text((left, y), text, fontsize=font_size, fontname="china-s")
        y += line_height
    doc.save(str(path))
    doc.close()


def _render_lines(lines: list[str], font: ImageFont.FreeTypeFont) -> Image.Image:
    image = Image.new("RGB", PAGE_SIZE, "white")
    draw = ImageDraw.Draw(image)
    y = MARGIN_Y
    for text in lines:
        draw.text((MARGIN_X, y), text, font=font, fill=(20, 20, 20))
        y += LINE_HEIGHT
    return image


def _write_scanned_pdf(path: Path, pages: list[list[str]], write_labels: bool) -> None:
    """生成无文本层的扫描件 PDF（图像渲染，逼真模拟纸质扫描）。

    无文本层是 OCR 路径的前提：解析时 pymupdf 提取不到文本，才会转向 OCR。
    """
    font = _resolve_font()
    images = [_render_lines(lines, font) for lines in pages]

    buffer = io.BytesIO()
    images[0].save(
        buffer,
        format="PDF",
        resolution=150.0,
        save_all=True,
        append_images=images[1:],
    )
    pdf_bytes = buffer.getvalue()

    # 断言产物确实没有文本层，避免示例失真导致 OCR 路径不可达
    probe = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    for index, page in enumerate(probe, start=1):
        if page.get_text().strip():
            raise AssertionError(f"{path.name} 第{index}页意外包含文本层，扫描件示例生成失败")
    probe.close()

    path.write_bytes(pdf_bytes)

    if not write_labels:
        return

    # 写出 OCR 标注（模拟 OCR 引擎的识别结果）
    label_dir = config.OCR_LABEL_DIR
    label_dir.mkdir(parents=True, exist_ok=True)
    slug = safe_slug(path.stem)
    for number, lines in enumerate(pages, start=1):
        (label_dir / f"{slug}.page{number}.txt").write_text("\n".join(lines), encoding="utf-8")


def generate() -> list[tuple[str, str]]:
    """生成全部示例文件，返回 (文件名, 说明) 列表。"""
    config.CONTRACT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[tuple[str, str]] = []

    for item in ALL_CONTRACTS:
        path = config.CONTRACT_DIR / item["file"]
        kind = item["kind"]
        if kind == "docx":
            _write_docx(path, item["paragraphs"])
        elif kind == "blank_docx":
            _write_docx(path, item["paragraphs"])
        elif kind == "text_pdf":
            _write_text_pdf(path, item["paragraphs"])
        elif kind == "scanned_pdf":
            _write_scanned_pdf(path, item["pages"], bool(item.get("write_labels")))
        else:  # pragma: no cover - 防御性分支
            raise ValueError(f"未知的示例类型：{kind}")
        written.append((path.name, kind))

    return written


def main() -> None:
    written = generate()
    print("示例合同生成完成：")
    for name, kind in written:
        print(f"  - {name:<32} [{kind}]")

    labels = sorted(config.OCR_LABEL_DIR.glob("*.txt")) if config.OCR_LABEL_DIR.is_dir() else []
    print(f"OCR 标注文件：{len(labels)} 个")
    for label in labels:
        print(f"  - {label.name}")


if __name__ == "__main__":
    main()
