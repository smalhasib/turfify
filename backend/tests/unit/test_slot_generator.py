"""Unit tests for the slot generator (pure logic, no DB)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.enums import BookingStatus, ScheduleExceptionType, SlotOverrideReason
from app.models import (
    BookingSlot,
    PricingRule,
    ScheduleException,
    SlotOverride,
    Venue,
)
from app.services.slots import slots_for_day

DHK = ZoneInfo("Asia/Dhaka")


def _venue(
    *,
    open_h: int = 6,
    close_h: int = 24,
    duration: int = 60,
    advance: int = 14,
    cutoff: int = 30,
    base: int = 1000,
    tz: str = "Asia/Dhaka",
) -> Venue:
    return Venue(
        id=1,
        name="V",
        open_hour=open_h,
        close_hour=close_h,
        slot_duration_min=duration,
        advance_book_days=advance,
        cutoff_min=cutoff,
        base_price_bdt=base,
        timezone=tz,
        is_active=True,
    )


def _now_dhk(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Return a UTC `now` corresponding to the given Dhaka local time."""
    local = datetime(year, month, day, hour, minute, tzinfo=DHK)
    return local.astimezone(ZoneInfo("UTC"))


def _rule(*, hour_start: int, hour_end: int, price: int, priority: int = 0) -> PricingRule:
    return PricingRule(
        id=1,
        venue_id=1,
        name="r",
        hour_start=hour_start,
        hour_end=hour_end,
        price_bdt=price,
        priority=priority,
        is_active=True,
    )


def _override(*, start_local_hour: int, end_local_hour: int, day: date) -> SlotOverride:
    return SlotOverride(
        id=1,
        venue_id=1,
        slot_start_at=datetime(day.year, day.month, day.day, start_local_hour, 0, tzinfo=DHK),
        slot_end_at=datetime(day.year, day.month, day.day, end_local_hour, 0, tzinfo=DHK),
        reason=SlotOverrideReason.MAINTENANCE,
    )


def _booked(*, start_local_hour: int, end_local_hour: int, day: date) -> BookingSlot:
    return BookingSlot(
        id=1,
        booking_id=1,
        venue_id=1,
        slot_start_at=datetime(day.year, day.month, day.day, start_local_hour, 0, tzinfo=DHK),
        slot_end_at=datetime(day.year, day.month, day.day, end_local_hour, 0, tzinfo=DHK),
        price_bdt=1000,
        booking_status=BookingStatus.CONFIRMED,
    )


# ---------------------------------------------------------------------------
# Default grid
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_default_grid_full_day() -> None:
    venue = _venue(open_h=6, close_h=24, duration=60)
    day = date(2026, 5, 12)
    now = _now_dhk(2026, 5, 11, 23, 0)  # day before, late evening

    result = slots_for_day(
        venue=venue,
        day=day,
        pricing_rules=[],
        schedule_exception=None,
        slot_overrides=[],
        booked_slots=[],
        now=now,
    )

    assert result.is_closed is False
    assert len(result.slots) == 18  # 6am..midnight = 18 hours
    # All slots in the future should be available.
    assert all(s.status == "available" for s in result.slots)
    # Default price = venue base.
    assert all(s.price_bdt == venue.base_price_bdt for s in result.slots)


@pytest.mark.unit
def test_default_grid_30min_duration() -> None:
    venue = _venue(open_h=6, close_h=10, duration=30)
    day = date(2026, 5, 12)
    now = _now_dhk(2026, 5, 11, 23, 0)

    result = slots_for_day(
        venue=venue,
        day=day,
        pricing_rules=[],
        schedule_exception=None,
        slot_overrides=[],
        booked_slots=[],
        now=now,
    )
    assert len(result.slots) == (10 - 6) * 2  # 8 half-hour slots


# ---------------------------------------------------------------------------
# Schedule exceptions
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_closed_exception_returns_no_slots() -> None:
    venue = _venue()
    day = date(2026, 5, 12)
    now = _now_dhk(2026, 5, 11, 23, 0)
    exc = ScheduleException(id=1, venue_id=1, exception_date=day, type=ScheduleExceptionType.CLOSED)

    result = slots_for_day(
        venue=venue,
        day=day,
        pricing_rules=[],
        schedule_exception=exc,
        slot_overrides=[],
        booked_slots=[],
        now=now,
    )
    assert result.is_closed is True
    assert result.slots == []


@pytest.mark.unit
def test_windows_exception_two_segments() -> None:
    """User example from grilling: 10 May has 9-11 + 16-20 windows only."""
    venue = _venue()
    day = date(2026, 5, 10)
    now = _now_dhk(2026, 5, 9, 12, 0)
    exc = ScheduleException(
        id=1,
        venue_id=1,
        exception_date=day,
        type=ScheduleExceptionType.WINDOWS,
        windows=[
            {"start": "09:00", "end": "11:00"},
            {"start": "16:00", "end": "20:00"},
        ],
    )

    result = slots_for_day(
        venue=venue,
        day=day,
        pricing_rules=[],
        schedule_exception=exc,
        slot_overrides=[],
        booked_slots=[],
        now=now,
    )
    # Expected: 9-10, 10-11, 16-17, 17-18, 18-19, 19-20
    assert len(result.slots) == 6
    starts_local = [s.start_at.astimezone(DHK).hour for s in result.slots]
    assert starts_local == [9, 10, 16, 17, 18, 19]


