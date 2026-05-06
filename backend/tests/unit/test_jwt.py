"""Unit tests for JWT mint/decode (no Redis, no DB)."""

from __future__ import annotations

import time

import pytest
from jose import jwt as jose_jwt

from app.config import get_settings
from app.enums import UserRole
from app.security.jwt import (
    AccessClaims,
    TokenError,
    decode_access_token,
    mint_access_token,
)


@pytest.mark.unit
def test_mint_and_decode_round_trip() -> None:
    token, expires_in = mint_access_token(user_id=42, role=UserRole.ADMIN)
    claims = decode_access_token(token)
    assert isinstance(claims, AccessClaims)
    assert claims.sub == "42"
    assert claims.role == UserRole.ADMIN
    assert claims.exp - claims.iat == expires_in


@pytest.mark.unit
def test_decode_expired_token_raises() -> None:
    settings = get_settings()
    payload = {
        "sub": "1",
        "role": UserRole.CUSTOMER.value,
        "iat": int(time.time()) - 3600,
        "exp": int(time.time()) - 60,
    }
    expired = jose_jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(TokenError):
        decode_access_token(expired)


@pytest.mark.unit
def test_decode_wrong_signature_raises() -> None:
    settings = get_settings()
    payload = {
        "sub": "1",
        "role": UserRole.CUSTOMER.value,
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
    }
    bad = jose_jwt.encode(payload, "wrong-secret", algorithm=settings.jwt_algorithm)
    with pytest.raises(TokenError):
        decode_access_token(bad)


@pytest.mark.unit
def test_decode_missing_role_raises() -> None:
    settings = get_settings()
    payload = {
        "sub": "1",
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
    }
    bad = jose_jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(TokenError):
        decode_access_token(bad)


@pytest.mark.unit
def test_role_carried_through() -> None:
    for role in (UserRole.CUSTOMER, UserRole.STAFF, UserRole.ADMIN):
        token, _ = mint_access_token(user_id=1, role=role)
        assert decode_access_token(token).role == role
