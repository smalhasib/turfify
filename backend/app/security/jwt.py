"""JWT access tokens + Redis-backed refresh tokens.

Access tokens are short-lived (15 min default), HS256-signed, fully stateless.
Refresh tokens are random opaque UUIDs stored in Redis with the user_id and
configurable TTL (30 days default). Each refresh is single-use: presenting one
returns a new pair and atomically invalidates the old. This blocks replay
windows narrower than the access TTL.

Redis key shape:
    refresh:{token_uuid} -> JSON {"user_id": <int>, "issued_at": <iso8601>}
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from pydantic import BaseModel
from redis.asyncio import Redis

from app.config import get_settings
from app.enums import UserRole

REFRESH_KEY_PREFIX = "refresh:"


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth2 scheme name, not a secret
    expires_in: int  # seconds


class AccessClaims(BaseModel):
    sub: str  # user_id (string)
    role: UserRole
    iat: int
    exp: int


class TokenError(Exception):
    """Raised on invalid/expired/missing tokens."""


def _now() -> datetime:
    return datetime.now(UTC)


def mint_access_token(*, user_id: int, role: UserRole) -> tuple[str, int]:
    """Return (jwt_str, expires_in_seconds)."""
    settings = get_settings()
    issued_at = _now()
    expires_at = issued_at + timedelta(minutes=settings.jwt_access_ttl_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role.value,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token: str = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, settings.jwt_access_ttl_minutes * 60


def decode_access_token(token: str) -> AccessClaims:
    """Decode and validate an access token; raise TokenError on any failure."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise TokenError(f"invalid_token: {e}") from e

    try:
        return AccessClaims(
            sub=str(payload["sub"]),
            role=UserRole(payload["role"]),
            iat=int(payload["iat"]),
            exp=int(payload["exp"]),
        )
    except (KeyError, ValueError) as e:
        raise TokenError(f"malformed_claims: {e}") from e


async def issue_refresh_token(redis: Redis, *, user_id: int) -> str:
    """Generate a fresh refresh token and persist it in Redis."""
    settings = get_settings()
    token = secrets.token_urlsafe(48)
    payload = json.dumps(
        {"user_id": user_id, "issued_at": _now().isoformat()},
        separators=(",", ":"),
    )
    await redis.set(
        f"{REFRESH_KEY_PREFIX}{token}",
        payload,
        ex=settings.jwt_refresh_ttl_days * 86400,
    )
    return token


async def consume_refresh_token(redis: Redis, *, token: str) -> int:
    """Atomically pop a refresh token and return the bound user_id.

    Returns the user_id if valid; raises TokenError if missing/expired.
    Single-use: GETDEL means the same token cannot be reused.
    """
    raw = await redis.getdel(f"{REFRESH_KEY_PREFIX}{token}")
    if raw is None:
        raise TokenError("refresh_token_invalid_or_expired")

    try:
        data = json.loads(raw)
        return int(data["user_id"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        raise TokenError(f"refresh_token_malformed: {e}") from e


async def revoke_refresh_token(redis: Redis, *, token: str) -> None:
    """Best-effort revocation (idempotent): delete a refresh token."""
    await redis.delete(f"{REFRESH_KEY_PREFIX}{token}")


async def issue_token_pair(redis: Redis, *, user_id: int, role: UserRole) -> TokenPair:
    """Mint a new access+refresh pair."""
    access, expires_in = mint_access_token(user_id=user_id, role=role)
    refresh = await issue_refresh_token(redis, user_id=user_id)
    return TokenPair(access_token=access, refresh_token=refresh, expires_in=expires_in)
