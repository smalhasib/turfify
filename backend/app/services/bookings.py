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
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    BookingSource,
    BookingStatus,
    PaymentCollection,
    PaymentProvider,
    PaymentStatus,
)
from app.logging_config import get_logger
from app.models import (
    Booking,
    BookingSlot,
    Payment,
    PricingRule,
    ScheduleException,
    SlotOverride,
    User,
    Venue,
)
from app.services.discounts import (
    DiscountInvalidError,
)
from app.services.discounts import (
    redeem as redeem_discount,
)
from app.services.discounts import (
    validate_code as validate_discount_code,
)
from app.services.discounts import (
    void_for_booking as void_discount_for_booking,
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


class DiscountRejectedError(HoldError):
    """Wraps DiscountInvalidError so the hold flow can return a uniform 400."""

    code = "discount_rejected"
    status_code = 400


class CashDisabledError(HoldError):
    """Customer is blacklisted from cash bookings after repeated no-shows."""

    code = "cash_disabled_for_user"
    status_code = 403


class UnsupportedPaymentMethodError(HoldError):
    """Phase 6 only ships cash; bKash slot reserved for the next phase."""

    code = "unsupported_payment_method"
    status_code = 400


# Threshold of auto-cancelled cash bookings before the user is blacklisted from
# placing more cash holds. Keep in code, not env, to make the rule legible.
NO_SHOW_BLACKLIST_THRESHOLD: int = 3


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
    payment_method: str  # "online" (Phase 7+) | "cash"
    hold_token: str | None  # populated only for online holds
    hold_expires_at: datetime | None
    subtotal_bdt: int
    discount_code: str | None
    discount_amount_bdt: int
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
    payment_method: str = "online",
    discount_code: str | None = None,
    now: datetime | None = None,
) -> HoldResult:
    """Lock + persist a multi-slot hold for `user`.

    `payment_method` controls the lifecycle:
      - "online" (Phase 7+ bKash): booking starts in pending_payment, Redis
        holds the slots for 8 minutes while the user pays.
      - "cash": booking is committed straight to confirmed with
        payment_collection=cash_pending. No Redis hold; the GIST exclusion
        constraint guards the slot. The auto-cancel cron transitions
        unpaid cash bookings shortly before the slot starts.
    """
    if payment_method not in ("online", "cash"):
        raise UnsupportedPaymentMethodError()
    if payment_method == "cash" and user.cash_disabled:
        raise CashDisabledError()
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

    starts = [m[0] for m in matched]
    is_online = payment_method == "online"

    # Online holds use Redis as a UX-layer 8-min hold; cash bookings skip the
    # lock since the slot commits straight to confirmed and GIST guards it.
    hold_token: str | None = generate_hold_token() if is_online else None
    ttl = hold_ttl_seconds() if is_online else 0
    if is_online:
        assert hold_token is not None  # narrowing for type checker
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

        # Resolve discount BEFORE booking insert so we fail fast on a bad code
        # without polluting Postgres with a doomed-to-rollback row.
        discount_resolution = None
        discount_code_id: int | None = None
        discount_amount_bdt = 0
        if discount_code:
            try:
                slot_dates = [s.astimezone(ZoneInfo(venue.timezone)).date() for s, _, _ in matched]
                discount_resolution = await validate_discount_code(
                    db,
                    code=discount_code,
                    user=user,
                    subtotal_bdt=subtotal,
                    slot_dates=slot_dates,
                    now=now,
                )
                discount_code_id = discount_resolution.discount.id
                discount_amount_bdt = discount_resolution.amount_off_bdt
            except DiscountInvalidError as exc:
                if is_online and hold_token is not None:
                    await release_slot_locks(
                        redis, venue_id=venue_id, slot_starts=starts, hold_token=hold_token
                    )
                raise DiscountRejectedError(exc.code) from exc

        total_bdt = max(0, subtotal - discount_amount_bdt)

        booking_status = BookingStatus.PENDING_PAYMENT if is_online else BookingStatus.CONFIRMED
        collection = PaymentCollection.ONLINE if is_online else PaymentCollection.CASH_PENDING

        booking = Booking(
            public_id="TRF-PENDING",  # placeholder; rewritten after id is known
            user_id=user.id,
            venue_id=venue_id,
            booking_source=BookingSource.WEB,
            payment_collection=collection,
            subtotal_bdt=subtotal,
            discount_code_id=discount_code_id,
            discount_amount_bdt=discount_amount_bdt,
            total_amount_bdt=total_bdt,
            slot_count=len(matched),
            first_slot_at=first_start,
            last_slot_at=last_end,
            status=booking_status,
            hold_token=hold_token,
            hold_expires_at=(now + timedelta(seconds=ttl)) if is_online else None,
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
                    booking_status=booking_status,
                )
            )

        if discount_resolution is not None:
            await redeem_discount(
                db,
                discount=discount_resolution.discount,
                booking_id=booking.id,
                user=user,
                amount_off_bdt=discount_amount_bdt,
            )

        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        if is_online and hold_token is not None:
            await release_slot_locks(
                redis, venue_id=venue_id, slot_starts=starts, hold_token=hold_token
            )
        # GIST exclusion message is the recognizable signature.
        if "ex_booking_slot_no_overlap" in str(e):
            raise SlotLockConflictHoldError() from e
        raise
    except Exception:
        await db.rollback()
        if is_online and hold_token is not None:
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
        subtotal_bdt=subtotal,
        discount_code=discount_code,
        discount_amount_bdt=discount_amount_bdt,
        total_bdt=total_bdt,
        ttl_seconds=ttl,
    )

    return HoldResult(
        booking_id=booking.id,
        public_id=booking.public_id,
        payment_method=payment_method,
        hold_token=hold_token,
        hold_expires_at=booking.hold_expires_at,
        subtotal_bdt=subtotal,
        discount_code=discount_code,
        discount_amount_bdt=discount_amount_bdt,
        total_bdt=total_bdt,
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

    # Void any redemptions tied to this booking so the user can retry the
    # code without burning a usage count.
    await void_discount_for_booking(db, booking_id=booking.id)

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


async def mark_cash_paid(
    db: AsyncSession,
    *,
    booking: Booking,
    actor: User,
    now: datetime | None = None,
) -> Payment:
    """Admin/staff records a cash payment for an in-person booking.

    Inserts a `payments` row (provider=cash, status=completed) and clears the
    cash_pending flag by switching `payment_collection` to CASH. Idempotent:
    if a successful cash payment already exists, returns it without creating
    a duplicate.
    """
    if booking.payment_collection not in (
        PaymentCollection.CASH_PENDING,
        PaymentCollection.CASH,
    ):
        raise HoldError("booking_not_cash")
    if booking.status not in (BookingStatus.CONFIRMED, BookingStatus.COMPLETED):
        raise HoldError("booking_not_payable")

    if now is None:
        now = datetime.now(UTC)

    # Idempotency: surface the existing completed payment if any.
    existing = (
        (
            await db.execute(
                select(Payment).where(
                    Payment.booking_id == booking.id,
                    Payment.provider == PaymentProvider.CASH,
                    Payment.status == PaymentStatus.COMPLETED,
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return existing

    payment = Payment(
        booking_id=booking.id,
        provider=PaymentProvider.CASH,
        amount_bdt=booking.total_amount_bdt,
        status=PaymentStatus.COMPLETED,
        collected_by_admin_id=actor.id,
        completed_at=now,
    )
    db.add(payment)
    booking.payment_collection = PaymentCollection.CASH
    await db.commit()
    logger.info(
        "booking.cash.marked_paid",
        booking_id=booking.id,
        public_id=booking.public_id,
        actor_id=actor.id,
    )
    return payment


async def reconcile_unpaid_cash_bookings(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Auto-cancel cash bookings approaching their first slot without payment.

    A booking is auto-cancelled when:
      - status is `confirmed`
      - payment_collection is `cash_pending`
      - `now() + venue.cash_cancel_minutes_before` is past first_slot_at

    Each auto-cancellation increments the user's `no_show_count` and toggles
    `cash_disabled=true` once the threshold is crossed. Returns the number of
    bookings transitioned.
    """
    if now is None:
        now = datetime.now(UTC)

    rows = (
        await db.execute(
            select(Booking, Venue)
            .join(Venue, Venue.id == Booking.venue_id)
            .where(
                Booking.status == BookingStatus.CONFIRMED,
                Booking.payment_collection == PaymentCollection.CASH_PENDING,
            )
        )
    ).all()

    count = 0
    for booking, venue in rows:
        deadline = booking.first_slot_at - timedelta(minutes=venue.cash_cancel_minutes_before)
        if now < deadline:
            continue

        booking.status = BookingStatus.AUTO_CANCELLED_NO_PAYMENT
        booking.cancelled_at = now
        booking.cancellation_reason = "cash_not_received_before_slot"

        # Bump the user's no-show counter and auto-blacklist on threshold.
        user = (
            await db.execute(select(User).where(User.id == booking.user_id))
        ).scalar_one_or_none()
        if user is not None:
            user.no_show_count += 1
            if user.no_show_count >= NO_SHOW_BLACKLIST_THRESHOLD:
                user.cash_disabled = True

        await void_discount_for_booking(db, booking_id=booking.id)
        await db.commit()

        logger.info(
            "booking.cash.auto_cancelled",
            booking_id=booking.id,
            public_id=booking.public_id,
            user_id=booking.user_id,
            no_show_count=getattr(user, "no_show_count", None),
            cash_disabled=getattr(user, "cash_disabled", None),
        )
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
