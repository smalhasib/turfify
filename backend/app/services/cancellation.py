"""Customer + admin booking cancellation with per-slot refund computation.

Refund tier (binary, configurable per venue via cancellation_full_refund_hours):
  - More than `cancellation_full_refund_hours` before slot start → 100% refund
  - Within the window → 0% refund

Per-slot evaluation: each slot is judged against its own start time and the
booking-level refund is the sum across slots.

Cash flavor (Phase 8): bKash provider is deferred. Refund types here:
  - manual: admin physically returns cash at the venue (or via personal bKash)
  - none: no payment was collected (e.g., cash_pending unpaid before slot)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import (
    BookingStatus,
    PaymentCollection,
    PaymentStatus,
    RefundProvider,
    RefundStatus,
)
from app.logging_config import get_logger
from app.models import Booking, BookingSlot, Payment, Refund, User
from app.services.discounts import void_for_booking as void_discount_for_booking

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CancellationError(Exception):
    code: str = "cancellation_error"
    status_code: int = 400

    def __init__(self, code: str | None = None) -> None:
        super().__init__(code or self.code)
        self.code = code or self.code


class BookingNotCancellableError(CancellationError):
    code = "booking_not_cancellable"
    status_code = 409


class StaleReauthError(CancellationError):
    code = "stale_reauth"
    status_code = 401


# ---------------------------------------------------------------------------
# Refund preview (pure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RefundPreview:
    refund_amount_bdt: int
    eligible_slot_count: int
    total_slot_count: int
    full_refund_hours: int


def compute_refund(
    *,
    booking: Booking,
    slot_rows: Sequence[BookingSlot],
    full_refund_hours: int,
    now: datetime | None = None,
) -> RefundPreview:
    """Per-slot refund: each slot >`full_refund_hours` before start gets full
    price back; everything closer is forfeit. Total is the sum.

    For unpaid bookings the tier still informs the user how much *would* be
    refunded if they had paid; the API may zero it out.
    """
    if now is None:
        now = datetime.now(UTC)

    total = 0
    eligible = 0
    for s in slot_rows:
        delta = s.slot_start_at - now
        hours_until = delta.total_seconds() / 3600.0
        if hours_until > full_refund_hours:
            total += s.price_bdt
            eligible += 1

    return RefundPreview(
        refund_amount_bdt=total,
        eligible_slot_count=eligible,
        total_slot_count=len(slot_rows),
        full_refund_hours=full_refund_hours,
    )


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


CancelReason = Literal["customer", "admin"]


@dataclass(frozen=True)
class CancellationResult:
    booking_id: int
    new_status: BookingStatus
    refund_preview: RefundPreview
    refund_id: int | None
    refund_required: bool


# Statuses that customers/admins can cancel from. Terminal states are skipped.
_CANCELLABLE_STATUSES = (
    BookingStatus.PENDING_PAYMENT,
    BookingStatus.CONFIRMED,
)


async def _completed_payments(db: AsyncSession, booking_id: int) -> list[Payment]:
    rows = (
        (
            await db.execute(
                select(Payment).where(
                    Payment.booking_id == booking_id,
                    Payment.status == PaymentStatus.COMPLETED,
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def cancel_booking(
    db: AsyncSession,
    *,
    booking: Booking,
    user: User,
    venue_full_refund_hours: int,
    initiator: CancelReason = "customer",
    admin_grace_full_refund: bool = False,
    now: datetime | None = None,
) -> CancellationResult:
    """Move a booking to `cancelled` and (where applicable) raise a refund row.

    `admin_grace_full_refund=True` overrides the tier and refunds everything
    (used by admins for goodwill / system-fault cases).

    Refund mechanics for cash flavor:
      - If the booking has a completed cash payment, raise a Refund row with
        provider=manual, status=pending. Admin physically returns cash at the
        venue and confirms via the admin-refund endpoint (Phase 9+).
      - If unpaid (cash_pending), no refund row is needed: status flips to
        cancelled, slot clears via the trigger.

    Returns metadata including the refund id (if any).
    """
    if booking.status not in _CANCELLABLE_STATUSES:
        raise BookingNotCancellableError()
    if now is None:
        now = datetime.now(UTC)

    slot_rows = (
        (
            await db.execute(
                select(BookingSlot)
                .where(BookingSlot.booking_id == booking.id)
                .order_by(BookingSlot.slot_start_at)
            )
        )
        .scalars()
        .all()
    )

    preview = compute_refund(
        booking=booking,
        slot_rows=slot_rows,
        full_refund_hours=venue_full_refund_hours,
        now=now,
    )

    # Compute the refund amount we'll actually attempt to disburse.
    # For unpaid bookings (no completed payment), there's nothing to refund.
    payments = await _completed_payments(db, booking.id)
    has_paid = len(payments) > 0
    final_amount = (
        preview.refund_amount_bdt if not admin_grace_full_refund else booking.total_amount_bdt
    )
    refund_required = has_paid and final_amount > 0

    # Mark the booking cancelled.
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = now
    booking.refund_amount_bdt = final_amount if refund_required else 0
    booking.cancellation_reason = "admin_cancel" if initiator == "admin" else "customer_cancel"

    # Void discount redemptions so the user can reuse the code.
    await void_discount_for_booking(db, booking_id=booking.id)

    refund_id: int | None = None
    if refund_required:
        # Cash flavor: provider=manual; admin must mark refund completed
        # after physically returning the cash. bKash provider arrives later.
        first_payment = payments[0]
        refund = Refund(
            payment_id=first_payment.id,
            amount_bdt=final_amount,
            reason=f"{initiator}_cancel",
            provider=RefundProvider.MANUAL,
            status=RefundStatus.PENDING,
            requested_by=user.id,
        )
        db.add(refund)
        await db.flush()
        refund_id = refund.id

    await db.commit()

    logger.info(
        "booking.cancelled",
        booking_id=booking.id,
        public_id=booking.public_id,
        initiator=initiator,
        refund_amount_bdt=booking.refund_amount_bdt,
        refund_id=refund_id,
    )

    return CancellationResult(
        booking_id=booking.id,
        new_status=BookingStatus.CANCELLED,
        refund_preview=preview,
        refund_id=refund_id,
        refund_required=refund_required,
    )


async def admin_complete_refund(
    db: AsyncSession,
    *,
    refund: Refund,
    actor: User,
    provider_refund_id: str | None = None,
    now: datetime | None = None,
) -> Refund:
    """Admin marks a manual refund as physically completed (cash returned)."""
    if refund.status != RefundStatus.PENDING:
        raise CancellationError("refund_not_pending")
    if now is None:
        now = datetime.now(UTC)

    refund.status = RefundStatus.COMPLETED
    refund.completed_at = now
    if provider_refund_id:
        refund.provider_refund_id = provider_refund_id

    # Advance booking status to refunded for the customer-facing log.
    booking = (
        await db.execute(
            select(Booking)
            .join(Payment, Payment.id == refund.payment_id)
            .where(Payment.id == refund.payment_id)
        )
    ).scalar_one()
    booking.status = BookingStatus.REFUNDED

    await db.commit()
    logger.info(
        "refund.completed",
        refund_id=refund.id,
        booking_id=booking.id,
        actor_id=actor.id,
    )
    return refund


# Suppress unused-import warning for an enum re-exported in tests later.
_ = PaymentCollection
