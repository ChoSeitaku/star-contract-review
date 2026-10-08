"""密码哈希与登录令牌（仅依赖标准库，避免 Windows 上 bcrypt 二进制依赖问题）。"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 120_000
_SALT_BYTES = 16

TOKEN_TTL_SECONDS = 24 * 3600


def hash_password(password: str) -> str:
    """返回 `pbkdf2_sha256$迭代次数$盐$哈希` 格式的密码摘要。"""
    salt = secrets.token_hex(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _ITERATIONS
    ).hex()
    return f"{_ALGORITHM}${_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    """校验密码，使用常量时间比较避免时序侧信道。"""
    if not stored_hash:
        return False
    try:
        algorithm, iterations, salt, digest = stored_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != _ALGORITHM:
        return False
    try:
        rounds = int(iterations)
    except ValueError:
        return False
    computed = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), rounds
    ).hex()
    return hmac.compare_digest(computed, digest)


def new_token() -> str:
    return secrets.token_urlsafe(32)
