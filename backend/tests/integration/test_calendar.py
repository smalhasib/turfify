"""Integration tests for GET /v1/venues/{id}/calendar."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    BookingSource,
    BookingStatus,
    PaymentCollection,
    ScheduleExceptionType,
    SlotOverrideReason,
)
from app.models import (
    Booking,
    BookingSlot,
    PricingRule,
    ScheduleException,
    SlotOverride,
    User,
    Venue,
)

DHK = ZoneInfo("Asia/Dhaka")


async def _make_venue(
    db: AsyncSession,
    *,
    open_h: int = 6,
    close_h: int = 24,
    advance: int = 14,
    cutoff: int = 30,
    base: int = 1000,
) -> Venue:
    venue = Venue(
        name="Calendar Test Venue",
        open_hour=open_h,
        close_hour=close_h,
        slot_duration_min=60,
        advance_book_days=advance,
        cutoff_min=cutoff,
        base_price_bdt=base,
    )
    db.add(venue)
    await db.flush()
    return venue


def _next_weekday(target_weekday: int = 5) -> date:
    """Return a date well within advance_book_days that's not today."""
    today = datetime.now(UTC).date()
    delta = (target_weekday - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_calendar_default_grid(api_client: AsyncClient, db_session: AsyncSession) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()

    target = _next_weekday()
    resp = await api_client.get(
        f"/v1/venues/{venue.id}/calendar",
        params={"from": target.isoformat(), "to": target.isoformat()},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["venue_id"] == venue.id
    assert data["timezone"] == "Asia/Dhaka"
    assert len(data["days"]) == 1
    day = data["days"][0]
    assert day["date"] == target.isoformat()
    assert day["is_closed"] is False
    assert len(day["slots"]) == 18
    assert all(s["price_bdt"] == 1000 for s in day["slots"])


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_calendar_with_pricing_rules(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    db_session.add(
        PricingRule(
            venue_id=venue.id,
            name="evening peak",
            hour_start=18,
            hour_end=22,
            price_bdt=2000,
            priority=10,
        )
    )
    await db_session.commit()

    target = _next_weekday()
    resp = await api_client.get(
        f"/v1/venues/{venue.id}/calendar",
        params={"from": target.isoformat(), "to": target.isoformat()},
    )
    slots = resp.json()["days"][0]["slots"]
    by_local_hour = {datetime.fromisoformat(s["start_at"]).astimezone(DHK).hour: s for s in slots}
    assert by_local_hour[10]["price_bdt"] == 1000
    assert by_local_hour[19]["price_bdt"] == 2000


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_calendar_closed_exception(api_client: AsyncClient, db_session: AsyncSession) -> None:
    venue = await _make_venue(db_session)
    target = _next_weekday()
    db_session.add(
        ScheduleException(
            venue_id=venue.id,
            exception_date=target,
            type=ScheduleExceptionType.CLOSED,
            reason="Eid",
        )
    )
    await db_session.commit()

    resp = await api_client.get(
        f"/v1/venues/{venue.id}/calendar",
        params={"from": target.isoformat(), "to": target.isoformat()},
    )
    day = resp.json()["days"][0]
    assert day["is_closed"] is True
    assert day["slots"] == []


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_calendar_windows_exception(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    target = _next_weekday()
    db_session.add(
        ScheduleException(
            venue_id=venue.id,
            exception_date=target,
            type=ScheduleExceptionType.WINDOWS,
            windows=[
                {"start": "09:00", "end": "11:00"},
                {"start": "16:00", "end": "20:00"},
            ],
        )
    )
    await db_session.commit()

    resp = await api_client.get(
        f"/v1/venues/{venue.id}/calendar",
        params={"from": target.isoformat(), "to": target.isoformat()},
    )
    slots = resp.json()["days"][0]["slots"]
    starts = sorted(datetime.fromisoformat(s["start_at"]).astimezone(DHK).hour for s in slots)
    assert starts == [9, 10, 16, 17, 18, 19]


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_calendar_marks_booked_slot(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    user = User(phone="+8801723000001")
    db_session.add(user)
    await db_session.flush()

    target = _next_weekday()
    booked_start = datetime(target.year, target.month, target.day, 19, 0, tzinfo=DHK)
    booked_end = booked_start + timedelta(hours=1)
    booking = Booking(
        public_id="TRF-CAL-1",
        user_id=user.id,
        venue_id=venue.id,
        booking_source=BookingSource.WEB,
        payment_collection=PaymentCollection.ONLINE,
        subtotal_bdt=1000,
        total_amount_bdt=1000,
        slot_count=1,
        first_slot_at=booked_start,
        last_slot_at=booked_end,
        status=BookingStatus.CONFIRMED,
    )
    db_session.add(booking)
    await db_session.flush()
    db_session.add(
        BookingSlot(
            booking_id=booking.id,
            venue_id=venue.id,
            slot_start_at=booked_start,
            slot_end_at=booked_end,
            price_bdt=1000,
            booking_status=BookingStatus.CONFIRMED,
        )
    )
    await db_session.commit()

    resp = await api_client.get(
        f"/v1/venues/{venue.id}/calendar",
        params={"from": target.isoformat(), "to": target.isoformat()},
    )
    slots = resp.json()["days"][0]["slots"]
    by_hour = {datetime.fromisoformat(s["start_at"]).astimezone(DHK).hour: s for s in slots}
    assert by_hour[19]["status"] == "booked"
    assert by_hour[20]["status"] == "available"


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_calendar_marks_blocked_slot(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    user = User(phone="+8801723000002")
    db_session.add(user)
    await db_session.flush()

    target = _next_weekday()
    block_start = datetime(target.year, target.month, target.day, 14, 0, tzinfo=DHK)
    block_end = block_start + timedelta(hours=2)
    db_session.add(
        SlotOverride(
            venue_id=venue.id,
            slot_start_at=block_start,
            slot_end_at=block_end,
            reason=SlotOverrideReason.MAINTENANCE,
            created_by=user.id,
        )
    )
    await db_session.commit()

    resp = await api_client.get(
        f"/v1/venues/{venue.id}/calendar",
        params={"from": target.isoformat(), "to": target.isoformat()},
    )
    slots = resp.json()["days"][0]["slots"]
    by_hour = {datetime.fromisoformat(s["start_at"]).astimezone(DHK).hour: s for s in slots}
    assert by_hour[14]["status"] == "blocked"
    assert by_hour[15]["status"] == "blocked"
    assert by_hour[13]["status"] == "available"
    assert by_hour[16]["status"] == "available"


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_calendar_returns_multiple_days(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()

    start = _next_weekday()
    end = start + timedelta(days=2)
    resp = await api_client.get(
        f"/v1/venues/{venue.id}/calendar",
        params={"from": start.isoformat(), "to": end.isoformat()},
    )
    data = resp.json()
    assert len(data["days"]) == 3


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_calendar_404_for_unknown_venue(api_client: AsyncClient) -> None:
    resp = await api_client.get(
        "/v1/venues/9999/calendar",
        params={"from": "2026-05-10", "to": "2026-05-10"},
    )
    assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_calendar_rejects_inverted_range(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()
    resp = await api_client.get(
        f"/v1/venues/{venue.id}/calendar",
        params={"from": "2026-05-12", "to": "2026-05-10"},
    )
    assert resp.status_code == 400


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_calendar_rejects_oversized_range(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session, advance=180)
    await db_session.commit()
    start = _next_weekday()
    end = start + timedelta(days=60)
    resp = await api_client.get(
        f"/v1/venues/{venue.id}/calendar",
        params={"from": start.isoformat(), "to": end.isoformat()},
    )
    assert resp.status_code == 400
    assert "31_days" in resp.json()["detail"]


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_calendar_rejects_beyond_advance_window(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session, advance=7)
    await db_session.commit()

    today = datetime.now(UTC).date()
    too_far = today + timedelta(days=20)
    resp = await api_client.get(
        f"/v1/venues/{venue.id}/calendar",
        params={"from": today.isoformat(), "to": too_far.isoformat()},
    )
    assert resp.status_code == 400
    assert "advance_window" in resp.json()["detail"]
