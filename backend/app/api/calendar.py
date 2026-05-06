"""Calendar / slot grid endpoint.

`GET /v1/venues/{id}/calendar?from=YYYY-MM-DD&to=YYYY-MM-DD`

Returns N days of slot grids with computed status (available / booked / blocked
/ past) and per-slot price. Public (no auth) — slot availability needs to be
visible before sign-in to convince users to book.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.enums import BookingStatus
from app.models import (
    BookingSlot,
    PricingRule,
    ScheduleException,
    SlotOverride,
    Venue,
)
from app.services.slots import (
    CalendarDay,
    CalendarSlot,
    daterange_inclusive,
    slots_for_day,
)

router = APIRouter(tags=["calendar"])

DbDep = Annotated[AsyncSession, Depends(get_db)]

# Hard cap: even if venue.advance_book_days is huge, never return more than this
# many days in one request.
MAX_DAYS_PER_REQUEST = 31


class CalendarSlotOut(BaseModel):
    start_at: datetime
    end_at: datetime
    status: str
    price_bdt: int


class CalendarDayOut(BaseModel):
    date: date
    is_closed: bool
    slots: list[CalendarSlotOut]


class CalendarOut(BaseModel):
    venue_id: int
    venue_name: str
    timezone: str
    days: list[CalendarDayOut]


def _to_out_slot(s: CalendarSlot) -> CalendarSlotOut:
    return CalendarSlotOut(
        start_at=s.start_at,
        end_at=s.end_at,
        status=s.status,
        price_bdt=s.price_bdt,
    )


def _to_out_day(d: CalendarDay) -> CalendarDayOut:
    return CalendarDayOut(
        date=d.date,
        is_closed=d.is_closed,
        slots=[_to_out_slot(s) for s in d.slots],
    )


@router.get("/venues/{venue_id}/calendar", response_model=CalendarOut)
async def get_calendar(
    venue_id: int,
    db: DbDep,
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
) -> CalendarOut:
    if date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from_must_be_before_to",
        )

    span = (date_to - date_from).days + 1
    if span > MAX_DAYS_PER_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"date_range_exceeds_{MAX_DAYS_PER_REQUEST}_days",
        )

    venue = (
        await db.execute(select(Venue).where(Venue.id == venue_id, Venue.is_active.is_(True)))
    ).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="venue_not_found")

    today = datetime.now(UTC).date()
    max_advance = today + timedelta(days=venue.advance_book_days)
    if date_to > max_advance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"to_exceeds_advance_window_{venue.advance_book_days}_days",
        )

    days = daterange_inclusive(date_from, date_to)
    if not days:
        return CalendarOut(
            venue_id=venue.id,
            venue_name=venue.name,
            timezone=venue.timezone,
            days=[],
        )

    pricing_rules = (
        (
            await db.execute(
                select(PricingRule).where(
                    PricingRule.venue_id == venue_id,
                    PricingRule.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )

    exceptions_by_date = {
        e.exception_date: e
        for e in (
            (
                await db.execute(
                    select(ScheduleException).where(
                        ScheduleException.venue_id == venue_id,
                        ScheduleException.exception_date >= date_from,
                        ScheduleException.exception_date <= date_to,
                    )
                )
            )
            .scalars()
            .all()
        )
    }

    # Bound the time range so we only fetch overrides + bookings overlapping the
    # requested span. Use UTC bounds wide enough to catch any timezone shifts.
    range_start = datetime.combine(date_from - timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    range_end = datetime.combine(date_to + timedelta(days=2), datetime.min.time(), tzinfo=UTC)

    slot_overrides = (
        (
            await db.execute(
                select(SlotOverride).where(
                    SlotOverride.venue_id == venue_id,
                    SlotOverride.slot_end_at > range_start,
                    SlotOverride.slot_start_at < range_end,
                )
            )
        )
        .scalars()
        .all()
    )

    booked_slots = (
        (
            await db.execute(
                select(BookingSlot).where(
                    and_(
                        BookingSlot.venue_id == venue_id,
                        BookingSlot.slot_end_at > range_start,
                        BookingSlot.slot_start_at < range_end,
                        or_(
                            BookingSlot.booking_status == BookingStatus.PENDING_PAYMENT,
                            BookingSlot.booking_status == BookingStatus.CONFIRMED,
                        ),
                    )
                )
            )
        )
        .scalars()
        .all()
    )

    now = datetime.now(UTC)
    days_out: list[CalendarDayOut] = []
    for day in days:
        cal_day = slots_for_day(
            venue=venue,
            day=day,
            pricing_rules=pricing_rules,
            schedule_exception=exceptions_by_date.get(day),
            slot_overrides=slot_overrides,
            booked_slots=booked_slots,
            now=now,
        )
        days_out.append(_to_out_day(cal_day))

    return CalendarOut(
        venue_id=venue.id,
        venue_name=venue.name,
        timezone=venue.timezone,
        days=days_out,
    )
