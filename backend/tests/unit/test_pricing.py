"""Unit tests for pricing rule resolver."""

from __future__ import annotations

from datetime import date

import pytest

from app.models import PricingRule, Venue
from app.services.pricing import resolve_price


def _venue(base: int = 1000) -> Venue:
    return Venue(id=1, name="V", base_price_bdt=base)


def _rule(
    *,
    rule_id: int = 1,
    venue_id: int = 1,
    name: str = "rule",
    price: int,
    priority: int = 0,
    day_of_week: int | None = None,
    hour_start: int = 0,
    hour_end: int = 24,
    date_start: date | None = None,
    date_end: date | None = None,
    is_active: bool = True,
) -> PricingRule:
    return PricingRule(
        id=rule_id,
        venue_id=venue_id,
        name=name,
        day_of_week=day_of_week,
        hour_start=hour_start,
        hour_end=hour_end,
        date_start=date_start,
        date_end=date_end,
        price_bdt=price,
        priority=priority,
        is_active=is_active,
    )


@pytest.mark.unit
def test_falls_back_to_venue_base_when_no_rules() -> None:
    res = resolve_price(venue=_venue(1500), rules=[], day=date(2026, 5, 10), hour=18)
    assert res.price_bdt == 1500
    assert res.rule_id is None


@pytest.mark.unit
def test_single_rule_matches() -> None:
    res = resolve_price(
        venue=_venue(),
        rules=[_rule(price=2000, hour_start=18, hour_end=22)],
        day=date(2026, 5, 10),
        hour=20,
    )
    assert res.price_bdt == 2000


@pytest.mark.unit
def test_rule_outside_hours_does_not_match() -> None:
    res = resolve_price(
        venue=_venue(),
        rules=[_rule(price=2000, hour_start=18, hour_end=22)],
        day=date(2026, 5, 10),
        hour=10,
    )
    assert res.price_bdt == 1000  # falls back to base


@pytest.mark.unit
def test_higher_priority_wins() -> None:
    rules = [
        _rule(rule_id=1, price=1500, priority=0),  # all-day
        _rule(rule_id=2, price=2500, priority=10, hour_start=18, hour_end=22),  # peak
    ]
    res = resolve_price(venue=_venue(), rules=rules, day=date(2026, 5, 10), hour=20)
    assert res.price_bdt == 2500
    assert res.rule_id == 2


@pytest.mark.unit
def test_inactive_rule_ignored() -> None:
    rules = [_rule(price=2500, priority=10, is_active=False)]
    res = resolve_price(venue=_venue(), rules=rules, day=date(2026, 5, 10), hour=20)
    assert res.price_bdt == 1000


@pytest.mark.unit
def test_day_of_week_filter() -> None:
    # 2026-05-10 is a Sunday (weekday() == 6)
    rules = [_rule(price=2500, day_of_week=6)]
    sun = resolve_price(venue=_venue(), rules=rules, day=date(2026, 5, 10), hour=20)
    mon = resolve_price(venue=_venue(), rules=rules, day=date(2026, 5, 11), hour=20)
    assert sun.price_bdt == 2500
    assert mon.price_bdt == 1000


@pytest.mark.unit
def test_date_range_filter() -> None:
    rules = [
        _rule(
            price=3000,
            date_start=date(2026, 5, 10),
            date_end=date(2026, 5, 15),
        )
    ]
    inside = resolve_price(venue=_venue(), rules=rules, day=date(2026, 5, 12), hour=20)
    before = resolve_price(venue=_venue(), rules=rules, day=date(2026, 5, 9), hour=20)
    after = resolve_price(venue=_venue(), rules=rules, day=date(2026, 5, 16), hour=20)
    assert inside.price_bdt == 3000
    assert before.price_bdt == 1000
    assert after.price_bdt == 1000
