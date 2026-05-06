"""Booking lifecycle endpoints (Phase 4: hold + status + cancel-hold).

Phase 6 wires this into bKash payment; Phase 7 adds cash-on-arrival; Phase 9
adds customer-initiated cancellation with refund + re-OTP. For now the only
state transitions exposed are: create-hold, read-status, cancel-hold-while-pending.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import FirebaseVerifierDep
from app.db import get_db
from app.enums import BookingStatus, PaymentCollection, UserRole
from app.models import Booking, BookingSlot, Venue
from app.redis_client import get_redis
from app.security.deps import CurrentUser, StaffOrAdmin
from app.security.firebase import FirebaseAuthError
from app.services.bookings import (
    HoldError,
    HoldSlotInput,
    expire_hold,
    hold_slots,
    mark_cash_paid,
    reconcile_expired_holds,
    reconcile_unpaid_cash_bookings,
)
from app.services.cancellation import (
    BookingNotCancellableError,
    CancellationError,
    cancel_booking,
    compute_refund,
)
from app.services.receipts import render_receipt_pdf

router = APIRouter(prefix="/bookings", tags=["bookings"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]

MAX_SLOTS_PER_HOLD = 24


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class HoldSlotIn(BaseModel):
    start_at: datetime


class HoldRequest(BaseModel):
    venue_id: int
    slots: list[HoldSlotIn] = Field(..., min_length=1, max_length=MAX_SLOTS_PER_HOLD)
    discount_code: str | None = Field(default=None, max_length=64)
    payment_method: Literal["online", "cash"] = "online"


class HoldResponse(BaseModel):
    booking_id: int
    public_id: str
    payment_method: str
    hold_token: str | None
    hold_expires_at: datetime | None
    subtotal_bdt: int
    discount_code: str | None
    discount_amount_bdt: int
    total_bdt: int
    slot_count: int


class BookingSlotOut(BaseModel):
    slot_start_at: datetime
    slot_end_at: datetime
    price_bdt: int


class BookingStatusResponse(BaseModel):
    booking_id: int
    public_id: str
    status: BookingStatus
    payment_collection: PaymentCollection
    venue_id: int
    total_bdt: int
    subtotal_bdt: int
    discount_amount_bdt: int
    admin_adjustment_bdt: int
    slot_count: int
    first_slot_at: datetime
    last_slot_at: datetime
    hold_expires_at: datetime | None
    seconds_to_expiry: int | None
    slots: list[BookingSlotOut]
    created_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_booking_for_user(db: AsyncSession, *, booking_id: int, user: object) -> Booking:
    booking = (
        await db.execute(select(Booking).where(Booking.id == booking_id))
    ).scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=404, detail="booking_not_found")

    is_admin = getattr(user, "role", None) == UserRole.ADMIN
    is_staff = getattr(user, "role", None) == UserRole.STAFF
    if not (booking.user_id == getattr(user, "id", None) or is_admin or is_staff):
        raise HTTPException(status_code=404, detail="booking_not_found")
    return booking


async def _to_status_response(
    db: AsyncSession, booking: Booking, *, now: datetime
) -> BookingStatusResponse:
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
    seconds_to_expiry: int | None = None
    if booking.hold_expires_at is not None:
        delta = (booking.hold_expires_at - now).total_seconds()
        seconds_to_expiry = max(0, int(delta))

    return BookingStatusResponse(
        booking_id=booking.id,
        public_id=booking.public_id,
        status=booking.status,
        payment_collection=booking.payment_collection,
        venue_id=booking.venue_id,
        total_bdt=booking.total_amount_bdt,
        subtotal_bdt=booking.subtotal_bdt,
        discount_amount_bdt=booking.discount_amount_bdt,
        admin_adjustment_bdt=booking.admin_adjustment_bdt,
        slot_count=booking.slot_count,
        first_slot_at=booking.first_slot_at,
        last_slot_at=booking.last_slot_at,
        hold_expires_at=booking.hold_expires_at,
        seconds_to_expiry=seconds_to_expiry,
        slots=[
            BookingSlotOut(
                slot_start_at=s.slot_start_at,
                slot_end_at=s.slot_end_at,
                price_bdt=s.price_bdt,
            )
            for s in slot_rows
        ],
        created_at=booking.created_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/hold", response_model=HoldResponse, status_code=status.HTTP_201_CREATED)
async def create_hold(
    body: HoldRequest, user: CurrentUser, db: DbDep, redis: RedisDep
) -> HoldResponse:
    if body.slots is None or len(body.slots) == 0:
        raise HTTPException(status_code=400, detail="no_slots_requested")

    inputs = [HoldSlotInput(start_at=s.start_at) for s in body.slots]
    try:
        result = await hold_slots(
            db,
            redis,
            user=user,
            venue_id=body.venue_id,
            slot_inputs=inputs,
            payment_method=body.payment_method,
            discount_code=body.discount_code,
        )
    except HoldError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

    return HoldResponse(
        booking_id=result.booking_id,
        public_id=result.public_id,
        payment_method=result.payment_method,
        hold_token=result.hold_token,
        hold_expires_at=result.hold_expires_at,
        subtotal_bdt=result.subtotal_bdt,
        discount_code=result.discount_code,
        discount_amount_bdt=result.discount_amount_bdt,
        total_bdt=result.total_bdt,
        slot_count=result.slot_count,
    )


@router.get("/{booking_id}/status", response_model=BookingStatusResponse)
async def read_status(
    booking_id: int, user: CurrentUser, db: DbDep, redis: RedisDep
) -> BookingStatusResponse:
    # Lazy reconciliation: sweep expired pending holds + unpaid cash bookings
    # before reading state. Keeps an idle deployment honest without a worker.
    await reconcile_expired_holds(db, redis)
    await reconcile_unpaid_cash_bookings(db)

    booking = await _load_booking_for_user(db, booking_id=booking_id, user=user)
    return await _to_status_response(db, booking, now=datetime.now(UTC))


@router.post("/{booking_id}/cancel-hold", response_model=BookingStatusResponse)
async def cancel_hold(
    booking_id: int, user: CurrentUser, db: DbDep, redis: RedisDep
) -> BookingStatusResponse:
    booking = await _load_booking_for_user(db, booking_id=booking_id, user=user)
    if booking.status != BookingStatus.PENDING_PAYMENT:
        raise HTTPException(status_code=409, detail="booking_not_pending")

    await expire_hold(db, redis, booking=booking, reason="cancelled")
    await db.refresh(booking)
    return await _to_status_response(db, booking, now=datetime.now(UTC))


# ---------------------------------------------------------------------------
# Admin: cash payment recording
# ---------------------------------------------------------------------------


@router.post(
    "/{booking_id}/mark-cash-paid",
    response_model=BookingStatusResponse,
    tags=["admin"],
)
async def mark_cash_paid_endpoint(
    booking_id: int,
    actor: StaffOrAdmin,
    db: DbDep,
) -> BookingStatusResponse:
    """Staff or admin records receipt of cash for an in-person booking.

    Idempotent: re-calling on a booking already marked paid returns 200 with
    the same payment row referenced.
    """
    booking = (
        await db.execute(select(Booking).where(Booking.id == booking_id))
    ).scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=404, detail="booking_not_found")

    try:
        await mark_cash_paid(db, booking=booking, actor=actor)
    except HoldError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

    await db.refresh(booking)
    return await _to_status_response(db, booking, now=datetime.now(UTC))


# ---------------------------------------------------------------------------
# PDF receipt download
# ---------------------------------------------------------------------------


@router.get("/{booking_id}/receipt.pdf", response_class=Response)
async def download_receipt(
    booking_id: int, request: Request, user: CurrentUser, db: DbDep
) -> Response:
    """Generate + stream the booking receipt as a PDF.

    Auth: owner or admin/staff (via _load_booking_for_user).
    """
    booking = await _load_booking_for_user(db, booking_id=booking_id, user=user)

    base_url = str(request.base_url).rstrip("/")
    pdf = await render_receipt_pdf(db, booking=booking, base_url=base_url)

    headers = {
        "Content-Disposition": f'attachment; filename="Receipt-{booking.public_id}.pdf"',
        "Cache-Control": "private, max-age=300",
    }
    return Response(content=pdf, media_type="application/pdf", headers=headers)


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


# Re-OTP freshness window: the customer must complete Firebase phone
# re-verification within this many seconds of triggering cancel.
REAUTH_MAX_AGE_SECONDS = 5 * 60


class CancelPreviewResponse(BaseModel):
    refund_amount_bdt: int
    eligible_slot_count: int
    total_slot_count: int
    full_refund_hours: int
    requires_reauth: bool
    refund_will_be_required: bool


class CancelConfirmRequest(BaseModel):
    firebase_id_token: str = Field(..., min_length=20)


class CancelConfirmResponse(BaseModel):
    booking_id: int
    new_status: BookingStatus
    refund_amount_bdt: int
    refund_id: int | None
    refund_required: bool


async def _venue_for(db: AsyncSession, venue_id: int) -> Venue:
    venue = (await db.execute(select(Venue).where(Venue.id == venue_id))).scalar_one_or_none()
    if venue is None:  # pragma: no cover - FK should make this impossible
        raise HTTPException(status_code=404, detail="venue_not_found")
    return venue


@router.get(
    "/{booking_id}/cancel-preview",
    response_model=CancelPreviewResponse,
)
async def preview_cancellation(
    booking_id: int, user: CurrentUser, db: DbDep
) -> CancelPreviewResponse:
    """Show the refund the customer would get if they cancel right now.

    Used by the UI before triggering the re-OTP flow so the user can decide
    informed. Always available to the booking owner; admins/staff also.
    """
    booking = await _load_booking_for_user(db, booking_id=booking_id, user=user)
    if booking.status not in (BookingStatus.PENDING_PAYMENT, BookingStatus.CONFIRMED):
        raise HTTPException(status_code=409, detail="booking_not_cancellable")

    venue = await _venue_for(db, booking.venue_id)
    slot_rows = (
        (await db.execute(select(BookingSlot).where(BookingSlot.booking_id == booking.id)))
        .scalars()
        .all()
    )
    preview = compute_refund(
        booking=booking,
        slot_rows=slot_rows,
        full_refund_hours=venue.cancellation_full_refund_hours,
    )

    # A customer cancelling a confirmed booking that they paid for in cash
    # needs to step through the re-OTP gate. Pending bookings (no payment
    # yet) skip it — there's no money at risk.
    has_paid_cash = booking.payment_collection == PaymentCollection.CASH
    requires_reauth = (
        user.role == UserRole.CUSTOMER
        and booking.status == BookingStatus.CONFIRMED
        and has_paid_cash
        and preview.refund_amount_bdt > 0
    )

    return CancelPreviewResponse(
        refund_amount_bdt=preview.refund_amount_bdt,
        eligible_slot_count=preview.eligible_slot_count,
        total_slot_count=preview.total_slot_count,
        full_refund_hours=preview.full_refund_hours,
        requires_reauth=requires_reauth,
        refund_will_be_required=requires_reauth,
    )


@router.post(
    "/{booking_id}/cancel",
    response_model=CancelConfirmResponse,
)
async def confirm_cancellation(
    booking_id: int,
    body: CancelConfirmRequest | None,
    user: CurrentUser,
    verifier: FirebaseVerifierDep,
    db: DbDep,
) -> CancelConfirmResponse:
    """Confirm cancellation. Re-OTP is required only when the customer is
    cancelling a paid confirmed booking; the UI gates this via the preview.
    """
    booking = await _load_booking_for_user(db, booking_id=booking_id, user=user)
    venue = await _venue_for(db, booking.venue_id)

    is_admin = user.role in (UserRole.ADMIN, UserRole.STAFF)
    needs_reauth = (
        not is_admin
        and booking.status == BookingStatus.CONFIRMED
        and booking.payment_collection == PaymentCollection.CASH
    )

    if needs_reauth:
        if body is None or not body.firebase_id_token:
            raise HTTPException(status_code=401, detail="reauth_required")
        try:
            decoded = verifier(body.firebase_id_token)
        except FirebaseAuthError as e:
            raise HTTPException(status_code=401, detail=f"firebase_{e}") from e

        # Token must be issued for the same phone and within the freshness window.
        if decoded.get("phone_number") != user.phone:
            raise HTTPException(status_code=401, detail="reauth_phone_mismatch")
        iat = decoded.get("iat") or decoded.get("auth_time") or 0
        age = datetime.now(UTC).timestamp() - float(iat)
        if age > REAUTH_MAX_AGE_SECONDS:
            raise HTTPException(status_code=401, detail="reauth_stale")

    try:
        result = await cancel_booking(
            db,
            booking=booking,
            user=user,
            venue_full_refund_hours=venue.cancellation_full_refund_hours,
            initiator="admin" if is_admin else "customer",
        )
    except BookingNotCancellableError as e:
        raise HTTPException(status_code=e.status_code, detail=e.code) from e
    except CancellationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.code) from e

    return CancelConfirmResponse(
        booking_id=result.booking_id,
        new_status=result.new_status,
        refund_amount_bdt=booking.refund_amount_bdt,
        refund_id=result.refund_id,
        refund_required=result.refund_required,
    )
