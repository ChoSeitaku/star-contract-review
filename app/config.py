"""全局配置：目录布局、运行参数、系统配置项读写。

系统配置（§1.3.2 系统管理员维护审批接入配置）持久化在 system_configs 表，
此处提供默认值兜底。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# 目录布局（§1.3.8 附件模块：附件下载、附件存储、附件元数据保存）
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "star_contract.db"
SCHEMA_PATH = BASE_DIR / "scripts" / "init_db.sql"

RUNTIME_LOG_DIR = BASE_DIR / "runtime_logs"     # 日志文件 runtime_logs/{task_id}/task.log
WORKSPACE_DIR = BASE_DIR / "workspace"          # 附件与临时文件 workspace/{task_id}/
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

EXAMPLES_DIR = BASE_DIR / "examples"
CONTRACT_DIR = EXAMPLES_DIR / "contracts"                  # 示例合同文件
OCR_LABEL_DIR = CONTRACT_DIR / "ocr_labels"                # 扫描件 OCR 标注（模拟识别结果）

# 每次启动时建立的基础目录
MANAGED_DIRS = (RUNTIME_LOG_DIR, WORKSPACE_DIR)


def task_workspace_dir(task_id: int) -> Path:
    """单个任务的附件存储目录。"""
    return WORKSPACE_DIR / str(task_id)


def task_log_dir(task_id: int) -> Path:
    """单个任务的日志文件目录。"""
    return RUNTIME_LOG_DIR / str(task_id)


# ---------------------------------------------------------------------------
# 系统配置默认值（value, description）
# ---------------------------------------------------------------------------
DEFAULT_CONFIGS: dict[str, tuple[str, str]] = {
    "approval_system_name": (
        "模拟审批系统",
        "当前接入的审批系统名称（§1.3.2 系统管理员维护审批接入配置）",
    ),
    "adapter_fail_enabled": (
        "false",
        "模拟审批系统「拉取/下载」接口调用失败开关：true 时待办拉取、详情查询、附件下载均抛错，用于演示接口调用失败阻塞",
    ),
    "adapter_fail_write_enabled": (
        "false",
        "模拟审批系统「评论回写」接口调用失败开关：true 时评论回写抛错，用于演示回写失败与回写重试",
    ),
    "ocr_engine": (
        "simulated",
        "OCR 引擎：simulated（模拟识别，读取标注文件）/ paddleocr（需另行安装依赖，见 app/engine/ocr.py）",
    ),
    "max_attachment_mb": (
        "20",
        "单个合同附件允许的最大体积（MB），超出则下载判定失败",
    ),
    "comment_prefix": (
        "【合同自动审查意见】",
        "回写审批评论区的意见文本前缀标记",
    ),
    "retention_days": (
        "30",
        "任务附件与日志目录的保留天数，超出后启动时清理",
    ),
}


def get_config(key: str, default: str = "") -> str:
    from . import db  # 延迟导入，避免循环依赖

    fallback = DEFAULT_CONFIGS.get(key)
    default_value = fallback[0] if fallback else default
    try:
        row = db.query_one(
            "SELECT config_value FROM system_configs WHERE config_key = ?", (key,)
        )
    except sqlite3.Error:
        # 建库完成前（例如引擎层做独立自检）读取配置，回退到默认值
        return default_value
    if row is None:
        return default_value
    return row["config_value"]


def get_int_config(key: str, default: int = 0) -> int:
    try:
        return int(get_config(key, str(default)))
    except (TypeError, ValueError):
        return default


def get_bool_config(key: str, default: bool = False) -> bool:
    value = get_config(key, "true" if default else "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def set_config(key: str, value: str) -> None:
    from . import db
    from .utils import now_str

    description = DEFAULT_CONFIGS.get(key, ("", ""))[1]
    existing = db.query_one("SELECT config_key FROM system_configs WHERE config_key = ?", (key,))
    if existing is None:
        db.insert(
            "system_configs",
            {
                "config_key": key,
                "config_value": value,
                "description": description,
                "updated_at": now_str(),
            },
        )
    else:
        db.update(
            "system_configs",
            {"config_value": value, "updated_at": now_str()},
            "config_key = ?",
            (key,),
        )


def ensure_default_configs() -> None:
    """启动时补齐缺失的配置项，不覆盖已有值。"""
    from . import db
    from .utils import now_str

    for key, (value, description) in DEFAULT_CONFIGS.items():
        if db.query_one("SELECT config_key FROM system_configs WHERE config_key = ?", (key,)):
            continue
        db.insert(
            "system_configs",
            {
                "config_key": key,
                "config_value": value,
                "description": description,
                "updated_at": now_str(),
            },
        )
