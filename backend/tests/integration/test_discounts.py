"""Integration tests for discount validation, redemption, and admin CRUD."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_firebase_verifier
from app.enums import DiscountType, UserRole
from app.main import app
from app.models import DiscountCode, DiscountRedemption, User, Venue

DHK = ZoneInfo("Asia/Dhaka")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_venue(db: AsyncSession) -> Venue:
    venue = Venue(name="Discount Venue")
    db.add(venue)
    await db.flush()
    return venue


def _next_weekday(target_weekday: int = 5) -> date:
    today = datetime.now(UTC).date()
    delta = (target_weekday - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def _slot_iso(day: date, hour: int) -> str:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=DHK).astimezone(UTC).isoformat()


async def _login_user(api_client: AsyncClient, *, phone: str, fb_uid: str) -> str:
    def fake_verifier(_token: str) -> dict[str, Any]:
        return {"uid": fb_uid, "phone_number": phone}

    app.dependency_overrides[get_firebase_verifier] = lambda: fake_verifier
    try:
        resp = await api_client.post("/v1/auth/firebase", json={"id_token": "x" * 40})
        assert resp.status_code == 200, resp.text
        return resp.json()["access_token"]
    finally:
        app.dependency_overrides.pop(get_firebase_verifier, None)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_admin(db: AsyncSession, phone: str) -> User:
    admin = User(phone=phone, role=UserRole.ADMIN, manually_created=True)
    db.add(admin)
    await db.commit()
    return admin


async def _seed_code(
    db: AsyncSession,
    *,
    code: str = "WEEKEND10",
    type_: DiscountType = DiscountType.PERCENT,
    value: int = 10,
    min_amount: int = 0,
    max_discount: int | None = None,
    total_limit: int | None = None,
    per_user_limit: int = 1,
    valid_from_offset: timedelta = timedelta(days=-1),
    valid_until_offset: timedelta = timedelta(days=30),
    applies_to: dict[str, Any] | None = None,
    is_active: bool = True,
) -> DiscountCode:
    now = datetime.now(UTC)
    discount = DiscountCode(
        code=code,
        type=type_,
        value=value,
        min_amount_bdt=min_amount,
        max_discount_bdt=max_discount,
        usage_limit_total=total_limit,
        usage_limit_per_user=per_user_limit,
        valid_from=now + valid_from_offset,
        valid_until=now + valid_until_offset,
        is_active=is_active,
        applies_to=applies_to,
    )
    db.add(discount)
    await db.flush()
    return discount


# ---------------------------------------------------------------------------
# /v1/discount-codes/validate
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_validate_returns_amount_off(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_code(db_session, code="OFF20", type_=DiscountType.PERCENT, value=20)
    await db_session.commit()

    access = await _login_user(api_client, phone="+8801715000001", fb_uid="fb_v1")
    resp = await api_client.post(
        "/v1/discount-codes/validate",
        headers=_auth(access),
        json={"code": "OFF20", "subtotal_bdt": 2000, "slot_dates": []},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["amount_off_bdt"] == 400
    assert data["final_total_bdt"] == 1600


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_validate_404_when_unknown(api_client: AsyncClient, db_session: AsyncSession) -> None:
    access = await _login_user(api_client, phone="+8801715000002", fb_uid="fb_v2")
    resp = await api_client.post(
        "/v1/discount-codes/validate",
        headers=_auth(access),
        json={"code": "NOPE", "subtotal_bdt": 1000, "slot_dates": []},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "discount_not_found"


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_validate_rejects_inactive(api_client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed_code(db_session, code="OFFOFF", is_active=False)
    await db_session.commit()
    access = await _login_user(api_client, phone="+8801715000003", fb_uid="fb_v3")
    resp = await api_client.post(
        "/v1/discount-codes/validate",
        headers=_auth(access),
        json={"code": "OFFOFF", "subtotal_bdt": 2000, "slot_dates": []},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "discount_inactive"


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_validate_rejects_expired_window(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_code(
        db_session,
        code="OLD",
        valid_from_offset=timedelta(days=-30),
        valid_until_offset=timedelta(days=-1),
    )
    await db_session.commit()
    access = await _login_user(api_client, phone="+8801715000004", fb_uid="fb_v4")
    resp = await api_client.post(
        "/v1/discount-codes/validate",
        headers=_auth(access),
        json={"code": "OLD", "subtotal_bdt": 2000, "slot_dates": []},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "discount_out_of_window"


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_validate_rejects_below_min_amount(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_code(db_session, code="MIN500", min_amount=500)
    await db_session.commit()
    access = await _login_user(api_client, phone="+8801715000005", fb_uid="fb_v5")
    resp = await api_client.post(
        "/v1/discount-codes/validate",
        headers=_auth(access),
        json={"code": "MIN500", "subtotal_bdt": 200, "slot_dates": []},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "discount_below_min_amount"


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_validate_applies_to_weekend_only(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_code(db_session, code="WEEKENDONLY", applies_to={"weekend": True})
    await db_session.commit()

    access = await _login_user(api_client, phone="+8801715000006", fb_uid="fb_v6")

    # Saturday (weekday 5) is allowed.
    sat = _next_weekday(5).isoformat()
    ok = await api_client.post(
        "/v1/discount-codes/validate",
        headers=_auth(access),
        json={"code": "WEEKENDONLY", "subtotal_bdt": 1000, "slot_dates": [sat]},
    )
    assert ok.status_code == 200

    # Wednesday (weekday 2) is rejected.
    wed = _next_weekday(2).isoformat()
    bad = await api_client.post(
        "/v1/discount-codes/validate",
        headers=_auth(access),
        json={"code": "WEEKENDONLY", "subtotal_bdt": 1000, "slot_dates": [wed]},
    )
    assert bad.status_code == 400
    assert bad.json()["detail"] == "discount_applies_to_mismatch"


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_validate_requires_auth(api_client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed_code(db_session, code="ANY")
    await db_session.commit()
    resp = await api_client.post(
        "/v1/discount-codes/validate",
        json={"code": "ANY", "subtotal_bdt": 1000, "slot_dates": []},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Hold flow with discount
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_hold_with_valid_code_creates_redemption(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await _seed_code(db_session, code="HOLD20", type_=DiscountType.PERCENT, value=20)
    await db_session.commit()

    access = await _login_user(api_client, phone="+8801715100001", fb_uid="fb_h1")
    target = _next_weekday()
    resp = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "discount_code": "HOLD20",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["subtotal_bdt"] == 1000
    assert body["discount_amount_bdt"] == 200
    assert body["total_bdt"] == 800
    assert body["discount_code"] == "HOLD20"

    # Redemption row exists.
    rows = (await db_session.execute(select(DiscountRedemption))).scalars().all()
    assert len(rows) == 1
    assert rows[0].voided is False


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_hold_rejects_invalid_code(api_client: AsyncClient, db_session: AsyncSession) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()
    access = await _login_user(api_client, phone="+8801715100002", fb_uid="fb_h2")
    target = _next_weekday()
    resp = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "discount_code": "DOESNOTEXIST",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "discount_not_found"


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_cancel_hold_voids_redemption(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await _seed_code(db_session, code="CAN10", type_=DiscountType.PERCENT, value=10)
    await db_session.commit()

    access = await _login_user(api_client, phone="+8801715100003", fb_uid="fb_h3")
    target = _next_weekday()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "discount_code": "CAN10",
        },
    )
    booking_id = hold.json()["booking_id"]

    cancel = await api_client.post(f"/v1/bookings/{booking_id}/cancel-hold", headers=_auth(access))
    assert cancel.status_code == 200

    rows = (await db_session.execute(select(DiscountRedemption))).scalars().all()
    assert len(rows) == 1
    assert rows[0].voided is True

    # User can reuse the code on a new hold.
    redo = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 20)}],
            "discount_code": "CAN10",
        },
    )
    assert redo.status_code == 201


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_per_user_limit_blocks_second_active_use(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await _seed_code(db_session, code="ONCE", per_user_limit=1)
    await db_session.commit()

    access = await _login_user(api_client, phone="+8801715100004", fb_uid="fb_h4")
    target = _next_weekday()
    first = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "discount_code": "ONCE",
        },
    )
    assert first.status_code == 201

    second = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 20)}],
            "discount_code": "ONCE",
        },
    )
    assert second.status_code == 400
    assert second.json()["detail"] == "discount_per_user_limit_reached"


# ---------------------------------------------------------------------------
# Admin CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_admin_create_list_get_patch_delete(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_admin(db_session, phone="+8801715200001")

    admin_access = await _login_user(api_client, phone="+8801715200001", fb_uid="fb_admin1")

    now = datetime.now(UTC)
    create_payload = {
        "code": "ADMINCODE",
        "type": "percent",
        "value": 15,
        "min_amount_bdt": 0,
        "valid_from": now.isoformat(),
        "valid_until": (now + timedelta(days=14)).isoformat(),
        "is_active": True,
        "usage_limit_per_user": 1,
    }
    created = await api_client.post(
        "/v1/admin/discount-codes",
        headers=_auth(admin_access),
        json=create_payload,
    )
    assert created.status_code == 201, created.text
    code_id = created.json()["id"]

    # Duplicate -> 409
    dup = await api_client.post(
        "/v1/admin/discount-codes",
        headers=_auth(admin_access),
        json=create_payload,
    )
    assert dup.status_code == 409

    # List
    listing = await api_client.get("/v1/admin/discount-codes", headers=_auth(admin_access))
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    # Patch -> deactivate
    patched = await api_client.patch(
        f"/v1/admin/discount-codes/{code_id}",
        headers=_auth(admin_access),
        json={"is_active": False, "value": 25},
    )
    assert patched.status_code == 200
    assert patched.json()["is_active"] is False
    assert patched.json()["value"] == 25

    # Patch invalid percent
    bad = await api_client.patch(
        f"/v1/admin/discount-codes/{code_id}",
        headers=_auth(admin_access),
        json={"value": 150},
    )
    assert bad.status_code == 400

    # Delete
    deleted = await api_client.delete(
        f"/v1/admin/discount-codes/{code_id}", headers=_auth(admin_access)
    )
    assert deleted.status_code == 204

    # Read after delete -> 404
    missing = await api_client.get(
        f"/v1/admin/discount-codes/{code_id}", headers=_auth(admin_access)
    )
    assert missing.status_code == 404


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_admin_endpoints_require_admin_role(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    customer_access = await _login_user(api_client, phone="+8801715200002", fb_uid="fb_cust")

    resp = await api_client.get("/v1/admin/discount-codes", headers=_auth(customer_access))
    assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_admin_cannot_delete_redeemed_code(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await _seed_admin(db_session, phone="+8801715200003")
    discount = await _seed_code(db_session, code="REDEEMED")
    await db_session.commit()

    # Customer redeems it.
    cust_access = await _login_user(api_client, phone="+8801715200004", fb_uid="fb_cust2")
    target = _next_weekday()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(cust_access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "discount_code": "REDEEMED",
        },
    )
    assert hold.status_code == 201

    admin_access = await _login_user(api_client, phone="+8801715200003", fb_uid="fb_admin2")
    resp = await api_client.delete(
        f"/v1/admin/discount-codes/{discount.id}", headers=_auth(admin_access)
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "discount_has_redemptions"
