"""Integration tests for the auth router.

The Firebase verifier is overridden via dependency override so we never call
real Firebase. The override returns a canned decoded-token dict.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_firebase_verifier
from app.enums import UserRole
from app.main import app
from app.models import User


def _fake_verifier(decoded: dict[str, Any]) -> Any:
    def _verify(_id_token: str) -> dict[str, Any]:
        return decoded

    return _verify


@pytest.fixture
def override_firebase() -> Any:
    """Helper: install a fake verifier returning a configurable payload."""

    def install(decoded: dict[str, Any]) -> None:
        app.dependency_overrides[get_firebase_verifier] = lambda: _fake_verifier(decoded)

    yield install
    app.dependency_overrides.pop(get_firebase_verifier, None)


# ---------------------------------------------------------------------------
# Firebase exchange
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_firebase_exchange_creates_user_and_returns_pair(
    api_client: AsyncClient,
    db_session: AsyncSession,
    override_firebase: Any,
) -> None:
    override_firebase({"uid": "fb_uid_alpha", "phone_number": "+8801711000001"})

    resp = await api_client.post(
        "/v1/auth/firebase",
        json={"id_token": "x" * 40},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["expires_in"] > 0

    user = (
        await db_session.execute(select(User).where(User.phone == "+8801711000001"))
    ).scalar_one()
    assert user.firebase_uid == "fb_uid_alpha"
    assert user.role == UserRole.CUSTOMER
    assert user.last_login_at is not None


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_firebase_exchange_existing_user_login(
    api_client: AsyncClient,
    db_session: AsyncSession,
    override_firebase: Any,
) -> None:
    db_session.add(User(phone="+8801711000002", role=UserRole.ADMIN, manually_created=True))
    await db_session.commit()

    override_firebase({"uid": "fb_uid_beta", "phone_number": "+8801711000002"})
    resp = await api_client.post("/v1/auth/firebase", json={"id_token": "x" * 40})
    assert resp.status_code == 200

    refreshed = (
        await db_session.execute(select(User).where(User.phone == "+8801711000002"))
    ).scalar_one()
    assert refreshed.firebase_uid == "fb_uid_beta"
    assert refreshed.role == UserRole.ADMIN  # admin role preserved
    assert refreshed.manually_created is False  # claimed via Firebase


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_firebase_exchange_rejects_non_bd_phone(
    api_client: AsyncClient,
    override_firebase: Any,
) -> None:
    override_firebase({"uid": "fb_uid_gamma", "phone_number": "+14155551234"})
    resp = await api_client.post("/v1/auth/firebase", json={"id_token": "x" * 40})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "phone_not_supported"


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_firebase_exchange_rejects_token_without_phone(
    api_client: AsyncClient,
    override_firebase: Any,
) -> None:
    override_firebase({"uid": "fb_uid_delta"})  # no phone_number
    resp = await api_client.post("/v1/auth/firebase", json={"id_token": "x" * 40})
    assert resp.status_code == 400
    assert "phone" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Refresh rotation
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_refresh_rotation_issues_new_pair_and_invalidates_old(
    api_client: AsyncClient,
    override_firebase: Any,
) -> None:
    override_firebase({"uid": "fb_rot", "phone_number": "+8801712000001"})
    first = (await api_client.post("/v1/auth/firebase", json={"id_token": "x" * 40})).json()

    second = await api_client.post(
        "/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert second.status_code == 200
    pair = second.json()
    assert pair["refresh_token"] != first["refresh_token"]

    # Old refresh must now be invalid (single-use rotation).
    replay = await api_client.post(
        "/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert replay.status_code == 401


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_refresh_unknown_token_401(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/v1/auth/refresh", json={"refresh_token": "definitely-not-a-real-token-xxxxxxxxxxx"}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_logout_revokes_refresh_token(
    api_client: AsyncClient,
    override_firebase: Any,
) -> None:
    override_firebase({"uid": "fb_logout", "phone_number": "+8801713000001"})
    pair = (await api_client.post("/v1/auth/firebase", json={"id_token": "x" * 40})).json()

    out = await api_client.post("/v1/auth/logout", json={"refresh_token": pair["refresh_token"]})
    assert out.status_code == 204

    # Refresh now fails — token revoked.
    replay = await api_client.post(
        "/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]}
    )
    assert replay.status_code == 401


# ---------------------------------------------------------------------------
# /v1/me
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_me_returns_authenticated_user(
    api_client: AsyncClient,
    override_firebase: Any,
) -> None:
    override_firebase({"uid": "fb_me", "phone_number": "+8801714000001"})
    pair = (await api_client.post("/v1/auth/firebase", json={"id_token": "x" * 40})).json()

    resp = await api_client.get(
        "/v1/me", headers={"Authorization": f"Bearer {pair['access_token']}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["phone"] == "+8801714000001"
    assert body["role"] == "customer"


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_me_without_token_401(api_client: AsyncClient) -> None:
    resp = await api_client.get("/v1/me")
    assert resp.status_code == 401


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_me_with_garbage_token_401(api_client: AsyncClient) -> None:
    resp = await api_client.get("/v1/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_me_patch_updates_profile(
    api_client: AsyncClient,
    db_session: AsyncSession,
    override_firebase: Any,
) -> None:
    override_firebase({"uid": "fb_patch", "phone_number": "+8801715000001"})
    pair = (await api_client.post("/v1/auth/firebase", json={"id_token": "x" * 40})).json()

    resp = await api_client.patch(
        "/v1/me",
        headers={"Authorization": f"Bearer {pair['access_token']}"},
        json={"name": "Test User", "email": "test@example.com"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Test User"
    assert body["email"] == "test@example.com"


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_me_delete_marks_deletion_requested(
    api_client: AsyncClient,
    db_session: AsyncSession,
    override_firebase: Any,
) -> None:
    override_firebase({"uid": "fb_del", "phone_number": "+8801716000001"})
    pair = (await api_client.post("/v1/auth/firebase", json={"id_token": "x" * 40})).json()

    resp = await api_client.delete(
        "/v1/me", headers={"Authorization": f"Bearer {pair['access_token']}"}
    )
    assert resp.status_code == 202

    user = (
        await db_session.execute(select(User).where(User.phone == "+8801716000001"))
    ).scalar_one()
    assert user.deletion_requested_at is not None
