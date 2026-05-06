"""Integration tests for Phase 9 admin endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_firebase_verifier
from app.enums import RefundStatus, UserRole
from app.main import app
from app.models import (
    Booking,
    BookingSlot,
    Payment,
    Refund,
    User,
    Venue,
)

DHK = ZoneInfo("Asia/Dhaka")


async def _make_venue(db: AsyncSession) -> Venue:
    venue = Venue(name="Admin Venue")
    db.add(venue)
    await db.flush()
    return venue


def _far_future() -> date:
    today = datetime.now(UTC).date()
    return today + timedelta(days=10)


def _slot_iso(day: date, hour: int) -> str:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=DHK).astimezone(UTC).isoformat()


async def _login(api_client: AsyncClient, *, phone: str, fb_uid: str) -> str:
    def fake(_token: str) -> dict[str, Any]:
        return {"uid": fb_uid, "phone_number": phone}

    app.dependency_overrides[get_firebase_verifier] = lambda: fake
    try:
        resp = await api_client.post("/v1/auth/firebase", json={"id_token": "x" * 40})
        return resp.json()["access_token"]
    finally:
        app.dependency_overrides.pop(get_firebase_verifier, None)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Admin booking creation
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_admin_creates_cash_paid_booking_for_quick_create_user(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    db_session.add(User(phone="+8801721000001", role=UserRole.ADMIN, manually_created=True))
    await db_session.commit()

    admin = await _login(api_client, phone="+8801721000001", fb_uid="fb_admin_book")
    target = _far_future()
    resp = await api_client.post(
        "/v1/admin/bookings",
        headers=_auth(admin),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19), "price_bdt": 800}],
            "payment_collection": "cash",
            "quick_create_phone": "+8801721000099",
            "quick_create_name": "Walk-in Bilal",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["payment_collection"] == "cash"
    assert body["status"] == "confirmed"
    assert body["payment_id"] is not None
    assert body["total_bdt"] == 800

    # Quick-create user materialized.
    new_user = (
        await db_session.execute(select(User).where(User.phone == "+8801721000099"))
    ).scalar_one()
    assert new_user.manually_created is True

    # Payment row inserted with provider=cash.
    payment = (await db_session.execute(select(Payment))).scalars().one()
    assert payment.provider.value == "cash"
    assert payment.amount_bdt == 800

    # booking_slot has overridden price flag.
    slot = (await db_session.execute(select(BookingSlot))).scalars().one()
    assert slot.price_overridden is True
    assert slot.price_bdt == 800


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_admin_free_booking_requires_reason(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    db_session.add(User(phone="+8801721000002", role=UserRole.ADMIN, manually_created=True))
    await db_session.commit()
    admin = await _login(api_client, phone="+8801721000002", fb_uid="fb_admin_free")

    target = _far_future()
    bad = await api_client.post(
        "/v1/admin/bookings",
        headers=_auth(admin),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_collection": "free",
            "quick_create_phone": "+8801721000098",
        },
    )
    assert bad.status_code == 400
    assert bad.json()["detail"] == "free_reason_required"

    ok = await api_client.post(
        "/v1/admin/bookings",
        headers=_auth(admin),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_collection": "free",
            "quick_create_phone": "+8801721000098",
            "free_reason": "VIP guest",
        },
    )
    assert ok.status_code == 201
    booking = (
        await db_session.execute(select(Booking).where(Booking.id == ok.json()["booking_id"]))
    ).scalar_one()
    assert booking.free_reason == "VIP guest"
    assert booking.payment_collection.value == "free"


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_admin_booking_blocked_by_existing_booking_via_gist(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    db_session.add(User(phone="+8801721000003", role=UserRole.ADMIN, manually_created=True))
    await db_session.commit()

    cust = await _login(api_client, phone="+8801721000004", fb_uid="fb_block_cust")
    target = _far_future()
    first = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(cust),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_method": "cash",
        },
    )
    assert first.status_code == 201

    admin = await _login(api_client, phone="+8801721000003", fb_uid="fb_block_admin")
    resp = await api_client.post(
        "/v1/admin/bookings",
        headers=_auth(admin),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_collection": "cash",
            "quick_create_phone": "+8801721000097",
        },
    )
    # Slot already booked by customer; admin blocked at grid match (status=booked).
    assert resp.status_code in (400, 409)


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_customer_cannot_call_admin_booking(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()
    access = await _login(api_client, phone="+8801721000005", fb_uid="fb_block_basic")
    target = _far_future()
    resp = await api_client.post(
        "/v1/admin/bookings",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_collection": "cash",
            "quick_create_phone": "+8801721000096",
        },
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Schedule exception CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_admin_schedule_exception_crud(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    db_session.add(User(phone="+8801721100001", role=UserRole.ADMIN, manually_created=True))
    await db_session.commit()
    admin = await _login(api_client, phone="+8801721100001", fb_uid="fb_exc_admin")

    target = _far_future().isoformat()
    create = await api_client.post(
        "/v1/admin/schedule-exceptions",
        headers=_auth(admin),
        json={
            "venue_id": venue.id,
            "exception_date": f"{target}T00:00:00Z",
            "type": "closed",
            "reason": "Maintenance",
        },
    )
    assert create.status_code == 201, create.text
    exc_id = create.json()["id"]

    dup = await api_client.post(
        "/v1/admin/schedule-exceptions",
        headers=_auth(admin),
        json={
            "venue_id": venue.id,
            "exception_date": f"{target}T00:00:00Z",
            "type": "closed",
        },
    )
    assert dup.status_code == 409

    listing = await api_client.get(
        f"/v1/admin/venues/{venue.id}/schedule-exceptions", headers=_auth(admin)
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    deleted = await api_client.delete(
        f"/v1/admin/schedule-exceptions/{exc_id}", headers=_auth(admin)
    )
    assert deleted.status_code == 204
    after = await api_client.get(
        f"/v1/admin/venues/{venue.id}/schedule-exceptions", headers=_auth(admin)
    )
    assert after.json() == []


# ---------------------------------------------------------------------------
# Slot override CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_admin_slot_override_crud_and_blocks_calendar(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    db_session.add(User(phone="+8801721100002", role=UserRole.ADMIN, manually_created=True))
    await db_session.commit()
    admin = await _login(api_client, phone="+8801721100002", fb_uid="fb_so_admin")

    target = _far_future()
    start = f"{target.isoformat()}T13:00:00Z"
    end = f"{target.isoformat()}T14:00:00Z"
    create = await api_client.post(
        "/v1/admin/slot-overrides",
        headers=_auth(admin),
        json={
            "venue_id": venue.id,
            "slot_start_at": start,
            "slot_end_at": end,
            "reason": "maintenance",
        },
    )
    assert create.status_code == 201, create.text
    so_id = create.json()["id"]

    listing = await api_client.get(
        f"/v1/admin/venues/{venue.id}/slot-overrides", headers=_auth(admin)
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    # Calendar reflects the block.
    cal = await api_client.get(
        f"/v1/venues/{venue.id}/calendar",
        params={"from": target.isoformat(), "to": target.isoformat()},
    )
    slots = cal.json()["days"][0]["slots"]
    blocked = [s for s in slots if s["status"] == "blocked"]
    assert len(blocked) >= 1

    deleted = await api_client.delete(f"/v1/admin/slot-overrides/{so_id}", headers=_auth(admin))
    assert deleted.status_code == 204


# ---------------------------------------------------------------------------
# Refund completion
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_admin_completes_manual_refund(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    db_session.add(User(phone="+8801721200001", role=UserRole.ADMIN, manually_created=True))
    await db_session.commit()
    admin = await _login(api_client, phone="+8801721200001", fb_uid="fb_refund_admin")

    # Admin creates a paid cash booking and cancels it (admin path skips re-OTP).
    target = _far_future()
    create = await api_client.post(
        "/v1/admin/bookings",
        headers=_auth(admin),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_collection": "cash",
            "quick_create_phone": "+8801721200002",
        },
    )
    assert create.status_code == 201, create.text
    booking_id = create.json()["booking_id"]

    cancel = await api_client.post(
        f"/v1/bookings/{booking_id}/cancel",
        headers=_auth(admin),
        json={"firebase_id_token": "x" * 40},
    )
    assert cancel.status_code == 200, cancel.text
    refund_id = cancel.json()["refund_id"]
    assert refund_id is not None

    pending = await api_client.get("/v1/admin/refunds/pending", headers=_auth(admin))
    assert pending.status_code == 200
    assert any(r["id"] == refund_id for r in pending.json())

    complete = await api_client.post(
        f"/v1/admin/refunds/{refund_id}/complete",
        headers=_auth(admin),
        json={"provider_refund_id": "manual-cash-001"},
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "completed"

    refund = (await db_session.execute(select(Refund).where(Refund.id == refund_id))).scalar_one()
    assert refund.status == RefundStatus.COMPLETED
    assert refund.provider_refund_id == "manual-cash-001"
