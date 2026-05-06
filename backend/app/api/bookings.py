"""Booking lifecycle endpoints (Phase 4: hold + status + cancel-hold).

Phase 6 wires this into bKash payment; Phase 7 adds cash-on-arrival; Phase 9
adds customer-initiated cancellation with refund + re-OTP. For now the only
state transitions exposed are: create-hold, read-status, cancel-hold-while-pending.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.enums import BookingStatus, UserRole
from app.models import Booking, BookingSlot
from app.redis_client import get_redis
from app.security.deps import CurrentUser
from app.services.bookings import (
    HoldError,
    HoldSlotInput,
    expire_hold,
    hold_slots,
    reconcile_expired_holds,
)

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


class HoldResponse(BaseModel):
    booking_id: int
    public_id: str
    hold_token: str
    hold_expires_at: datetime
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
            discount_code=body.discount_code,
        )
    except HoldError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

    return HoldResponse(
        booking_id=result.booking_id,
        public_id=result.public_id,
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
    # Lazy reconciliation: sweep expired pending holds before reading state.
    # This is a small write on the read path but keeps the system honest in
    # the absence of a dedicated worker.
    await reconcile_expired_holds(db, redis)

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
