"""Booking hold flow.

This service brings together the slot generator, the Redis lock, and the
Postgres GIST exclusion to materialize a hold:

  1. Validate every requested slot:
     - Falls within the venue's grid for the day (open hours / windows).
     - Not blocked, not already booked, not past, not before the cutoff.
     - Within the advance-book window.
  2. Acquire all slot locks atomically in Redis (Lua all-or-nothing).
  3. Insert the `Booking` and its `BookingSlot` rows in one DB transaction.
     The GIST exclusion constraint is the second line of defense: if Redis
     state is lost, Postgres still refuses overlapping bookings.
  4. On any failure after step 2, release the Redis locks before raising.

The reverse path (`expire_hold`) is exposed for explicit cancellation and for
the lazy-reconciliation cron in `reconcile_expired_holds`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import BookingSource, BookingStatus, PaymentCollection
from app.logging_config import get_logger
from app.models import (
    Booking,
    BookingSlot,
    PricingRule,
    ScheduleException,
    SlotOverride,
    User,
    Venue,
)
from app.services.locks import (
    SlotLockConflictError,
    acquire_slot_locks,
    generate_hold_token,
    hold_ttl_seconds,
    release_slot_locks,
)
from app.services.slots import slots_for_day

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HoldError(Exception):
    """Base class for hold-flow domain errors that map to 4xx responses."""

    code: str = "hold_error"
    status_code: int = 400

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)


class VenueNotFoundError(HoldError):
    code = "venue_not_found"
    status_code = 404


class NoSlotsRequestedError(HoldError):
    code = "no_slots_requested"


class SlotsCrossVenueError(HoldError):
    code = "slots_must_belong_to_one_venue"


class SlotNotAvailableError(HoldError):
    code = "slot_not_available"


class SlotLockConflictHoldError(HoldError):
    code = "slot_lock_conflict"
    status_code = 409


# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HoldSlotInput:
    """One slot the client is asking to hold."""

    start_at: datetime  # tz-aware UTC


@dataclass(frozen=True)
class HoldResult:
    booking_id: int
    public_id: str
    hold_token: str
    hold_expires_at: datetime
    total_bdt: int
    slot_count: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _format_public_id(year: int, sequence: int) -> str:
    """`TRF-2026-000123` style identifier visible to users + on receipts."""
    return f"TRF-{year}-{sequence:06d}"


async def hold_slots(
    db: AsyncSession,
    redis: Redis,
    *,
    user: User,
    venue_id: int,
    slot_inputs: Sequence[HoldSlotInput],
    now: datetime | None = None,
) -> HoldResult:
    """Lock + persist a multi-slot hold for `user`.

    See module docstring for the full sequence. Atomic w.r.t. concurrent calls
    by the same user OR another user targeting overlapping slots.
    """
    if not slot_inputs:
        raise NoSlotsRequestedError()
    if now is None:
        now = datetime.now(UTC)

    venue = (
        await db.execute(select(Venue).where(Venue.id == venue_id, Venue.is_active.is_(True)))
    ).scalar_one_or_none()
    if venue is None:
        raise VenueNotFoundError()

    # Normalize and dedupe slot starts.
    slot_starts = sorted({s.start_at.astimezone(UTC) for s in slot_inputs})
    if any(s.tzinfo is None for s in (i.start_at for i in slot_inputs)):
        raise HoldError("slot_starts_must_be_timezone_aware")

    # Group by venue-local date so we generate the day grid once per date.
    from zoneinfo import ZoneInfo

    venue_tz = ZoneInfo(venue.timezone)
    dates_needed = sorted({s.astimezone(venue_tz).date() for s in slot_starts})

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

    range_start = datetime.combine(
        dates_needed[0] - timedelta(days=1), datetime.min.time(), tzinfo=UTC
    )
    range_end = datetime.combine(
        dates_needed[-1] + timedelta(days=2), datetime.min.time(), tzinfo=UTC
    )

    exceptions_by_date = {
        e.exception_date: e
        for e in (
            (
                await db.execute(
                    select(ScheduleException).where(
                        ScheduleException.venue_id == venue_id,
                        ScheduleException.exception_date >= dates_needed[0],
                        ScheduleException.exception_date <= dates_needed[-1],
                    )
                )
            )
            .scalars()
            .all()
        )
    }
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

    # Resolve every requested slot against the generated grid.
    matched: list[tuple[datetime, datetime, int]] = []  # (start_utc, end_utc, price)
    requested_set = set(slot_starts)
    for day in dates_needed:
        cal_day = slots_for_day(
            venue=venue,
            day=day,
            pricing_rules=pricing_rules,
            schedule_exception=exceptions_by_date.get(day),
            slot_overrides=slot_overrides,
            booked_slots=booked_slots,
            now=now,
        )
        for s in cal_day.slots:
            if s.start_at not in requested_set:
                continue
            if s.status != "available":
                raise SlotNotAvailableError(f"slot {s.start_at.isoformat()} is {s.status}")
            matched.append((s.start_at, s.end_at, s.price_bdt))

    if len(matched) != len(requested_set):
        # At least one requested slot did not appear in the venue grid.
        raise SlotNotAvailableError("requested_slot_outside_grid")

    matched.sort(key=lambda m: m[0])

    # Acquire Redis locks atomically.
    hold_token = generate_hold_token()
    ttl = hold_ttl_seconds()
    starts = [m[0] for m in matched]
    try:
        await acquire_slot_locks(
            redis,
            venue_id=venue_id,
            slot_starts=starts,
            hold_token=hold_token,
            ttl_seconds=ttl,
        )
    except SlotLockConflictError as e:
        raise SlotLockConflictHoldError() from e

    # Persist Booking + BookingSlot rows. GIST is the safety net.
    try:
        subtotal = sum(price for _, _, price in matched)
        first_start, _, _ = matched[0]
        _, last_end, _ = matched[-1]

        booking = Booking(
            public_id="TRF-PENDING",  # placeholder; rewritten after id is known
            user_id=user.id,
            venue_id=venue_id,
            booking_source=BookingSource.WEB,
            payment_collection=PaymentCollection.ONLINE,
            subtotal_bdt=subtotal,
            total_amount_bdt=subtotal,
            slot_count=len(matched),
            first_slot_at=first_start,
            last_slot_at=last_end,
            status=BookingStatus.PENDING_PAYMENT,
            hold_token=hold_token,
            hold_expires_at=now + timedelta(seconds=ttl),
        )
        db.add(booking)
        await db.flush()  # populates booking.id

        booking.public_id = _format_public_id(now.year, booking.id)

        for start_at, end_at, price in matched:
            db.add(
                BookingSlot(
                    booking_id=booking.id,
                    venue_id=venue_id,
                    slot_start_at=start_at,
                    slot_end_at=end_at,
                    price_bdt=price,
                    booking_status=BookingStatus.PENDING_PAYMENT,
                )
            )

        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        await release_slot_locks(
            redis, venue_id=venue_id, slot_starts=starts, hold_token=hold_token
        )
        # GIST exclusion message is the recognizable signature.
        if "ex_booking_slot_no_overlap" in str(e):
            raise SlotLockConflictHoldError() from e
        raise
    except Exception:
        await db.rollback()
        await release_slot_locks(
            redis, venue_id=venue_id, slot_starts=starts, hold_token=hold_token
        )
        raise

    logger.info(
        "booking.hold.created",
        booking_id=booking.id,
        public_id=booking.public_id,
        user_id=user.id,
        venue_id=venue_id,
        slot_count=len(matched),
        total_bdt=subtotal,
        ttl_seconds=ttl,
    )

    expires = booking.hold_expires_at
    assert expires is not None  # always set above on the new booking
    return HoldResult(
        booking_id=booking.id,
        public_id=booking.public_id,
        hold_token=hold_token,
        hold_expires_at=expires,
        total_bdt=subtotal,
        slot_count=len(matched),
    )


async def expire_hold(
    db: AsyncSession,
    redis: Redis,
    *,
    booking: Booking,
    reason: str = "expired",
) -> None:
    """Move a `pending_payment` booking to `expired` (or `cancelled`) and
    release its Redis locks. Idempotent: terminal-state bookings are no-ops.
    """
    if booking.status != BookingStatus.PENDING_PAYMENT:
        return

    target = BookingStatus.CANCELLED if reason == "cancelled" else BookingStatus.EXPIRED

    booking.status = target
    if booking.hold_token:
        slots = (
            (
                await db.execute(
                    select(BookingSlot.slot_start_at).where(BookingSlot.booking_id == booking.id)
                )
            )
            .scalars()
            .all()
        )
        await release_slot_locks(
            redis,
            venue_id=booking.venue_id,
            slot_starts=slots,
            hold_token=booking.hold_token,
        )
    await db.commit()
    logger.info(
        "booking.hold.expired",
        booking_id=booking.id,
        public_id=booking.public_id,
        new_status=target.value,
        reason=reason,
    )


async def reconcile_expired_holds(
    db: AsyncSession,
    redis: Redis,
    *,
    now: datetime | None = None,
) -> int:
    """Sweep `pending_payment` bookings whose `hold_expires_at` has passed and
    transition them to `expired`. Returns count expired.

    Called lazily on every status read so an idle deployment still cleans up
    after itself even without a separate cron worker. Phase 6 will swap to a
    Dramatiq scheduled job once the worker container is in place.
    """
    if now is None:
        now = datetime.now(UTC)

    expired_bookings = (
        (
            await db.execute(
                select(Booking).where(
                    Booking.status == BookingStatus.PENDING_PAYMENT,
                    Booking.hold_expires_at.isnot(None),
                    Booking.hold_expires_at <= now,
                )
            )
        )
        .scalars()
        .all()
    )

    count = 0
    for b in expired_bookings:
        await expire_hold(db, redis, booking=b, reason="expired")
        count += 1
    return count


async def count_pending_for_year(db: AsyncSession, year: int) -> int:
    """Diagnostic helper: bookings created in `year`."""
    return int(
        (
            await db.execute(
                select(func.count(Booking.id)).where(
                    func.extract("year", Booking.created_at) == year
                )
            )
        ).scalar_one()
    )
