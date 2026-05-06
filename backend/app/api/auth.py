"""Authentication endpoints.

Flow:
1. Client signs in via Firebase Phone Auth (OTP) on the browser.
2. Client POSTs the Firebase ID token to /v1/auth/firebase.
3. Backend verifies the token, upserts the user row keyed by phone, and returns
   an app JWT pair (short-lived access + 30-day Redis-backed refresh).
4. Subsequent calls use Bearer access tokens. Refresh via /v1/auth/refresh.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.enums import UserRole
from app.logging_config import get_logger
from app.models import User
from app.redis_client import get_redis
from app.security.firebase import FirebaseAuthError, verify_id_token
from app.security.jwt import (
    TokenError,
    TokenPair,
    consume_refresh_token,
    decode_access_token,
    issue_token_pair,
    revoke_refresh_token,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]

# Bangladesh mobile: +880 followed by 1[3-9] and 8 more digits.
BD_PHONE_PATTERN = re.compile(r"^\+8801[3-9]\d{8}$")


# ---------------------------------------------------------------------------
# Request / response shapes
# ---------------------------------------------------------------------------


class FirebaseTokenIn(BaseModel):
    id_token: str = Field(..., min_length=20, description="Firebase ID token from client")


class RefreshIn(BaseModel):
    refresh_token: str = Field(..., min_length=20)


class LogoutIn(BaseModel):
    refresh_token: str = Field(..., min_length=20)


# ---------------------------------------------------------------------------
# Firebase verifier indirection
#
# Tests override this dependency to inject a fake verifier so we never call
# real Firebase from integration tests.
# ---------------------------------------------------------------------------


def get_firebase_verifier() -> Any:
    """Default: real Firebase Admin SDK verifier."""
    return verify_id_token


FirebaseVerifierDep = Annotated[Any, Depends(get_firebase_verifier)]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/firebase", response_model=TokenPair)
async def exchange_firebase_token(
    payload: FirebaseTokenIn,
    db: DbDep,
    redis: RedisDep,
    verifier: FirebaseVerifierDep,
) -> TokenPair:
    """Exchange a Firebase ID token for an app JWT pair."""
    try:
        decoded = verifier(payload.id_token)
    except FirebaseAuthError as e:
        logger.warning("auth.firebase.verify_failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"firebase_{e}") from e

    firebase_uid: str | None = decoded.get("uid") or decoded.get("user_id")
    phone: str | None = decoded.get("phone_number")
    if not firebase_uid or not phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="firebase_token_missing_uid_or_phone",
        )

    if not BD_PHONE_PATTERN.match(phone):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="phone_not_supported",
        )

    user = (await db.execute(select(User).where(User.phone == phone))).scalar_one_or_none()

    if user is None:
        user = User(
            firebase_uid=firebase_uid,
            phone=phone,
            role=UserRole.CUSTOMER,
        )
        db.add(user)
        await db.flush()
        logger.info("auth.user.created", user_id=user.id, phone=phone)
    else:
        if user.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user_deleted")
        if user.firebase_uid is None:
            user.firebase_uid = firebase_uid
            user.manually_created = False
            logger.info("auth.user.claimed", user_id=user.id, phone=phone)
        elif user.firebase_uid != firebase_uid:
            logger.warning(
                "auth.user.uid_changed",
                user_id=user.id,
                old=user.firebase_uid,
                new=firebase_uid,
            )
            user.firebase_uid = firebase_uid

    user.last_login_at = datetime.now(UTC)
    await db.commit()

    return await issue_token_pair(redis, user_id=user.id, role=user.role)


@router.post("/refresh", response_model=TokenPair)
async def refresh_tokens(
    payload: RefreshIn,
    db: DbDep,
    redis: RedisDep,
) -> TokenPair:
    """Rotate a refresh token (single-use). Returns a fresh pair."""
    try:
        user_id = await consume_refresh_token(redis, token=payload.refresh_token)
    except TokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user_not_found")

    return await issue_token_pair(redis, user_id=user.id, role=user.role)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: LogoutIn, redis: RedisDep) -> None:
    """Revoke a refresh token. Idempotent."""
    await revoke_refresh_token(redis, token=payload.refresh_token)


# ---------------------------------------------------------------------------
# Local helper used by /v1/me (kept here to share BD_PHONE_PATTERN logic)
# ---------------------------------------------------------------------------


def _ensure_valid_access_token(token: str) -> int:
    """Quick decode helper for cases that bypass the dependency injection.
    Returns the user_id; raises 401 otherwise.
    """
    try:
        claims = decode_access_token(token)
    except TokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e
    return int(claims.sub)
