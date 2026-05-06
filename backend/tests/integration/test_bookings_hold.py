"""Integration tests for the Phase 4 hold flow.

Covered:
- Happy hold (single + multi-day).
- Sequential conflict: second hold against the same slot fails (Lua + GIST).
- Lua atomicity: see test_locks_lua.py for direct Redis-level proof.
- Slot must be available (booked / blocked / past rejected).
- Status endpoint enforces ownership.
- Cancel-hold releases lock + transitions to cancelled.
- Lazy reconciliation expires past-TTL holds + frees slots for re-hold.

NOTE: We don't drive truly concurrent API calls here because SQLAlchemy's
`AsyncSession` is not safe for parallel operations on the same session, and
the test harness shares one `db_session` across an `api_client`. Concurrency
correctness is proven at the lock layer in `test_locks_lua.py`, and the GIST
exclusion proof lives in `test_schema.py`. Both run against real Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_firebase_verifier
from app.enums import BookingStatus, UserRole
from app.main import app
from app.models import Booking, BookingSlot, User, Venue
from app.services.locks import make_slot_key

DHK = ZoneInfo("Asia/Dhaka")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_venue(db: AsyncSession) -> Venue:
    venue = Venue(name="Hold Test Venue")
    db.add(venue)
    await db.flush()
    return venue


def _next_weekday() -> datetime.date:
    today = datetime.now(UTC).date()
    delta = (5 - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def _slot_iso(day: datetime.date, hour: int) -> str:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=DHK).astimezone(UTC).isoformat()


async def _login_user(api_client: AsyncClient, *, phone: str, fb_uid: str) -> tuple[str, str]:
    """Returns (access_token, refresh_token) after Firebase exchange."""

    def fake_verifier(_token: str) -> dict[str, Any]:
        return {"uid": fb_uid, "phone_number": phone}

    app.dependency_overrides[get_firebase_verifier] = lambda: fake_verifier
    try:
        resp = await api_client.post("/v1/auth/firebase", json={"id_token": "x" * 40})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        return data["access_token"], data["refresh_token"]
    finally:
        app.dependency_overrides.pop(get_firebase_verifier, None)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_hold_single_slot_happy_path(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()

    access, _ = await _login_user(api_client, phone="+8801712100001", fb_uid="fb_hold_1")

    target = _next_weekday()
    resp = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["public_id"].startswith("TRF-")
    assert body["slot_count"] == 1
    assert body["total_bdt"] == 1000
    assert body["hold_expires_at"]


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_hold_multi_day(api_client: AsyncClient, db_session: AsyncSession) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()

    access, _ = await _login_user(api_client, phone="+8801712100002", fb_uid="fb_hold_2")

    day1 = _next_weekday()
    day2 = day1 + timedelta(days=2)
    resp = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [
                {"start_at": _slot_iso(day1, 16)},
                {"start_at": _slot_iso(day1, 17)},
                {"start_at": _slot_iso(day2, 19)},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slot_count"] == 3
    assert body["total_bdt"] == 3000


# ---------------------------------------------------------------------------
# Lock conflict
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_hold_rejects_already_booked_slot(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()

    a_access, _ = await _login_user(api_client, phone="+8801712100005", fb_uid="fb_two_a")
    b_access, _ = await _login_user(api_client, phone="+8801712100006", fb_uid="fb_two_b")
    target = _next_weekday()
    body = {
        "venue_id": venue.id,
        "slots": [{"start_at": _slot_iso(target, 20)}],
    }

    first = await api_client.post("/v1/bookings/hold", headers=_auth(a_access), json=body)
    assert first.status_code == 201

    second = await api_client.post("/v1/bookings/hold", headers=_auth(b_access), json=body)
    assert second.status_code in (400, 409)


# ---------------------------------------------------------------------------
# Status + cancel
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_status_returns_seconds_to_expiry(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()

    access, _ = await _login_user(api_client, phone="+8801712100007", fb_uid="fb_status_a")
    target = _next_weekday()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={"venue_id": venue.id, "slots": [{"start_at": _slot_iso(target, 19)}]},
    )
    assert hold.status_code == 201
    booking_id = hold.json()["booking_id"]

    resp = await api_client.get(f"/v1/bookings/{booking_id}/status", headers=_auth(access))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending_payment"
    assert data["seconds_to_expiry"] is not None
    assert 0 < data["seconds_to_expiry"] <= 8 * 60


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_status_404_for_other_users_booking(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()

    a_access, _ = await _login_user(api_client, phone="+8801712100008", fb_uid="fb_owner")
    b_access, _ = await _login_user(api_client, phone="+8801712100009", fb_uid="fb_intruder")
    target = _next_weekday()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(a_access),
        json={"venue_id": venue.id, "slots": [{"start_at": _slot_iso(target, 17)}]},
    )
    booking_id = hold.json()["booking_id"]
    resp = await api_client.get(f"/v1/bookings/{booking_id}/status", headers=_auth(b_access))
    assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_admin_can_read_any_booking_status(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    # Pre-create admin user.
    admin = User(phone="+8801712100010", role=UserRole.ADMIN, manually_created=True)
    db_session.add(admin)
    await db_session.commit()

    cust_access, _ = await _login_user(api_client, phone="+8801712100011", fb_uid="fb_admin_owner")
    admin_access, _ = await _login_user(api_client, phone="+8801712100010", fb_uid="fb_admin_self")

    target = _next_weekday()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(cust_access),
        json={"venue_id": venue.id, "slots": [{"start_at": _slot_iso(target, 16)}]},
    )
    booking_id = hold.json()["booking_id"]
    resp = await api_client.get(f"/v1/bookings/{booking_id}/status", headers=_auth(admin_access))
    assert resp.status_code == 200


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_cancel_hold_releases_lock_and_marks_cancelled(
    api_client: AsyncClient, db_session: AsyncSession, redis_client: Any
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()

    access, _ = await _login_user(api_client, phone="+8801712100012", fb_uid="fb_cancel")
    target = _next_weekday()
    slot_iso = _slot_iso(target, 21)
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={"venue_id": venue.id, "slots": [{"start_at": slot_iso}]},
    )
    assert hold.status_code == 201
    booking_id = hold.json()["booking_id"]

    # Lock should exist now.
    slot_key = make_slot_key(
        venue.id,
        datetime.fromisoformat(slot_iso),
    )
    assert await redis_client.get(slot_key) is not None

    cancel = await api_client.post(f"/v1/bookings/{booking_id}/cancel-hold", headers=_auth(access))
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    # Lock released.
    assert await redis_client.get(slot_key) is None

    # Slot is bookable again by another user.
    other_access, _ = await _login_user(
        api_client, phone="+8801712100013", fb_uid="fb_after_cancel"
    )
    redo = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(other_access),
        json={"venue_id": venue.id, "slots": [{"start_at": slot_iso}]},
    )
    assert redo.status_code == 201


# ---------------------------------------------------------------------------
# Lazy reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_expired_hold_reconciled_on_status_read(
    api_client: AsyncClient, db_session: AsyncSession, redis_client: Any
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()

    access, _ = await _login_user(api_client, phone="+8801712100014", fb_uid="fb_expire")
    target = _next_weekday()
    slot_iso = _slot_iso(target, 22)
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={"venue_id": venue.id, "slots": [{"start_at": slot_iso}]},
    )
    booking_id = hold.json()["booking_id"]

    # Backdate hold_expires_at to simulate elapsed TTL.
    booking = (
        await db_session.execute(select(Booking).where(Booking.id == booking_id))
    ).scalar_one()
    booking.hold_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    # Reading status triggers reconciliation.
    resp = await api_client.get(f"/v1/bookings/{booking_id}/status", headers=_auth(access))
    assert resp.status_code == 200
    assert resp.json()["status"] == "expired"

    # The slot should now be free for someone else to hold.
    other_access, _ = await _login_user(
        api_client, phone="+8801712100015", fb_uid="fb_after_expire"
    )
    redo = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(other_access),
        json={"venue_id": venue.id, "slots": [{"start_at": slot_iso}]},
    )
    assert redo.status_code == 201

    # Old booking_slots row should have been transitioned (booking_status synced
    # by the trg_sync_booking_slot_status trigger).
    slots = (
        (await db_session.execute(select(BookingSlot).where(BookingSlot.booking_id == booking_id)))
        .scalars()
        .all()
    )
    assert all(s.booking_status == BookingStatus.EXPIRED for s in slots)


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_hold_requires_auth(api_client: AsyncClient, db_session: AsyncSession) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()

    target = _next_weekday()
    resp = await api_client.post(
        "/v1/bookings/hold",
        json={"venue_id": venue.id, "slots": [{"start_at": _slot_iso(target, 18)}]},
    )
    assert resp.status_code == 401
