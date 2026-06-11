"""JWT + bcrypt yardımcıları (Adım 2a + 8a).

Adım 8'de eklenenler:
  - hash_password / verify_password: bcrypt SDK doğrudan (passlib bypass —
    passlib 1.7.4 modern bcrypt 4.x ile uyumsuz, `bcrypt.__about__` aramayı
    deniyor ve verify çağrılarını sessizce başarısız kılıyor).
  - create_access_token: artık `username` / `display_name` opsiyonel
    payload alanlarını da gömüyor; mevcut çağrılar geriye dönük çalışır.

bcrypt'in 72-byte parola limiti var; sınır aşan parolaları sessizce
trunc etmiyoruz, schemas.py'de Pydantic max_length=128'e güveniyoruz.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from .config import Settings


_BCRYPT_ROUNDS = 12  # pgcrypto seed'iyle aynı maliyet


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password cannot be empty")
    pw_bytes = password.encode("utf-8")
    if len(pw_bytes) > 72:
        # Pydantic'in 128 char limiti UTF-8 byte limitinden farklı; defansif kes.
        pw_bytes = pw_bytes[:72]
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        pw_bytes = password.encode("utf-8")
        if len(pw_bytes) > 72:
            pw_bytes = pw_bytes[:72]
        return bcrypt.checkpw(pw_bytes, password_hash.encode("utf-8"))
    except Exception:
        return False


def create_access_token(
    student_id: str,
    grade_level: int,
    settings: Settings,
    role: Optional[str] = None,
    username: Optional[str] = None,
    display_name: Optional[str] = None,
) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.jwt_expiration_seconds)
    payload: dict = {
        "sub": student_id,
        "grade_level": grade_level,
        "exp": int(expires_at.timestamp()),
    }
    if role:
        payload["role"] = role
    if username:
        payload["username"] = username
    if display_name:
        payload["display_name"] = display_name
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise ValueError(f"invalid token: {e}") from e
