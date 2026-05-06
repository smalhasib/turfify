"""Admin-flow booking creation.

Phase 9: admins/staff create bookings on behalf of customers (walk-ins,
phone-in regulars, comp slots). Differs from the customer hold flow:
  - No Redis 8-min hold (booking commits straight to its target state).
  - Customer can be looked up by phone, quick-created (no Firebase OTP),
    or self (admin's own user_id).
  - Per-slot price override + booking-level adjustment supported.
  - Cutoff override allowed (walk-in 5 minutes before kickoff).
  - All payment_collection modes available (cash, bkash_manual, free,
    pending_offline, online).

GIST exclusion still guards against double-booking — slot_inputs go through
the same generated grid + insert path.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    BookingSource,
    BookingStatus,
    PaymentCollection,
    PaymentProvider,
    PaymentStatus,
    UserRole,
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
from app.services.bookings import HoldError, _format_public_id
from app.services.slots import slots_for_day

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AdminBookingError(HoldError):
    pass


class CustomerNotFoundError(AdminBookingError):
    code = "customer_not_found"
    status_code = 404


class InvalidPaymentCollectionError(AdminBookingError):
    code = "invalid_payment_collection"


class FreeReasonRequiredError(AdminBookingError):
    code = "free_reason_required"


class SlotMismatchError(AdminBookingError):
    code = "slot_outside_grid"


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdminSlotOverride:
    start_at: datetime
    price_bdt: int | None = None  # None → use grid-resolved price


@dataclass(frozen=True)
class AdminBookingInput:
    venue_id: int
    slot_overrides: Sequence[AdminSlotOverride]
    payment_collection: PaymentCollection
    customer_user_id: int | None = None  # one of (id | quick_create | self)
    quick_create_phone: str | None = None
    quick_create_name: str | None = None
    book_for_self: bool = False
    admin_adjustment_bdt: int = 0
    admin_adjustment_reason: str | None = None
    free_reason: str | None = None
    cutoff_override: bool = False
    manual_trx_id: str | None = None  # for bkash_manual


@dataclass(frozen=True)
class AdminBookingResult:
    booking_id: int
    public_id: str
    status: BookingStatus
    payment_collection: PaymentCollection
    subtotal_bdt: int
    total_bdt: int
    payment_id: int | None
    user_id: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def _resolve_customer(
    db: AsyncSession,
    *,
    actor: User,
    body: AdminBookingInput,
) -> User:
    if body.book_for_self:
        return actor
    if body.customer_user_id is not None:
        user = (
            await db.execute(select(User).where(User.id == body.customer_user_id))
        ).scalar_one_or_none()
        if user is None or user.deleted_at is not None:
            raise CustomerNotFoundError()
        return user

    phone = (body.quick_create_phone or "").strip()
    if not phone:
        raise CustomerNotFoundError()
    existing = (await db.execute(select(User).where(User.phone == phone))).scalar_one_or_none()
    if existing is not None:
        return existing

    new_user = User(
        phone=phone,
        name=body.quick_create_name,
        role=UserRole.CUSTOMER,
        manually_created=True,
        created_by_admin_id=actor.id,
    )
    db.add(new_user)
    await db.flush()
    return new_user


async def admin_create_booking(
    db: AsyncSession,
    *,
    actor: User,
    body: AdminBookingInput,
    now: datetime | None = None,
) -> AdminBookingResult:
    """Persist an admin-created booking. See module docstring for behavior."""
    if not body.slot_overrides:
        raise HoldError("no_slots_requested")
    if body.payment_collection == PaymentCollection.FREE and not body.free_reason:
        raise FreeReasonRequiredError()
    if now is None:
        now = datetime.now(UTC)

    customer = await _resolve_customer(db, actor=actor, body=body)

    venue = (
        await db.execute(select(Venue).where(Venue.id == body.venue_id, Venue.is_active.is_(True)))
    ).scalar_one_or_none()
    if venue is None:
        raise HoldError("venue_not_found")

    # Generate the slot grid for each requested date and match by start_at.
    slot_starts = sorted({s.start_at.astimezone(UTC) for s in body.slot_overrides})
    venue_tz = ZoneInfo(venue.timezone)
    dates_needed = sorted({s.astimezone(venue_tz).date() for s in slot_starts})

    pricing_rules = (
        (
            await db.execute(
                select(PricingRule).where(
                    PricingRule.venue_id == body.venue_id,
                    PricingRule.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )

    from datetime import timedelta

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
                        ScheduleException.venue_id == body.venue_id,
                        ScheduleException.exception_date >= dates_needed[0],
                        ScheduleException.exception_date <= dates_needed[-1],
                    )
                )
            )
            .scalars()
            .all()
        )
    }
    overrides = (
        (
            await db.execute(
                select(SlotOverride).where(
                    SlotOverride.venue_id == body.venue_id,
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
                        BookingSlot.venue_id == body.venue_id,
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

    # Build a lookup of grid slots so we can match overrides by start.
    grid_by_start: dict[datetime, tuple[datetime, datetime, int, str]] = {}
    for day in dates_needed:
        cal = slots_for_day(
            venue=venue,
            day=day,
            pricing_rules=pricing_rules,
            schedule_exception=exceptions_by_date.get(day),
            slot_overrides=overrides,
            booked_slots=booked_slots,
            now=now,
        )
        for s in cal.slots:
            grid_by_start[s.start_at] = (s.start_at, s.end_at, s.price_bdt, s.status)

    matched: list[tuple[datetime, datetime, int, bool]] = []  # start, end, price, overridden
    for override in body.slot_overrides:
        start_utc = override.start_at.astimezone(UTC)
        grid = grid_by_start.get(start_utc)
        if grid is None:
            raise SlotMismatchError(f"slot {start_utc.isoformat()} not in grid")

        gstart, gend, gprice, gstatus = grid
        # Admin-only relaxations: cutoff_override permits past/imminent slots.
        if gstatus == "blocked":
            raise HoldError(f"slot {start_utc.isoformat()} is blocked")
        if gstatus == "booked":
            raise HoldError(f"slot {start_utc.isoformat()} is booked")
        if gstatus == "past" and not body.cutoff_override:
            raise HoldError(f"slot {start_utc.isoformat()} is past (use cutoff_override)")

        price = override.price_bdt if override.price_bdt is not None else gprice
        overridden = override.price_bdt is not None and override.price_bdt != gprice
        matched.append((gstart, gend, price, overridden))

    matched.sort(key=lambda m: m[0])
    subtotal = sum(p for _, _, p, _ in matched)
    total = max(0, subtotal + body.admin_adjustment_bdt)

    # Decide booking status from payment_collection.
    if body.payment_collection == PaymentCollection.FREE:
        booking_status = BookingStatus.CONFIRMED
        payment_status = None
    elif body.payment_collection in (
        PaymentCollection.CASH,
        PaymentCollection.BKASH_MANUAL,
    ):
        booking_status = BookingStatus.CONFIRMED
        payment_status = PaymentStatus.COMPLETED
    elif body.payment_collection in (
        PaymentCollection.CASH_PENDING,
        PaymentCollection.PENDING_OFFLINE,
    ):
        booking_status = BookingStatus.CONFIRMED
        payment_status = None
    elif body.payment_collection == PaymentCollection.ONLINE:
        booking_status = BookingStatus.PENDING_PAYMENT
        payment_status = None
    else:  # pragma: no cover - guarded by enum at API layer
        raise InvalidPaymentCollectionError()

    first_start = matched[0][0]
    last_end = matched[-1][1]

    booking = Booking(
        public_id="TRF-PENDING",
        user_id=customer.id,
        venue_id=body.venue_id,
        booking_source=BookingSource.ADMIN,
        created_by_admin_id=actor.id,
        payment_collection=body.payment_collection,
        subtotal_bdt=subtotal,
        admin_adjustment_bdt=body.admin_adjustment_bdt,
        admin_adjustment_reason=body.admin_adjustment_reason,
        total_amount_bdt=total,
        slot_count=len(matched),
        first_slot_at=first_start,
        last_slot_at=last_end,
        status=booking_status,
        cutoff_override=body.cutoff_override,
        free_reason=body.free_reason,
    )
    db.add(booking)

    try:
        await db.flush()
        booking.public_id = _format_public_id(now.year, booking.id)

        for start_at, end_at, price, overridden in matched:
            db.add(
                BookingSlot(
                    booking_id=booking.id,
                    venue_id=body.venue_id,
                    slot_start_at=start_at,
                    slot_end_at=end_at,
                    price_bdt=price,
                    price_overridden=overridden,
                    booking_status=booking_status,
                )
            )

        payment_id: int | None = None
        if (
            payment_status == PaymentStatus.COMPLETED
            and body.payment_collection != PaymentCollection.FREE
        ):
            provider = (
                PaymentProvider.CASH
                if body.payment_collection == PaymentCollection.CASH
                else PaymentProvider.BKASH_MANUAL
            )
            payment = Payment(
                booking_id=booking.id,
                provider=provider,
                manual_trx_id=body.manual_trx_id,
                collected_by_admin_id=actor.id,
                amount_bdt=total,
                status=PaymentStatus.COMPLETED,
                completed_at=now,
            )
            db.add(payment)
            await db.flush()
            payment_id = payment.id

        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        if "ex_booking_slot_no_overlap" in str(e):
            raise HoldError("slot_lock_conflict") from e
        raise

    logger.info(
        "booking.admin.created",
        booking_id=booking.id,
        public_id=booking.public_id,
        actor_id=actor.id,
        customer_id=customer.id,
        venue_id=body.venue_id,
        slot_count=len(matched),
        total_bdt=total,
        payment_collection=body.payment_collection.value,
    )

    return AdminBookingResult(
        booking_id=booking.id,
        public_id=booking.public_id,
        status=booking_status,
        payment_collection=body.payment_collection,
        subtotal_bdt=subtotal,
        total_bdt=total,
        payment_id=payment_id,
        user_id=customer.id,
    )
