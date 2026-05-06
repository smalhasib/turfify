"""Customer-facing discount validation + admin CRUD.

`POST /v1/discount-codes/validate` — auth required. Lets the cart preview the
discount amount before posting a hold so the user sees the final total inline.

`/v1/admin/discount-codes` — full CRUD, admin role required.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.enums import DiscountType, UserRole
from app.models import DiscountCode, DiscountRedemption
from app.security.deps import AdminUser, CurrentUser
from app.services.discounts import (
    DiscountInvalidError,
    validate_code,
)

# Two routers: one customer-facing, one admin-gated.
router = APIRouter(prefix="/discount-codes", tags=["discounts"])
admin_router = APIRouter(prefix="/admin/discount-codes", tags=["admin", "discounts"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Customer validation
# ---------------------------------------------------------------------------


class ValidateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    subtotal_bdt: int = Field(..., ge=0)
    slot_dates: list[date] = Field(default_factory=list)


class ValidateResponse(BaseModel):
    code: str
    type: DiscountType
    amount_off_bdt: int
    final_total_bdt: int


@router.post("/validate", response_model=ValidateResponse)
async def validate(body: ValidateRequest, user: CurrentUser, db: DbDep) -> ValidateResponse:
    try:
        resolution = await validate_code(
            db,
            code=body.code,
            user=user,
            subtotal_bdt=body.subtotal_bdt,
            slot_dates=body.slot_dates,
        )
    except DiscountInvalidError as e:
        raise HTTPException(status_code=400, detail=e.code) from e

    return ValidateResponse(
        code=resolution.discount.code,
        type=resolution.discount.type,
        amount_off_bdt=resolution.amount_off_bdt,
        final_total_bdt=max(0, body.subtotal_bdt - resolution.amount_off_bdt),
    )


# ---------------------------------------------------------------------------
# Admin CRUD
# ---------------------------------------------------------------------------


class DiscountCodeIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    type: DiscountType
    value: int = Field(..., gt=0)
    min_amount_bdt: int = Field(default=0, ge=0)
    max_discount_bdt: int | None = Field(default=None, ge=0)
    usage_limit_total: int | None = Field(default=None, ge=1)
    usage_limit_per_user: int = Field(default=1, ge=1)
    valid_from: datetime
    valid_until: datetime
    is_active: bool = True
    applies_to: dict[str, Any] | None = None


class DiscountCodePatch(BaseModel):
    type: DiscountType | None = None
    value: int | None = Field(default=None, gt=0)
    min_amount_bdt: int | None = Field(default=None, ge=0)
    max_discount_bdt: int | None = Field(default=None, ge=0)
    usage_limit_total: int | None = Field(default=None, ge=1)
    usage_limit_per_user: int | None = Field(default=None, ge=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    is_active: bool | None = None
    applies_to: dict[str, Any] | None = None


class DiscountCodeOut(BaseModel):
    id: int
    code: str
    type: DiscountType
    value: int
    min_amount_bdt: int
    max_discount_bdt: int | None
    usage_limit_total: int | None
    usage_limit_per_user: int
    valid_from: datetime
    valid_until: datetime
    is_active: bool
    applies_to: dict[str, Any] | None
    created_at: datetime
    redemption_count: int


def _ensure_window(*, valid_from: datetime, valid_until: datetime) -> None:
    if valid_until <= valid_from:
        raise HTTPException(status_code=400, detail="invalid_validity_window")


def _ensure_percent_in_range(*, type_: DiscountType, value: int) -> None:
    if type_ == DiscountType.PERCENT and value > 100:
        raise HTTPException(status_code=400, detail="percent_must_be_le_100")


async def _redemption_counts(db: AsyncSession, codes: Iterable[DiscountCode]) -> dict[int, int]:
    code_ids = [c.id for c in codes]
    if not code_ids:
        return {}
    rows = (
        await db.execute(
            select(
                DiscountRedemption.discount_code_id,
                func.count(DiscountRedemption.id),
            )
            .where(
                DiscountRedemption.discount_code_id.in_(code_ids),
                DiscountRedemption.voided.is_(False),
            )
            .group_by(DiscountRedemption.discount_code_id)
        )
    ).all()
    return {int(cid): int(count) for cid, count in rows}


def _to_out(code: DiscountCode, *, redemption_count: int = 0) -> DiscountCodeOut:
    return DiscountCodeOut(
        id=code.id,
        code=code.code,
        type=code.type,
        value=code.value,
        min_amount_bdt=code.min_amount_bdt,
        max_discount_bdt=code.max_discount_bdt,
        usage_limit_total=code.usage_limit_total,
        usage_limit_per_user=code.usage_limit_per_user,
        valid_from=code.valid_from,
        valid_until=code.valid_until,
        is_active=code.is_active,
        applies_to=code.applies_to,
        created_at=code.created_at,
        redemption_count=redemption_count,
    )


@admin_router.post("", response_model=DiscountCodeOut, status_code=status.HTTP_201_CREATED)
async def create_discount_code(
    body: DiscountCodeIn, admin: AdminUser, db: DbDep
) -> DiscountCodeOut:
    _ensure_window(valid_from=body.valid_from, valid_until=body.valid_until)
    _ensure_percent_in_range(type_=body.type, value=body.value)

    existing = (
        await db.execute(select(DiscountCode).where(DiscountCode.code == body.code))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="code_already_exists")

    discount = DiscountCode(
        code=body.code,
        type=body.type,
        value=body.value,
        min_amount_bdt=body.min_amount_bdt,
        max_discount_bdt=body.max_discount_bdt,
        usage_limit_total=body.usage_limit_total,
        usage_limit_per_user=body.usage_limit_per_user,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        is_active=body.is_active,
        applies_to=body.applies_to,
        created_by=admin.id,
    )
    db.add(discount)
    await db.commit()
    return _to_out(discount)


@admin_router.get("", response_model=list[DiscountCodeOut])
async def list_discount_codes(_admin: AdminUser, db: DbDep) -> list[DiscountCodeOut]:
    rows = (
        (await db.execute(select(DiscountCode).order_by(desc(DiscountCode.created_at))))
        .scalars()
        .all()
    )
    counts = await _redemption_counts(db, rows)
    return [_to_out(r, redemption_count=counts.get(r.id, 0)) for r in rows]


@admin_router.get("/{code_id}", response_model=DiscountCodeOut)
async def read_discount_code(code_id: int, _admin: AdminUser, db: DbDep) -> DiscountCodeOut:
    discount = (
        await db.execute(select(DiscountCode).where(DiscountCode.id == code_id))
    ).scalar_one_or_none()
    if discount is None:
        raise HTTPException(status_code=404, detail="discount_not_found")
    counts = await _redemption_counts(db, [discount])
    return _to_out(discount, redemption_count=counts.get(discount.id, 0))


@admin_router.patch("/{code_id}", response_model=DiscountCodeOut)
async def update_discount_code(
    code_id: int, body: DiscountCodePatch, _admin: AdminUser, db: DbDep
) -> DiscountCodeOut:
    discount = (
        await db.execute(select(DiscountCode).where(DiscountCode.id == code_id))
    ).scalar_one_or_none()
    if discount is None:
        raise HTTPException(status_code=404, detail="discount_not_found")

    data = body.model_dump(exclude_unset=True)
    # Validate the *proposed* values before mutating the ORM object so the DB
    # CHECK constraints don't fire on autoflush before we can return 400.
    proposed_type = data.get("type", discount.type)
    proposed_value = data.get("value", discount.value)
    proposed_from = data.get("valid_from", discount.valid_from)
    proposed_until = data.get("valid_until", discount.valid_until)
    _ensure_window(valid_from=proposed_from, valid_until=proposed_until)
    _ensure_percent_in_range(type_=proposed_type, value=proposed_value)

    for field, value in data.items():
        setattr(discount, field, value)

    await db.commit()
    counts = await _redemption_counts(db, [discount])
    return _to_out(discount, redemption_count=counts.get(discount.id, 0))


@admin_router.delete("/{code_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_discount_code(code_id: int, _admin: AdminUser, db: DbDep) -> None:
    discount = (
        await db.execute(select(DiscountCode).where(DiscountCode.id == code_id))
    ).scalar_one_or_none()
    if discount is None:
        raise HTTPException(status_code=404, detail="discount_not_found")

    # Block hard delete if redemptions exist; admin should deactivate instead
    # so the audit trail (and active holds) stays intact.
    counts = await _redemption_counts(db, [discount])
    if counts.get(discount.id, 0) > 0:
        raise HTTPException(status_code=409, detail="discount_has_redemptions")

    await db.delete(discount)
    await db.commit()


# Suppress unused-import warning for utilities reachable via tests later.
_ = (UserRole, timedelta, UTC)
