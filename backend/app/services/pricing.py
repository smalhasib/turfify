"""Pricing rule resolver.

Resolution order for a given slot at (venue, date, hour):
  1. If a `schedule_exceptions.windows[i]` row carries an explicit price, use it
     (handled by the slot generator before this resolver is called).
  2. Else: highest-priority active `pricing_rules` row matching (date, hour, dow).
  3. Else: `venue.base_price_bdt`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from app.models import PricingRule, Venue


@dataclass(frozen=True)
class ResolvedPrice:
    price_bdt: int
    rule_id: int | None  # None when fallback to venue base


def _rule_matches(rule: PricingRule, *, day: date, hour: int) -> bool:
    if not rule.is_active:
        return False
    if rule.date_start is not None and day < rule.date_start:
        return False
    if rule.date_end is not None and day > rule.date_end:
        return False
    # day_of_week NULL means any day; otherwise Monday=0..Sunday=6 (Python weekday).
    if rule.day_of_week is not None and rule.day_of_week != day.weekday():
        return False
    return rule.hour_start <= hour < rule.hour_end


def resolve_price(
    *, venue: Venue, rules: Iterable[PricingRule], day: date, hour: int
) -> ResolvedPrice:
    """Return the BDT price for the slot starting at `day` `hour`:00."""
    best: PricingRule | None = None
    for rule in rules:
        if not _rule_matches(rule, day=day, hour=hour):
            continue
        if best is None or rule.priority > best.priority:
            best = rule

    if best is not None:
        return ResolvedPrice(price_bdt=best.price_bdt, rule_id=best.id)
    return ResolvedPrice(price_bdt=venue.base_price_bdt, rule_id=None)