@pytest.mark.unit
def test_windows_exception_with_per_window_price() -> None:
    venue = _venue()
    day = date(2026, 5, 10)
    now = _now_dhk(2026, 5, 9, 12, 0)
    exc = ScheduleException(
        id=1,
        venue_id=1,
        exception_date=day,
        type=ScheduleExceptionType.WINDOWS,
        windows=[
            {"start": "09:00", "end": "11:00", "price": 800},
            {"start": "16:00", "end": "20:00", "price": 1500},
        ],
    )

    result = slots_for_day(
        venue=venue,
        day=day,
        pricing_rules=[],
        schedule_exception=exc,
        slot_overrides=[],
        booked_slots=[],
        now=now,
    )
    morning = [s for s in result.slots if s.start_at.astimezone(DHK).hour < 12]
    evening = [s for s in result.slots if s.start_at.astimezone(DHK).hour >= 16]
    assert all(s.price_bdt == 800 for s in morning)
    assert all(s.price_bdt == 1500 for s in evening)


# ---------------------------------------------------------------------------
# Pricing rules drive default-grid prices
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pricing_rule_applied_to_evening_slots() -> None:
    venue = _venue(base=1000)
    day = date(2026, 5, 12)
    now = _now_dhk(2026, 5, 11, 23, 0)
    rules = [_rule(hour_start=18, hour_end=22, price=2000, priority=10)]

    result = slots_for_day(
        venue=venue,
        day=day,
        pricing_rules=rules,
        schedule_exception=None,
        slot_overrides=[],
        booked_slots=[],
        now=now,
    )
    morning_slot = next(s for s in result.slots if s.start_at.astimezone(DHK).hour == 8)
    evening_slot = next(s for s in result.slots if s.start_at.astimezone(DHK).hour == 19)
    assert morning_slot.price_bdt == 1000
    assert evening_slot.price_bdt == 2000


# ---------------------------------------------------------------------------
# Slot overrides + bookings + cutoff
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_slot_override_blocks_range() -> None:
    venue = _venue()
    day = date(2026, 5, 12)
    now = _now_dhk(2026, 5, 11, 23, 0)

    result = slots_for_day(
        venue=venue,
        day=day,
        pricing_rules=[],
        schedule_exception=None,
        slot_overrides=[_override(start_local_hour=14, end_local_hour=17, day=day)],
        booked_slots=[],
        now=now,
    )
    blocked_hours = [s.start_at.astimezone(DHK).hour for s in result.slots if s.status == "blocked"]
    assert blocked_hours == [14, 15, 16]


@pytest.mark.unit
def test_booked_slot_marked_booked_not_available() -> None:
    venue = _venue()
    day = date(2026, 5, 12)
    now = _now_dhk(2026, 5, 11, 23, 0)

    result = slots_for_day(
        venue=venue,
        day=day,
        pricing_rules=[],
        schedule_exception=None,
        slot_overrides=[],
        booked_slots=[_booked(start_local_hour=18, end_local_hour=19, day=day)],
        now=now,
    )
    s = next(s for s in result.slots if s.start_at.astimezone(DHK).hour == 18)
    assert s.status == "booked"


@pytest.mark.unit
def test_cutoff_marks_imminent_slots_past() -> None:
    """Slots starting before now+cutoff_min are 'past' (un-bookable)."""
    venue = _venue(cutoff=30)
    day = date(2026, 5, 12)
    # now = 5:45pm Dhaka local on the booking day; cutoff = 6:15pm.
    now = _now_dhk(2026, 5, 12, 17, 45)

    result = slots_for_day(
        venue=venue,
        day=day,
        pricing_rules=[],
        schedule_exception=None,
        slot_overrides=[],
        booked_slots=[],
        now=now,
    )
    by_hour = {s.start_at.astimezone(DHK).hour: s for s in result.slots}

    # 17:00 has already ended ⇒ past
    assert by_hour[17].status == "past"
    # 18:00 starts at 6pm; cutoff is 6:15pm; 18:00 < cutoff ⇒ past
    assert by_hour[18].status == "past"
    # 19:00 starts at 7pm; >= cutoff ⇒ available
    assert by_hour[19].status == "available"


@pytest.mark.unit
def test_past_status_takes_precedence_over_booked() -> None:
    venue = _venue()
    day = date(2026, 5, 12)
    now = _now_dhk(2026, 5, 12, 22, 0)  # late on the same day

    result = slots_for_day(
        venue=venue,
        day=day,
        pricing_rules=[],
        schedule_exception=None,
        slot_overrides=[],
        booked_slots=[_booked(start_local_hour=10, end_local_hour=11, day=day)],
        now=now,
    )
    s = next(s for s in result.slots if s.start_at.astimezone(DHK).hour == 10)
    assert s.status == "past"


@pytest.mark.unit
def test_now_must_be_timezone_aware() -> None:
    venue = _venue()
    with pytest.raises(ValueError):
        slots_for_day(
            venue=venue,
            day=date(2026, 5, 12),
            pricing_rules=[],
            schedule_exception=None,
            slot_overrides=[],
            booked_slots=[],
            now=datetime(2026, 5, 11, 0, 0),  # naive
        )


@pytest.mark.unit
def test_close_hour_24_works() -> None:
    venue = _venue(open_h=22, close_h=24, duration=60)
    day = date(2026, 5, 12)
    now = _now_dhk(2026, 5, 11, 12, 0)

    result = slots_for_day(
        venue=venue,
        day=day,
        pricing_rules=[],
        schedule_exception=None,
        slot_overrides=[],
        booked_slots=[],
        now=now,
    )
    starts = sorted(s.start_at.astimezone(DHK).hour for s in result.slots)
    assert starts == [22, 23]
    # Last slot should end at midnight of next day in local time.
    last = next(s for s in result.slots if s.start_at.astimezone(DHK).hour == 23)
    end_local = last.end_at.astimezone(DHK)
    assert end_local == datetime(day.year, day.month, day.day, tzinfo=DHK) + timedelta(days=1)
