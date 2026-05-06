"""Unit tests for the pure pricing math in services.discounts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.enums import DiscountType
from app.models import DiscountCode
from app.services.discounts import compute_discount_amount


def _code(
    *,
    type_: DiscountType,
    value: int,
    max_discount: int | None = None,
) -> DiscountCode:
    now = datetime.now(UTC)
    return DiscountCode(
        id=1,
        code="X",
        type=type_,
        value=value,
        min_amount_bdt=0,
        max_discount_bdt=max_discount,
        usage_limit_total=None,
        usage_limit_per_user=1,
        valid_from=now,
        valid_until=now + timedelta(days=7),
        is_active=True,
        applies_to=None,
    )


@pytest.mark.unit
def test_percent_simple() -> None:
    code = _code(type_=DiscountType.PERCENT, value=20)
    assert compute_discount_amount(discount=code, subtotal_bdt=1000) == 200


@pytest.mark.unit
def test_percent_floor_division() -> None:
    code = _code(type_=DiscountType.PERCENT, value=33)
    # 1000 * 33 / 100 = 330 exactly
    assert compute_discount_amount(discount=code, subtotal_bdt=1000) == 330
    # Odd subtotal -> floor
    assert compute_discount_amount(discount=code, subtotal_bdt=1234) == 407


@pytest.mark.unit
def test_percent_capped_by_max_discount() -> None:
    code = _code(type_=DiscountType.PERCENT, value=50, max_discount=400)
    assert compute_discount_amount(discount=code, subtotal_bdt=2000) == 400


@pytest.mark.unit
def test_flat_simple() -> None:
    code = _code(type_=DiscountType.FLAT, value=300)
    assert compute_discount_amount(discount=code, subtotal_bdt=1000) == 300


@pytest.mark.unit
def test_flat_clamped_to_subtotal() -> None:
    code = _code(type_=DiscountType.FLAT, value=2000)
    assert compute_discount_amount(discount=code, subtotal_bdt=1000) == 1000


@pytest.mark.unit
def test_flat_capped_by_max_discount_then_subtotal() -> None:
    code = _code(type_=DiscountType.FLAT, value=2000, max_discount=500)
    assert compute_discount_amount(discount=code, subtotal_bdt=1000) == 500


@pytest.mark.unit
def test_zero_subtotal() -> None:
    code = _code(type_=DiscountType.PERCENT, value=20)
    assert compute_discount_amount(discount=code, subtotal_bdt=0) == 0
    assert compute_discount_amount(discount=code, subtotal_bdt=-100) == 0
