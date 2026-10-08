"""通用工具函数。"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from pathlib import Path

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def now_str() -> str:
    """当前本地时间字符串，统一用于所有 created_at / updated_at 字段。"""
    return _dt.datetime.now().strftime(TIME_FORMAT)


def truncate(text: str | None, limit: int = 500) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def safe_slug(text: str, fallback: str = "item", max_len: int = 60) -> str:
    """把任意名称转成安全的文件名片段（保留中文，用于 OCR 标注文件命名）。"""
    slug = re.sub(r"[^A-Za-z0-9._一-鿿-]+", "_", (text or "").strip())
    slug = slug.strip("._-")
    if not slug:
        return fallback
    return slug[:max_len]


def sha256_of(path: str | Path) -> str:
    """计算文件 sha256（§1.3.3 附件下载工具返回校验信息）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
