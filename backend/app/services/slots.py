"""Slot generator.

A slot is `(start_at, end_at, status, price_bdt)`. There is no `slots` table;
slots are derived per-day from:
  - `Venue` open/close hours and slot duration
  - `ScheduleException` rows for the date (closed | windows)
  - `SlotOverride` rows blocking specific time ranges (admin maintenance, etc.)
  - Active `BookingSlot` rows (status in {pending_payment, confirmed})
  - Cutoff (`now() + venue.cutoff_min`)
  - Advance window (`now() + venue.advance_book_days`)
  - Pricing rules (resolved per slot via `services.pricing`)

This module is pure: callers fetch the relevant DB rows and pass them in.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from app.enums import ScheduleExceptionType
from app.models import (
    BookingSlot,
    PricingRule,
    ScheduleException,
    SlotOverride,
    Venue,
)
from app.services.pricing import resolve_price

SlotStatus = Literal["available", "booked", "blocked", "past"]


@dataclass(frozen=True)
class CalendarSlot:
    start_at: datetime  # tz-aware UTC
    end_at: datetime  # tz-aware UTC
    status: SlotStatus
    price_bdt: int


@dataclass(frozen=True)
class CalendarDay:
    date: date  # in venue's timezone
    is_closed: bool
    slots: list[CalendarSlot]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tz(venue: Venue) -> ZoneInfo:
    return ZoneInfo(venue.timezone)


def _utc(dt: datetime) -> datetime:
    """Normalize to UTC for storage / overlap comparison."""
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return dt.astimezone(UTC)


def _local(dt: datetime, venue: Venue) -> datetime:
    return dt.astimezone(_tz(venue))


def _parse_hhmm(value: str) -> time:
    """Parse 'HH:MM' (or 'HH:MM:SS') to a time."""
    parts = value.split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    return time(hour=h, minute=m)


def _windows_from_exception(
    exc: ScheduleException,
) -> list[tuple[time, time, int | None]]:
    """Return [(start_time, end_time, optional_price_bdt), ...] for a windows
    exception. Each window may carry an explicit `price` override.
    """
    out: list[tuple[time, time, int | None]] = []
    if exc.windows:
        for w in exc.windows:
            start = _parse_hhmm(w["start"])
            end = _parse_hhmm(w["end"])
            price = w.get("price")
            out.append((start, end, int(price) if price is not None else None))
    return out


def _ranges_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open [a_start, a_end) overlaps [b_start, b_end)?"""
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def slots_for_day(
    *,
    venue: Venue,
    day: date,
    pricing_rules: Iterable[PricingRule],
    schedule_exception: ScheduleException | None,
    slot_overrides: Iterable[SlotOverride],
    booked_slots: Iterable[BookingSlot],
    now: datetime,
) -> CalendarDay:
    """Return the slot grid for `day` (interpreted in the venue's timezone).

    `now` must be tz-aware; used for cutoff + past-marker decisions.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    tz = _tz(venue)
    cutoff = now + timedelta(minutes=venue.cutoff_min)

    # Closed via schedule exception → no slots.
    if schedule_exception is not None and schedule_exception.type == ScheduleExceptionType.CLOSED:
        return CalendarDay(date=day, is_closed=True, slots=[])

    # Build raw [start_local, end_local, price_override?] tuples.
    raw: list[tuple[datetime, datetime, int | None]] = []

    if schedule_exception is not None and schedule_exception.type == ScheduleExceptionType.WINDOWS:
        duration_min = schedule_exception.slot_duration_min or venue.slot_duration_min
        for w_start, w_end, price_override in _windows_from_exception(schedule_exception):
            cur = datetime.combine(day, w_start, tzinfo=tz)
            stop = datetime.combine(day, w_end, tzinfo=tz)
            while cur + timedelta(minutes=duration_min) <= stop:
                raw.append((cur, cur + timedelta(minutes=duration_min), price_override))
                cur += timedelta(minutes=duration_min)
    else:
        # Default grid: venue.open_hour..venue.close_hour, slot_duration_min step.
        duration_min = venue.slot_duration_min
        open_dt = datetime.combine(day, time(hour=venue.open_hour), tzinfo=tz)
        # close_hour may exceed 24 (next-day overflow) — cap at 24:00 today for
        # MVP; cross-midnight shifts handled in Phase 7+ if needed.
        close_h = min(venue.close_hour, 24)
        if close_h == 24:
            close_dt = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
        else:
            close_dt = datetime.combine(day, time(hour=close_h), tzinfo=tz)
        cur = open_dt
        while cur + timedelta(minutes=duration_min) <= close_dt:
            raw.append((cur, cur + timedelta(minutes=duration_min), None))
            cur += timedelta(minutes=duration_min)

    # Convert overrides + booked into UTC ranges for overlap testing.
    override_ranges = [(_utc(o.slot_start_at), _utc(o.slot_end_at)) for o in slot_overrides]
    booked_ranges = [(_utc(b.slot_start_at), _utc(b.slot_end_at)) for b in booked_slots]

    # Materialize each slot with its status + price.
    pricing_rule_list = list(pricing_rules)
    out_slots: list[CalendarSlot] = []

    for start_local, end_local, price_override in raw:
        start_utc = _utc(start_local)
        end_utc = _utc(end_local)

        # Status precedence: past > booked > blocked > available.
        if end_utc <= now:
            status: SlotStatus = "past"
        elif any(_ranges_overlap(start_utc, end_utc, bs, be) for bs, be in booked_ranges):
            status = "booked"
        elif any(_ranges_overlap(start_utc, end_utc, os, oe) for os, oe in override_ranges):
            status = "blocked"
        elif start_utc < cutoff:
            status = "past"  # too late to book; surface as past for the UI
        else:
            status = "available"

        # Price: explicit window override wins, else pricing rules, else venue base.
        if price_override is not None:
            price = price_override
        else:
            local_start = _local(start_utc, venue)
            resolved = resolve_price(
                venue=venue,
                rules=pricing_rule_list,
                day=local_start.date(),
                hour=local_start.hour,
            )
            price = resolved.price_bdt

        out_slots.append(
            CalendarSlot(start_at=start_utc, end_at=end_utc, status=status, price_bdt=price)
        )

    return CalendarDay(date=day, is_closed=False, slots=out_slots)


def daterange_inclusive(start: date, end: date) -> list[date]:
    if end < start:
        return []
    days = (end - start).days
    return [start + timedelta(days=i) for i in range(days + 1)]
