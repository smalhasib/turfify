"""Discount code validation + redemption.

Validation order at hold time:
  1. Code exists, `is_active` is true.
  2. `now()` falls within `[valid_from, valid_until)`.
  3. Total redemptions < `usage_limit_total` (if set).
  4. User redemption count < `usage_limit_per_user`.
  5. Booking subtotal >= `min_amount_bdt`.
  6. `applies_to` matches the slot dates (weekday / weekend / specific_dates).

Discount amount:
  - percent: floor(subtotal * value / 100), then capped by `max_discount_bdt`.
  - flat: value, then capped by `max_discount_bdt` AND clamped to subtotal.

A `discount_redemptions` row is inserted at hold time so concurrent claims
respect the limit. On hold expire / cancel pre-confirm, the row is marked
`voided=true` (not deleted — we keep an audit trail).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import DiscountType
from app.models import DiscountCode, DiscountRedemption, User

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DiscountInvalidError(Exception):
    code: str = "discount_invalid"

    def __init__(self, code: str | None = None) -> None:
        super().__init__(code or self.code)
        self.code = code or self.code


class DiscountNotFoundError(DiscountInvalidError):
    code = "discount_not_found"


class DiscountInactiveError(DiscountInvalidError):
    code = "discount_inactive"


class DiscountOutOfWindowError(DiscountInvalidError):
    code = "discount_out_of_window"


class DiscountTotalLimitReachedError(DiscountInvalidError):
    code = "discount_total_limit_reached"


class DiscountPerUserLimitReachedError(DiscountInvalidError):
    code = "discount_per_user_limit_reached"


class DiscountBelowMinAmountError(DiscountInvalidError):
    code = "discount_below_min_amount"


class DiscountAppliesToMismatchError(DiscountInvalidError):
    code = "discount_applies_to_mismatch"


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscountResolution:
    discount: DiscountCode
    amount_off_bdt: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_discount_amount(*, discount: DiscountCode, subtotal_bdt: int) -> int:
    """Pure: return the BDT amount taken off `subtotal_bdt` for this code."""
    if subtotal_bdt <= 0:
        return 0

    if discount.type == DiscountType.PERCENT:
        raw = (subtotal_bdt * discount.value) // 100
    else:  # FLAT
        raw = discount.value

    capped = raw
    if discount.max_discount_bdt is not None:
        capped = min(capped, discount.max_discount_bdt)
    return min(capped, subtotal_bdt)


def _applies_to_dates(discount: DiscountCode, slot_dates: Iterable[date]) -> bool:
    """`applies_to` JSONB shapes:
    - missing / None / {} → matches anything
    - {"weekday": true} → all slot dates must be Mon-Fri
    - {"weekend": true} → all slot dates must be Sat-Sun (BD weekend
      is Fri-Sat; configurable later — default Saturday-Sunday for now)
    - {"specific_dates": ["2026-05-12", ...]} → all slot dates must
      appear in that allowlist
    """
    rules = discount.applies_to
    if not rules:
        return True

    dates = list(slot_dates)
    if not dates:
        return True

    if rules.get("weekday"):
        return all(d.weekday() < 5 for d in dates)
    if rules.get("weekend"):
        return all(d.weekday() >= 5 for d in dates)

    specific = rules.get("specific_dates")
    if specific:
        allowed = {date.fromisoformat(s) for s in specific}
        return all(d in allowed for d in dates)

    return True


async def validate_code(
    db: AsyncSession,
    *,
    code: str,
    user: User,
    subtotal_bdt: int,
    slot_dates: Iterable[date],
    now: datetime | None = None,
    exclude_booking_id: int | None = None,
) -> DiscountResolution:
    """Look up `code` and run every validation rule. Raises a
    `DiscountInvalidError` subclass on the first failure. Returns the resolved
    discount + computed amount when valid.

    `exclude_booking_id` lets callers re-validate after the hold row exists
    (so the row's own redemption doesn't count against the limit).
    """
    if now is None:
        now = datetime.now(UTC)

    discount = (
        await db.execute(select(DiscountCode).where(DiscountCode.code == code))
    ).scalar_one_or_none()
    if discount is None:
        raise DiscountNotFoundError()
    if not discount.is_active:
        raise DiscountInactiveError()
    if not (discount.valid_from <= now < discount.valid_until):
        raise DiscountOutOfWindowError()

    if discount.usage_limit_total is not None:
        total_q = select(func.count(DiscountRedemption.id)).where(
            DiscountRedemption.discount_code_id == discount.id,
            DiscountRedemption.voided.is_(False),
        )
        if exclude_booking_id is not None:
            total_q = total_q.where(DiscountRedemption.booking_id != exclude_booking_id)
        used_total = (await db.execute(total_q)).scalar_one()
        if used_total >= discount.usage_limit_total:
            raise DiscountTotalLimitReachedError()

    user_q = select(func.count(DiscountRedemption.id)).where(
        DiscountRedemption.discount_code_id == discount.id,
        DiscountRedemption.user_id == user.id,
        DiscountRedemption.voided.is_(False),
    )
    if exclude_booking_id is not None:
        user_q = user_q.where(DiscountRedemption.booking_id != exclude_booking_id)
    used_user = (await db.execute(user_q)).scalar_one()
    if used_user >= discount.usage_limit_per_user:
        raise DiscountPerUserLimitReachedError()

    if subtotal_bdt < discount.min_amount_bdt:
        raise DiscountBelowMinAmountError()

    if not _applies_to_dates(discount, slot_dates):
        raise DiscountAppliesToMismatchError()

    amount = compute_discount_amount(discount=discount, subtotal_bdt=subtotal_bdt)
    return DiscountResolution(discount=discount, amount_off_bdt=amount)


async def redeem(
    db: AsyncSession,
    *,
    discount: DiscountCode,
    booking_id: int,
    user: User,
    amount_off_bdt: int,
) -> DiscountRedemption:
    """Insert a `discount_redemptions` row tied to the booking."""
    redemption = DiscountRedemption(
        discount_code_id=discount.id,
        booking_id=booking_id,
        user_id=user.id,
        amount_off_bdt=amount_off_bdt,
    )
    db.add(redemption)
    await db.flush()
    return redemption


async def void_for_booking(db: AsyncSession, *, booking_id: int) -> int:
    """Mark every redemption for this booking as voided. Returns count voided."""
    rows = (
        (
            await db.execute(
                select(DiscountRedemption).where(
                    DiscountRedemption.booking_id == booking_id,
                    DiscountRedemption.voided.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    for r in rows:
        r.voided = True
    await db.flush()
    return len(rows)


# ---------------------------------------------------------------------------
# Type aliases re-exported for callers
# ---------------------------------------------------------------------------

__all__ = [
    "Any",
    "DiscountAppliesToMismatchError",
    "DiscountBelowMinAmountError",
    "DiscountInactiveError",
    "DiscountInvalidError",
    "DiscountNotFoundError",
    "DiscountOutOfWindowError",
    "DiscountPerUserLimitReachedError",
    "DiscountResolution",
    "DiscountTotalLimitReachedError",
    "compute_discount_amount",
    "redeem",
    "validate_code",
    "void_for_booking",
]
