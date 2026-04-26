from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import HTTPException, status
from pwdlib import PasswordHash


ALGORITHM = "HS256"
password_hash = PasswordHash.recommended()


class AuthError(ValueError):
    """Raised when a token cannot be validated."""


def resolve_secret_key() -> str:
    secret_key = os.getenv("SUBSETS_CHAT_SECRET_KEY")
    if secret_key:
        return secret_key

    environment = os.getenv("SUBSETS_CHAT_ENV", "dev").lower()
    if environment in {"dev", "test"}:
        return "dev-only-subsets-chat-secret-key"

    raise RuntimeError("SUBSETS_CHAT_SECRET_KEY is required outside dev/test mode")


def access_token_expire_minutes() -> int:
    raw_value = os.getenv("SUBSETS_CHAT_ACCESS_TOKEN_MINUTES", "60")
    try:
        minutes = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("SUBSETS_CHAT_ACCESS_TOKEN_MINUTES must be an integer") from exc
    if minutes <= 0:
        raise RuntimeError("SUBSETS_CHAT_ACCESS_TOKEN_MINUTES must be positive")
    return minutes


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, password_hash_value: str) -> bool:
    return password_hash.verify(password, password_hash_value)


def create_access_token(user_id: int, secret_key: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=access_token_expire_minutes())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "exp": expires_at,
        "typ": "access",
    }
    return jwt.encode(payload, secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str, secret_key: str) -> int:
    try:
        payload = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError as exc:
        raise AuthError("invalid token") from exc

    if payload.get("typ") != "access":
        raise AuthError("invalid token type")

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise AuthError("invalid token subject")
    try:
        return int(subject)
    except ValueError as exc:
        raise AuthError("invalid token subject") from exc


def unauthorized(detail: str = "Could not validate credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
