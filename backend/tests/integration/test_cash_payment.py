"""Integration tests for the Phase 6 cash-on-arrival flow."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_firebase_verifier
from app.enums import (
    BookingStatus,
    PaymentCollection,
    PaymentProvider,
    PaymentStatus,
    UserRole,
)
from app.main import app
from app.models import Booking, Payment, User, Venue
from app.services.bookings import (
    NO_SHOW_BLACKLIST_THRESHOLD,
    reconcile_unpaid_cash_bookings,
)

DHK = ZoneInfo("Asia/Dhaka")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_venue(db: AsyncSession, *, cash_cancel_min: int = 15) -> Venue:
    venue = Venue(name="Cash Venue", cash_cancel_minutes_before=cash_cancel_min)
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


# ---------------------------------------------------------------------------
# Cash hold happy path
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_cash_hold_creates_confirmed_booking_immediately(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()

    access = await _login_user(api_client, phone="+8801718000001", fb_uid="fb_cash1")
    target = _next_weekday()
    resp = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_method": "cash",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["payment_method"] == "cash"
    assert body["hold_token"] is None
    assert body["hold_expires_at"] is None

    # Verify DB state — confirmed + cash_pending.
    booking = (
        await db_session.execute(select(Booking).where(Booking.id == body["booking_id"]))
    ).scalar_one()
    assert booking.status == BookingStatus.CONFIRMED
    assert booking.payment_collection == PaymentCollection.CASH_PENDING
    assert booking.hold_expires_at is None

    # No payment row created yet.
    payments = (await db_session.execute(select(Payment))).scalars().all()
    assert payments == []


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_cash_hold_blocks_double_book_via_gist(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()

    a_access = await _login_user(api_client, phone="+8801718000002", fb_uid="fb_cash2a")
    b_access = await _login_user(api_client, phone="+8801718000003", fb_uid="fb_cash2b")
    target = _next_weekday()
    body = {
        "venue_id": venue.id,
        "slots": [{"start_at": _slot_iso(target, 18)}],
        "payment_method": "cash",
    }

    first = await api_client.post("/v1/bookings/hold", headers=_auth(a_access), json=body)
    assert first.status_code == 201

    second = await api_client.post("/v1/bookings/hold", headers=_auth(b_access), json=body)
    assert second.status_code in (400, 409)


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_cash_disabled_user_cannot_book_cash(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()

    # Pre-create a blacklisted user.
    user = User(
        phone="+8801718000004",
        role=UserRole.CUSTOMER,
        manually_created=False,
        cash_disabled=True,
    )
    db_session.add(user)
    await db_session.commit()

    access = await _login_user(api_client, phone="+8801718000004", fb_uid="fb_cash3")
    target = _next_weekday()
    resp = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 17)}],
            "payment_method": "cash",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "cash_disabled_for_user"


# ---------------------------------------------------------------------------
# Auto-cancellation reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_reconcile_unpaid_cash_increments_no_show_and_blacklists(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session, cash_cancel_min=15)
    await db_session.commit()

    access = await _login_user(api_client, phone="+8801718000005", fb_uid="fb_cash_no_show")
    target = _next_weekday()

    # Place 3 cash holds across different slots so we can reconcile each.
    for hour in (16, 17, 18):
        resp = await api_client.post(
            "/v1/bookings/hold",
            headers=_auth(access),
            json={
                "venue_id": venue.id,
                "slots": [{"start_at": _slot_iso(target, hour)}],
                "payment_method": "cash",
            },
        )
        assert resp.status_code == 201

    # Backdate all bookings so the reconcile sweep treats them as past-deadline.
    backdated_first_slot = datetime.now(UTC) - timedelta(minutes=5)
    bookings = (await db_session.execute(select(Booking))).scalars().all()
    for b in bookings:
        b.first_slot_at = backdated_first_slot
    await db_session.commit()

    expired = await reconcile_unpaid_cash_bookings(db_session)
    assert expired == 3

    # User blacklisted at threshold.
    user = (
        await db_session.execute(select(User).where(User.phone == "+8801718000005"))
    ).scalar_one()
    assert user.no_show_count == 3
    assert NO_SHOW_BLACKLIST_THRESHOLD == 3
    assert user.cash_disabled is True

    # All three bookings transitioned.
    bookings = (await db_session.execute(select(Booking))).scalars().all()
    assert all(b.status == BookingStatus.AUTO_CANCELLED_NO_PAYMENT for b in bookings)


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_reconcile_skips_bookings_before_deadline(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session, cash_cancel_min=15)
    await db_session.commit()

    access = await _login_user(api_client, phone="+8801718000006", fb_uid="fb_cash_future")
    target = _next_weekday()
    await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_method": "cash",
        },
    )

    expired = await reconcile_unpaid_cash_bookings(db_session)
    assert expired == 0

    booking = (await db_session.execute(select(Booking))).scalars().one()
    assert booking.status == BookingStatus.CONFIRMED


# ---------------------------------------------------------------------------
# Admin mark-cash-paid
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_admin_mark_cash_paid_records_payment(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    admin = User(phone="+8801718100001", role=UserRole.ADMIN, manually_created=True)
    db_session.add(admin)
    await db_session.commit()

    cust_access = await _login_user(api_client, phone="+8801718100002", fb_uid="fb_cash_cust")
    target = _next_weekday()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(cust_access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_method": "cash",
        },
    )
    booking_id = hold.json()["booking_id"]

    admin_access = await _login_user(api_client, phone="+8801718100001", fb_uid="fb_cash_admin")
    resp = await api_client.post(
        f"/v1/bookings/{booking_id}/mark-cash-paid", headers=_auth(admin_access)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["payment_collection"] == "cash"

    payment = (await db_session.execute(select(Payment))).scalars().one()
    assert payment.provider == PaymentProvider.CASH
    assert payment.status == PaymentStatus.COMPLETED
    assert payment.amount_bdt == body["total_bdt"]


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_mark_cash_paid_idempotent(api_client: AsyncClient, db_session: AsyncSession) -> None:
    venue = await _make_venue(db_session)
    User(phone="+8801718100003", role=UserRole.ADMIN, manually_created=True)
    db_session.add(User(phone="+8801718100003", role=UserRole.ADMIN, manually_created=True))
    await db_session.commit()

    cust_access = await _login_user(api_client, phone="+8801718100004", fb_uid="fb_cash_cust2")
    target = _next_weekday()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(cust_access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_method": "cash",
        },
    )
    booking_id = hold.json()["booking_id"]

    admin_access = await _login_user(api_client, phone="+8801718100003", fb_uid="fb_cash_admin2")
    first = await api_client.post(
        f"/v1/bookings/{booking_id}/mark-cash-paid", headers=_auth(admin_access)
    )
    second = await api_client.post(
        f"/v1/bookings/{booking_id}/mark-cash-paid", headers=_auth(admin_access)
    )
    assert first.status_code == 200
    assert second.status_code == 200

    # Only one payment row exists.
    rows = (await db_session.execute(select(Payment))).scalars().all()
    assert len(rows) == 1


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_customer_cannot_mark_cash_paid(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()
    access = await _login_user(api_client, phone="+8801718100005", fb_uid="fb_cash_cust3")
    target = _next_weekday()
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

    resp = await api_client.post(f"/v1/bookings/{booking_id}/mark-cash-paid", headers=_auth(access))
    assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_status_response_exposes_payment_collection(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()
    access = await _login_user(api_client, phone="+8801718100006", fb_uid="fb_cash_cust4")
    target = _next_weekday()
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

    resp = await api_client.get(f"/v1/bookings/{booking_id}/status", headers=_auth(access))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "confirmed"
    assert data["payment_collection"] == "cash_pending"
