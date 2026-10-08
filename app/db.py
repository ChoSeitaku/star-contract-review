"""SQLite 数据访问层。

采用「每次操作独立连接」策略，避免后台 asyncio 任务与请求线程之间的
跨线程连接问题；写入通过全局锁串行化，配合 WAL 模式保证并发安全。
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Sequence

from . import config

_write_lock = threading.RLock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def query_all(sql: str, params: Sequence[Any] = ()) -> list[dict]:
    with get_conn() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def query_one(sql: str, params: Sequence[Any] = ()) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def query_scalar(sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
        if row is None or row[0] is None:
            return default
        return row[0]


def count(table: str, where: str = "", params: Sequence[Any] = ()) -> int:
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    return int(query_scalar(sql, params, 0) or 0)


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------
def execute(sql: str, params: Sequence[Any] = ()) -> int:
    """执行写入语句，返回 lastrowid（INSERT）或受影响行数（UPDATE/DELETE）。"""
    with _write_lock, get_conn() as conn:
        cursor = conn.execute(sql, params)
        if cursor.lastrowid:
            return cursor.lastrowid
        return cursor.rowcount


def execute_many(sql: str, seq: Iterable[Sequence[Any]]) -> None:
    with _write_lock, get_conn() as conn:
        conn.executemany(sql, seq)


def insert(table: str, data: dict[str, Any]) -> int:
    """按字典插入一行，返回新记录 id。"""
    columns = ", ".join(data.keys())
    placeholders = ", ".join("?" for _ in data)
    sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
    return execute(sql, tuple(data.values()))


def update(table: str, data: dict[str, Any], where: str, params: Sequence[Any] = ()) -> int:
    """按字典更新记录，返回受影响行数。"""
    if not data:
        return 0
    assignments = ", ".join(f"{key} = ?" for key in data)
    sql = f"UPDATE {table} SET {assignments} WHERE {where}"
    return execute(sql, tuple(data.values()) + tuple(params))


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------
def init_db() -> None:
    """执行 scripts/init_db.sql 建库建表（幂等）。"""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    for directory in config.MANAGED_DIRS:
        directory.mkdir(parents=True, exist_ok=True)

    schema_sql = config.SCHEMA_PATH.read_text(encoding="utf-8")
    with _write_lock, get_conn() as conn:
        conn.executescript(schema_sql)
