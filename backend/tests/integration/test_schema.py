"""Integration tests for Phase 1 schema.

Verifies:
- Basic CRUD across each table.
- GIST exclusion constraint blocks overlapping booking_slots.
- The constraint correctly ignores non-active booking statuses.
- FK cascade from bookings to booking_slots.
- Unique constraints (phone, code, public_id, exception_per_date).
- Trigger keeps booking_slots.booking_status in sync with bookings.status.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    BookingSource,
    BookingStatus,
    DiscountType,
    PaymentCollection,
    ScheduleExceptionType,
    UserRole,
)
from app.models import (
    Booking,
    BookingSlot,
    DiscountCode,
    PricingRule,
    ScheduleException,
    User,
    Venue,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_venue(db: AsyncSession, *, name: str = "Test Venue") -> Venue:
    venue = Venue(name=name)
    db.add(venue)
    await db.flush()
    return venue


async def _make_user(db: AsyncSession, *, phone: str, role: UserRole = UserRole.CUSTOMER) -> User:
    user = User(phone=phone, role=role)
    db.add(user)
    await db.flush()
    return user


def _slot_window(
    *, days_from_now: int = 1, hour: int = 16, length_hours: int = 1
) -> tuple[datetime, datetime]:
    base = (datetime.now(UTC) + timedelta(days=days_from_now)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return base, base + timedelta(hours=length_hours)


async def _make_booking(
    db: AsyncSession,
    *,
    user: User,
    venue: Venue,
    public_id: str,
    status: BookingStatus = BookingStatus.PENDING_PAYMENT,
    days_from_now: int = 1,
    hour: int = 16,
    slot_count: int = 1,
) -> Booking:
    start, end = _slot_window(days_from_now=days_from_now, hour=hour)
    booking = Booking(
        public_id=public_id,
        user_id=user.id,
        venue_id=venue.id,
        booking_source=BookingSource.WEB,
        payment_collection=PaymentCollection.ONLINE,
        subtotal_bdt=1000 * slot_count,
        total_amount_bdt=1000 * slot_count,
        slot_count=slot_count,
        first_slot_at=start,
        last_slot_at=end + timedelta(hours=slot_count - 1),
        status=status,
    )
    db.add(booking)
    await db.flush()
    return booking


async def _make_booking_slot(
    db: AsyncSession,
    *,
    booking: Booking,
    venue: Venue,
    start: datetime,
    end: datetime,
    booking_status: BookingStatus | None = None,
) -> BookingSlot:
    slot = BookingSlot(
        booking_id=booking.id,
        venue_id=venue.id,
        slot_start_at=start,
        slot_end_at=end,
        price_bdt=1000,
        booking_status=booking_status or booking.status,
    )
    db.add(slot)
    await db.flush()
    return slot


# ---------------------------------------------------------------------------
# CRUD smoke
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_create_venue_and_user(db_session: AsyncSession) -> None:
    venue = await _make_venue(db_session, name="Smoke Venue")
    user = await _make_user(db_session, phone="+8801711111111")
    await db_session.commit()

    refreshed = (await db_session.execute(select(Venue).where(Venue.id == venue.id))).scalar_one()
    assert refreshed.name == "Smoke Venue"
    assert refreshed.is_active is True
    assert refreshed.timezone == "Asia/Dhaka"

    user_row = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    assert user_row.role == UserRole.CUSTOMER
    assert user_row.no_show_count == 0


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_pricing_rule_check_constraints(db_session: AsyncSession) -> None:
    venue = await _make_venue(db_session)
    rule = PricingRule(
        venue_id=venue.id, name="Weekend evening", hour_start=18, hour_end=22, price_bdt=1500
    )
    db_session.add(rule)
    await db_session.commit()

    # hour_end <= hour_start should fail
    bad = PricingRule(venue_id=venue.id, name="bad", hour_start=18, hour_end=18, price_bdt=100)
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_discount_code_percent_constraint(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    bad = DiscountCode(
        code="OVER100",
        type=DiscountType.PERCENT,
        value=120,  # > 100 for percent
        valid_from=now,
        valid_until=now + timedelta(days=7),
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    ok = DiscountCode(
        code="GOOD20",
        type=DiscountType.PERCENT,
        value=20,
        valid_from=now,
        valid_until=now + timedelta(days=7),
    )
    db_session.add(ok)
    await db_session.commit()


# ---------------------------------------------------------------------------
# Unique constraints
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_user_phone_unique(db_session: AsyncSession) -> None:
    await _make_user(db_session, phone="+8801712222222")
    await db_session.commit()

    dup = User(phone="+8801712222222")
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_schedule_exception_unique_per_date(db_session: AsyncSession) -> None:
    venue = await _make_venue(db_session)
    target = date.today() + timedelta(days=10)
    db_session.add(
        ScheduleException(
            venue_id=venue.id, exception_date=target, type=ScheduleExceptionType.CLOSED
        )
    )
    await db_session.commit()

    dup = ScheduleException(
        venue_id=venue.id,
        exception_date=target,
        type=ScheduleExceptionType.WINDOWS,
        windows=[{"start": "09:00", "end": "11:00"}],
    )
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# GIST exclusion: overlapping bookings must be rejected
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_gist_blocks_overlapping_active_bookings(db_session: AsyncSession) -> None:
    venue = await _make_venue(db_session)
    user_a = await _make_user(db_session, phone="+8801713333333")
    user_b = await _make_user(db_session, phone="+8801714444444")

    booking_a = await _make_booking(db_session, user=user_a, venue=venue, public_id="TRF-A")
    start, end = _slot_window(hour=16)
    await _make_booking_slot(db_session, booking=booking_a, venue=venue, start=start, end=end)
    await db_session.commit()

    # Booking B targets exact same slot — GIST exclusion must block on flush.
    booking_b = await _make_booking(db_session, user=user_b, venue=venue, public_id="TRF-B")
    with pytest.raises(IntegrityError) as ei:
        await _make_booking_slot(db_session, booking=booking_b, venue=venue, start=start, end=end)
    assert "ex_booking_slot_no_overlap" in str(ei.value)
    await db_session.rollback()


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_gist_blocks_partial_overlap(db_session: AsyncSession) -> None:
    venue = await _make_venue(db_session)
    user_a = await _make_user(db_session, phone="+8801715555555")
    user_b = await _make_user(db_session, phone="+8801716666666")

    booking_a = await _make_booking(db_session, user=user_a, venue=venue, public_id="TRF-PA")
    start_a, end_a = _slot_window(hour=16, length_hours=2)  # 16:00-18:00
    await _make_booking_slot(db_session, booking=booking_a, venue=venue, start=start_a, end=end_a)
    await db_session.commit()

    # Booking B 17:00-19:00 partially overlaps — must be blocked.
    booking_b = await _make_booking(db_session, user=user_b, venue=venue, public_id="TRF-PB")
    start_b, end_b = _slot_window(hour=17, length_hours=2)
    with pytest.raises(IntegrityError):
        await _make_booking_slot(
            db_session, booking=booking_b, venue=venue, start=start_b, end=end_b
        )
    await db_session.rollback()


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_gist_allows_back_to_back_no_gap(db_session: AsyncSession) -> None:
    """tstzrange '[)' means [start, end) — back-to-back slots do NOT overlap."""
    venue = await _make_venue(db_session)
    user = await _make_user(db_session, phone="+8801717777777")
    booking = await _make_booking(
        db_session, user=user, venue=venue, public_id="TRF-BB", slot_count=2
    )

    start1, end1 = _slot_window(hour=16)  # 16:00-17:00
    start2, end2 = _slot_window(hour=17)  # 17:00-18:00

    await _make_booking_slot(db_session, booking=booking, venue=venue, start=start1, end=end1)
    await _make_booking_slot(db_session, booking=booking, venue=venue, start=start2, end=end2)
    await db_session.commit()  # should NOT raise


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_gist_ignores_terminal_status_slots(db_session: AsyncSession) -> None:
    """A booking_slot with status=cancelled should NOT block a new active slot."""
    venue = await _make_venue(db_session)
    user_a = await _make_user(db_session, phone="+8801718888888")
    user_b = await _make_user(db_session, phone="+8801719999999")

    cancelled_booking = await _make_booking(
        db_session,
        user=user_a,
        venue=venue,
        public_id="TRF-CANCEL",
        status=BookingStatus.CANCELLED,
    )
    start, end = _slot_window(hour=16)
    # Insert booking_slot tagged cancelled (matches booking status).
    await _make_booking_slot(
        db_session,
        booking=cancelled_booking,
        venue=venue,
        start=start,
        end=end,
        booking_status=BookingStatus.CANCELLED,
    )
    await db_session.commit()

    # A new active booking on the same slot must succeed (cancelled slot ignored).
    new_booking = await _make_booking(db_session, user=user_b, venue=venue, public_id="TRF-NEW")
    await _make_booking_slot(db_session, booking=new_booking, venue=venue, start=start, end=end)
    await db_session.commit()  # should NOT raise


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_gist_isolates_per_venue(db_session: AsyncSession) -> None:
    """Same time slot at two different venues should both succeed."""
    venue_a = await _make_venue(db_session, name="Venue A")
    venue_b = await _make_venue(db_session, name="Venue B")
    user = await _make_user(db_session, phone="+8801731010101")

    booking_a = await _make_booking(db_session, user=user, venue=venue_a, public_id="TRF-VA")
    booking_b = await _make_booking(db_session, user=user, venue=venue_b, public_id="TRF-VB")

    start, end = _slot_window(hour=16)
    await _make_booking_slot(db_session, booking=booking_a, venue=venue_a, start=start, end=end)
    await _make_booking_slot(db_session, booking=booking_b, venue=venue_b, start=start, end=end)
    await db_session.commit()  # should NOT raise — different venue_id


# ---------------------------------------------------------------------------
# FK cascade
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_booking_delete_cascades_to_slots(db_session: AsyncSession) -> None:
    venue = await _make_venue(db_session)
    user = await _make_user(db_session, phone="+8801732020202")
    booking = await _make_booking(db_session, user=user, venue=venue, public_id="TRF-CASC")
    start, end = _slot_window(hour=16)
    await _make_booking_slot(db_session, booking=booking, venue=venue, start=start, end=end)
    await db_session.commit()

    await db_session.execute(text("DELETE FROM bookings WHERE id = :id"), {"id": booking.id})
    await db_session.commit()

    remaining = (
        await db_session.execute(select(BookingSlot).where(BookingSlot.booking_id == booking.id))
    ).all()
    assert remaining == []


# ---------------------------------------------------------------------------
# Trigger: bookings.status -> booking_slots.booking_status
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_status_sync_trigger(db_session: AsyncSession) -> None:
    venue = await _make_venue(db_session)
    user = await _make_user(db_session, phone="+8801733030303")
    booking = await _make_booking(db_session, user=user, venue=venue, public_id="TRF-TRIG")
    start, end = _slot_window(hour=16)
    slot = await _make_booking_slot(db_session, booking=booking, venue=venue, start=start, end=end)
    await db_session.commit()
    assert slot.booking_status == BookingStatus.PENDING_PAYMENT

    slot_id = slot.id
    # Update booking status — trigger should mirror to booking_slots.
    await db_session.execute(
        text("UPDATE bookings SET status = 'confirmed' WHERE id = :id"),
        {"id": booking.id},
    )
    await db_session.commit()

    # Bypass identity map: read raw value via SQL.
    result = await db_session.execute(
        text("SELECT booking_status FROM booking_slots WHERE id = :id"),
        {"id": slot_id},
    )
    row_status = result.scalar_one()
    assert row_status == BookingStatus.CONFIRMED.value
