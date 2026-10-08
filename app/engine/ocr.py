"""扫描件文字识别（OCR）引擎层（§1.3.1 审查能力：扫描件文字识别）。

设计为可插拔：`OCREngine` 定义统一接口，`get_ocr_engine()` 按系统配置
`ocr_engine` 选择实现。内置的 `SimulatedOCR` 读取示例扫描件随附的标注文件
（examples/contracts/ocr_labels/{slug}.pageN.txt）作为识别结果，使整条
「扫描件 → 识别 → 字段提取 → 规则审查」链路可以离线、确定性地跑通。

接入真实 OCR 引擎（PaddleOCR / EasyOCR / 云服务）只需新增子类：

    class PaddleOCREngine(OCREngine):
        name = "paddleocr"

        def __init__(self) -> None:
            from paddleocr import PaddleOCR
            self._model = PaddleOCR(use_angle_cls=True, lang="ch")

        def recognize(self, image: bytes, page_no: int, document_slug: str) -> str:
            import numpy as np
            from PIL import Image
            import io

            array = np.array(Image.open(io.BytesIO(image)).convert("RGB"))
            lines = self._model.ocr(array, cls=True)
            return "\\n".join(item[1][0] for item in (lines[0] or []))

并在 get_ocr_engine() 中按配置返回该类实例即可，其余模块无需改动。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .. import config
from ..utils import safe_slug


class OCREngine(ABC):
    """OCR 引擎接口：把一页扫描件图像识别为文本。"""

    name: str = "base"

    @abstractmethod
    def recognize(self, image: bytes, page_no: int, document_slug: str) -> str:
        """识别单页图像，返回文本；无法识别时返回空字符串。"""

    def describe(self) -> str:
        return self.name


class SimulatedOCR(OCREngine):
    """模拟 OCR：读取示例扫描件的标注文件作为识别结果。

    标注文件命名规则：`{safe_slug(文件名主干)}.page{页码}.txt`，
    缺失标注即视为识别失败，用于演示「图片无法识别」阻塞。
    """

    name = "simulated"

    def __init__(self, label_dir: Path | None = None) -> None:
        self._label_dir = label_dir or config.OCR_LABEL_DIR

    def label_path(self, document_slug: str, page_no: int) -> Path:
        return self._label_dir / f"{safe_slug(document_slug)}.page{page_no}.txt"

    def recognize(self, image: bytes, page_no: int, document_slug: str) -> str:
        path = self.label_path(document_slug, page_no)
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()


def get_ocr_engine() -> OCREngine:
    """按系统配置返回当前生效的 OCR 引擎。"""
    selected = config.get_config("ocr_engine", "simulated").strip().lower()
    if selected in {"simulated", ""}:
        return SimulatedOCR()
    if selected in {"paddleocr", "easyocr"}:
        # 真实引擎需要额外依赖，此处给出明确指引而不是静默降级
        raise RuntimeError(
            f"OCR 引擎 {selected} 需要自行安装依赖并实现适配器，"
            "请参考 app/engine/ocr.py 文件头的示例；"
            "如需使用内置模拟识别，请将系统配置 ocr_engine 设为 simulated。"
        )
    raise RuntimeError(f"未知的 OCR 引擎配置：{selected}")
