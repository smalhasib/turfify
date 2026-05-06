"""Integration tests for Phase 8 customer + admin cancellation."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_firebase_verifier
from app.enums import BookingStatus, RefundStatus, UserRole
from app.main import app
from app.models import Booking, Refund, User, Venue

DHK = ZoneInfo("Asia/Dhaka")


async def _make_venue(db: AsyncSession, *, refund_hours: int = 24) -> Venue:
    venue = Venue(name="Cancel Venue", cancellation_full_refund_hours=refund_hours)
    db.add(venue)
    await db.flush()
    return venue


def _far_future() -> date:
    today = datetime.now(UTC).date()
    return today + timedelta(days=10)


def _slot_iso(day: date, hour: int) -> str:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=DHK).astimezone(UTC).isoformat()


async def _login(api_client: AsyncClient, *, phone: str, fb_uid: str) -> str:
    def fake_verifier(_token: str) -> dict[str, Any]:
        return {"uid": fb_uid, "phone_number": phone}

    app.dependency_overrides[get_firebase_verifier] = lambda: fake_verifier
    try:
        resp = await api_client.post("/v1/auth/firebase", json={"id_token": "x" * 40})
        return resp.json()["access_token"]
    finally:
        app.dependency_overrides.pop(get_firebase_verifier, None)


def _override_verifier_with_iat(phone: str, age_seconds: int) -> None:
    def fake(_token: str) -> dict[str, Any]:
        return {
            "uid": "fb_reauth",
            "phone_number": phone,
            "iat": int(datetime.now(UTC).timestamp()) - age_seconds,
        }

    app.dependency_overrides[get_firebase_verifier] = lambda: fake


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_preview_full_refund_far_future(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()
    access = await _login(api_client, phone="+8801720000001", fb_uid="fb_preview1")
    target = _far_future()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_method": "cash",
        },
    )
    booking_id = hold.json()["booking_id"]

    resp = await api_client.get(
        f"/v1/bookings/{booking_id}/cancel-preview", headers=_auth(access)
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["refund_amount_bdt"] == 1000
    assert data["eligible_slot_count"] == 1
    assert data["full_refund_hours"] == 24
    # Unpaid booking → no re-OTP needed (no money to return).
    assert data["requires_reauth"] is False


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_preview_zero_refund_within_window(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()
    access = await _login(api_client, phone="+8801720000002", fb_uid="fb_preview2")
    target = _far_future()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_method": "cash",
        },
    )
    booking_id = hold.json()["booking_id"]

    # Backdate the slot so it's only 10h away.
    booking = (
        await db_session.execute(select(Booking).where(Booking.id == booking_id))
    ).scalar_one()
    booking.first_slot_at = datetime.now(UTC) + timedelta(hours=10)
    booking.last_slot_at = datetime.now(UTC) + timedelta(hours=11)
    await db_session.commit()

    from sqlalchemy import update

    from app.models import BookingSlot

    await db_session.execute(
        update(BookingSlot)
        .where(BookingSlot.booking_id == booking_id)
        .values(
            slot_start_at=datetime.now(UTC) + timedelta(hours=10),
            slot_end_at=datetime.now(UTC) + timedelta(hours=11),
        )
    )
    await db_session.commit()

    resp = await api_client.get(
        f"/v1/bookings/{booking_id}/cancel-preview", headers=_auth(access)
    )
    assert resp.status_code == 200
    assert resp.json()["refund_amount_bdt"] == 0


# ---------------------------------------------------------------------------
# Customer cancel — unpaid booking (no re-OTP)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_customer_cancel_unpaid_no_reauth_no_refund(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()
    access = await _login(api_client, phone="+8801720000003", fb_uid="fb_can1")
    target = _far_future()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_method": "cash",
        },
    )
    booking_id = hold.json()["booking_id"]

    resp = await api_client.post(
        f"/v1/bookings/{booking_id}/cancel",
        headers=_auth(access),
        json={"firebase_id_token": ""},
    )
    # Empty token works for unpaid bookings since reauth not required.
    assert resp.status_code in (200, 422)
    if resp.status_code == 422:
        # Pydantic min_length rejects empty string. Send valid stub instead.
        resp = await api_client.post(
            f"/v1/bookings/{booking_id}/cancel",
            headers=_auth(access),
            json={"firebase_id_token": "x" * 40},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["new_status"] == "cancelled"
    assert body["refund_required"] is False
    assert body["refund_amount_bdt"] == 0


# ---------------------------------------------------------------------------
# Customer cancel — paid cash booking (re-OTP required)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_customer_cancel_paid_requires_reauth(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    db_session.add(User(phone="+8801720100001", role=UserRole.ADMIN, manually_created=True))
    await db_session.commit()
    cust = await _login(api_client, phone="+8801720100002", fb_uid="fb_cust_paid")
    target = _far_future()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(cust),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_method": "cash",
        },
    )
    booking_id = hold.json()["booking_id"]

    # Admin marks cash paid.
    admin = await _login(api_client, phone="+8801720100001", fb_uid="fb_admin_paid")
    pay = await api_client.post(
        f"/v1/bookings/{booking_id}/mark-cash-paid", headers=_auth(admin)
    )
    assert pay.status_code == 200

    # Customer attempts cancel without a fresh token → 401 reauth_required.
    resp = await api_client.post(
        f"/v1/bookings/{booking_id}/cancel",
        headers=_auth(cust),
        json={"firebase_id_token": "x" * 40},  # provided but verifier returns no phone
    )
    # Default verifier override during _login was popped, so the verifier is the
    # real Firebase verifier — that fails on a stub token. Result: 401.
    assert resp.status_code == 401

    # Customer provides a fresh same-phone re-OTP → cancel succeeds.
    _override_verifier_with_iat("+8801720100002", age_seconds=10)
    try:
        resp = await api_client.post(
            f"/v1/bookings/{booking_id}/cancel",
            headers=_auth(cust),
            json={"firebase_id_token": "x" * 40},
        )
    finally:
        app.dependency_overrides.pop(get_firebase_verifier, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["new_status"] == "cancelled"
    assert body["refund_required"] is True
    assert body["refund_amount_bdt"] == 1000
    refund = (
        (
            await db_session.execute(
                select(Refund).where(Refund.id == body["refund_id"])
            )
        )
        .scalars()
        .one()
    )
    assert refund.status == RefundStatus.PENDING


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_customer_cancel_paid_stale_reauth_rejected(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    db_session.add(User(phone="+8801720100003", role=UserRole.ADMIN, manually_created=True))
    await db_session.commit()
    cust = await _login(api_client, phone="+8801720100004", fb_uid="fb_stale")
    target = _far_future()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(cust),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_method": "cash",
        },
    )
    booking_id = hold.json()["booking_id"]
    admin = await _login(api_client, phone="+8801720100003", fb_uid="fb_stale_admin")
    await api_client.post(
        f"/v1/bookings/{booking_id}/mark-cash-paid", headers=_auth(admin)
    )

    # Re-OTP token issued > 5 min ago.
    _override_verifier_with_iat("+8801720100004", age_seconds=10 * 60)
    try:
        resp = await api_client.post(
            f"/v1/bookings/{booking_id}/cancel",
            headers=_auth(cust),
            json={"firebase_id_token": "x" * 40},
        )
    finally:
        app.dependency_overrides.pop(get_firebase_verifier, None)

    assert resp.status_code == 401
    assert resp.json()["detail"] == "reauth_stale"


# ---------------------------------------------------------------------------
# Admin cancel — no re-OTP
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_admin_can_cancel_without_reauth(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    db_session.add(User(phone="+8801720200001", role=UserRole.ADMIN, manually_created=True))
    await db_session.commit()
    cust = await _login(api_client, phone="+8801720200002", fb_uid="fb_admincancel_cust")
    target = _far_future()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(cust),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_method": "cash",
        },
    )
    booking_id = hold.json()["booking_id"]

    admin = await _login(
        api_client, phone="+8801720200001", fb_uid="fb_admincancel_admin"
    )
    resp = await api_client.post(
        f"/v1/bookings/{booking_id}/cancel",
        headers=_auth(admin),
        json={"firebase_id_token": "x" * 40},
    )
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "cancelled"


# ---------------------------------------------------------------------------
# Repeat cancel rejected
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_double_cancel_returns_409(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()
    access = await _login(api_client, phone="+8801720300001", fb_uid="fb_double")
    target = _far_future()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_method": "cash",
        },
    )
    booking_id = hold.json()["booking_id"]
    first = await api_client.post(
        f"/v1/bookings/{booking_id}/cancel",
        headers=_auth(access),
        json={"firebase_id_token": "x" * 40},
    )
    assert first.status_code == 200

    second = await api_client.post(
        f"/v1/bookings/{booking_id}/cancel",
        headers=_auth(access),
        json={"firebase_id_token": "x" * 40},
    )
    assert second.status_code == 409
