"""Admin-gated endpoints: bookings creation, schedule_exceptions, slot_overrides,
manual refund completion. All routes require admin role unless otherwise noted.

Customer + staff manage-paid sit on bookings router (already shipped).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.enums import (
    BookingStatus,
    PaymentCollection,
    RefundStatus,
    ScheduleExceptionType,
    SlotOverrideReason,
)
from app.models import (
    Booking,
    Refund,
    ScheduleException,
    SlotOverride,
)
from app.security.deps import AdminUser, StaffOrAdmin
from app.services.admin_bookings import (
    AdminBookingInput,
    AdminSlotOverride,
    admin_create_booking,
)
from app.services.bookings import HoldError
from app.services.cancellation import admin_complete_refund

router = APIRouter(prefix="/admin", tags=["admin"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Admin booking creation
# ---------------------------------------------------------------------------


class AdminSlotIn(BaseModel):
    start_at: datetime
    price_bdt: int | None = Field(default=None, ge=0)


class AdminBookingCreateRequest(BaseModel):
    venue_id: int
    slots: list[AdminSlotIn] = Field(..., min_length=1, max_length=24)
    payment_collection: PaymentCollection
    customer_user_id: int | None = None
    quick_create_phone: str | None = Field(default=None, max_length=20)
    quick_create_name: str | None = Field(default=None, max_length=200)
    book_for_self: bool = False
    admin_adjustment_bdt: int = Field(default=0)
    admin_adjustment_reason: str | None = Field(default=None, max_length=500)
    free_reason: str | None = Field(default=None, max_length=500)
    cutoff_override: bool = False
    manual_trx_id: str | None = Field(default=None, max_length=128)


class AdminBookingCreateResponse(BaseModel):
    booking_id: int
    public_id: str
    status: BookingStatus
    payment_collection: PaymentCollection
    subtotal_bdt: int
    total_bdt: int
    payment_id: int | None
    user_id: int


@router.post(
    "/bookings",
    response_model=AdminBookingCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_booking(
    body: AdminBookingCreateRequest, actor: StaffOrAdmin, db: DbDep
) -> AdminBookingCreateResponse:
    inputs = AdminBookingInput(
        venue_id=body.venue_id,
        slot_overrides=[
            AdminSlotOverride(start_at=s.start_at, price_bdt=s.price_bdt) for s in body.slots
        ],
        payment_collection=body.payment_collection,
        customer_user_id=body.customer_user_id,
        quick_create_phone=body.quick_create_phone,
        quick_create_name=body.quick_create_name,
        book_for_self=body.book_for_self,
        admin_adjustment_bdt=body.admin_adjustment_bdt,
        admin_adjustment_reason=body.admin_adjustment_reason,
        free_reason=body.free_reason,
        cutoff_override=body.cutoff_override,
        manual_trx_id=body.manual_trx_id,
    )
    try:
        result = await admin_create_booking(db, actor=actor, body=inputs)
    except HoldError as e:
        # Subclasses (AdminBookingError, etc.) inherit from HoldError so this
        # catch handles every domain failure with the right status + detail.
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

    return AdminBookingCreateResponse(
        booking_id=result.booking_id,
        public_id=result.public_id,
        status=result.status,
        payment_collection=result.payment_collection,
        subtotal_bdt=result.subtotal_bdt,
        total_bdt=result.total_bdt,
        payment_id=result.payment_id,
        user_id=result.user_id,
    )


# ---------------------------------------------------------------------------
# Schedule exceptions CRUD
# ---------------------------------------------------------------------------


class ScheduleExceptionIn(BaseModel):
    venue_id: int
    exception_date: datetime  # auto-narrowed to date by FastAPI
    type: ScheduleExceptionType
    windows: list[dict[str, Any]] | None = None
    slot_duration_min: int | None = None
    reason: str | None = None
    note: str | None = None


class ScheduleExceptionOut(BaseModel):
    id: int
    venue_id: int
    exception_date: str
    type: ScheduleExceptionType
    windows: list[dict[str, Any]] | None
    slot_duration_min: int | None
    reason: str | None
    note: str | None


def _exc_to_out(e: ScheduleException) -> ScheduleExceptionOut:
    return ScheduleExceptionOut(
        id=e.id,
        venue_id=e.venue_id,
        exception_date=e.exception_date.isoformat(),
        type=e.type,
        windows=e.windows,
        slot_duration_min=e.slot_duration_min,
        reason=e.reason,
        note=e.note,
    )


@router.post(
    "/schedule-exceptions",
    response_model=ScheduleExceptionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule_exception(
    body: ScheduleExceptionIn, actor: AdminUser, db: DbDep
) -> ScheduleExceptionOut:
    existing = (
        await db.execute(
            select(ScheduleException).where(
                ScheduleException.venue_id == body.venue_id,
                ScheduleException.exception_date == body.exception_date.date(),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="exception_already_exists")

    if body.type == ScheduleExceptionType.WINDOWS and not body.windows:
        raise HTTPException(status_code=400, detail="windows_required_for_windows_type")

    exc = ScheduleException(
        venue_id=body.venue_id,
        exception_date=body.exception_date.date(),
        type=body.type,
        windows=body.windows,
        slot_duration_min=body.slot_duration_min,
        reason=body.reason,
        note=body.note,
        created_by=actor.id,
    )
    db.add(exc)
    await db.commit()
    return _exc_to_out(exc)


@router.get(
    "/venues/{venue_id}/schedule-exceptions",
    response_model=list[ScheduleExceptionOut],
)
async def list_schedule_exceptions(
    venue_id: int, _actor: AdminUser, db: DbDep
) -> list[ScheduleExceptionOut]:
    rows = (
        (
            await db.execute(
                select(ScheduleException)
                .where(ScheduleException.venue_id == venue_id)
                .order_by(ScheduleException.exception_date)
            )
        )
        .scalars()
        .all()
    )
    return [_exc_to_out(e) for e in rows]


@router.delete("/schedule-exceptions/{exception_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule_exception(exception_id: int, _actor: AdminUser, db: DbDep) -> None:
    exc = (
        await db.execute(select(ScheduleException).where(ScheduleException.id == exception_id))
    ).scalar_one_or_none()
    if exc is None:
        raise HTTPException(status_code=404, detail="exception_not_found")
    await db.delete(exc)
    await db.commit()


# ---------------------------------------------------------------------------
# Slot overrides CRUD
# ---------------------------------------------------------------------------


class SlotOverrideIn(BaseModel):
    venue_id: int
    slot_start_at: datetime
    slot_end_at: datetime
    reason: SlotOverrideReason
    note: str | None = None


class SlotOverrideOut(BaseModel):
    id: int
    venue_id: int
    slot_start_at: datetime
    slot_end_at: datetime
    reason: SlotOverrideReason
    note: str | None


@router.post(
    "/slot-overrides",
    response_model=SlotOverrideOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_slot_override(
    body: SlotOverrideIn, actor: AdminUser, db: DbDep
) -> SlotOverrideOut:
    if body.slot_end_at <= body.slot_start_at:
        raise HTTPException(status_code=400, detail="invalid_range")
    so = SlotOverride(
        venue_id=body.venue_id,
        slot_start_at=body.slot_start_at,
        slot_end_at=body.slot_end_at,
        reason=body.reason,
        note=body.note,
        created_by=actor.id,
    )
    db.add(so)
    await db.commit()
    return SlotOverrideOut(
        id=so.id,
        venue_id=so.venue_id,
        slot_start_at=so.slot_start_at,
        slot_end_at=so.slot_end_at,
        reason=so.reason,
        note=so.note,
    )


@router.get("/venues/{venue_id}/slot-overrides", response_model=list[SlotOverrideOut])
async def list_slot_overrides(venue_id: int, _actor: AdminUser, db: DbDep) -> list[SlotOverrideOut]:
    rows = (
        (
            await db.execute(
                select(SlotOverride)
                .where(SlotOverride.venue_id == venue_id)
                .order_by(desc(SlotOverride.slot_start_at))
            )
        )
        .scalars()
        .all()
    )
    return [
        SlotOverrideOut(
            id=r.id,
            venue_id=r.venue_id,
            slot_start_at=r.slot_start_at,
            slot_end_at=r.slot_end_at,
            reason=r.reason,
            note=r.note,
        )
        for r in rows
    ]


@router.delete("/slot-overrides/{override_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_slot_override(override_id: int, _actor: AdminUser, db: DbDep) -> None:
    so = (
        await db.execute(select(SlotOverride).where(SlotOverride.id == override_id))
    ).scalar_one_or_none()
    if so is None:
        raise HTTPException(status_code=404, detail="override_not_found")
    await db.delete(so)
    await db.commit()


# ---------------------------------------------------------------------------
# Manual refund completion
# ---------------------------------------------------------------------------


class CompleteRefundRequest(BaseModel):
    provider_refund_id: str | None = Field(default=None, max_length=128)


class RefundOut(BaseModel):
    id: int
    payment_id: int
    amount_bdt: int
    reason: str | None
    provider: str
    status: RefundStatus
    completed_at: datetime | None


@router.post("/refunds/{refund_id}/complete", response_model=RefundOut)
async def complete_refund(
    refund_id: int,
    body: CompleteRefundRequest,
    actor: AdminUser,
    db: DbDep,
) -> RefundOut:
    refund = (await db.execute(select(Refund).where(Refund.id == refund_id))).scalar_one_or_none()
    if refund is None:
        raise HTTPException(status_code=404, detail="refund_not_found")

    try:
        await admin_complete_refund(
            db,
            refund=refund,
            actor=actor,
            provider_refund_id=body.provider_refund_id,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return RefundOut(
        id=refund.id,
        payment_id=refund.payment_id,
        amount_bdt=refund.amount_bdt,
        reason=refund.reason,
        provider=refund.provider.value,
        status=refund.status,
        completed_at=refund.completed_at,
    )


@router.get("/refunds/pending", response_model=list[RefundOut])
async def list_pending_refunds(_actor: AdminUser, db: DbDep) -> list[RefundOut]:
    rows = (
        (
            await db.execute(
                select(Refund)
                .where(Refund.status == RefundStatus.PENDING)
                .order_by(Refund.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [
        RefundOut(
            id=r.id,
            payment_id=r.payment_id,
            amount_bdt=r.amount_bdt,
            reason=r.reason,
            provider=r.provider.value,
            status=r.status,
            completed_at=r.completed_at,
        )
        for r in rows
    ]


# Suppress unused-import warning for utilities pulled in via tests.
_ = (Booking, UTC)
