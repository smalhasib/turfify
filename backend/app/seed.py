"""Idempotent seed: default venue + first admin from INITIAL_ADMIN_PHONE.

Run via:
    python -m app.seed

Safe to re-run. Will not duplicate venues or users.
"""

from __future__ import annotations

import asyncio
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.enums import UserRole
from app.logging_config import configure_logging, get_logger
from app.models import User, Venue

DEFAULT_VENUE_NAME = "Turfify Main"
DEFAULT_VENUE_DEFAULTS = {
    "address": "Dhaka, Bangladesh",
    "open_hour": 6,
    "close_hour": 24,
    "slot_duration_min": 60,
    "advance_book_days": 14,
    "cutoff_min": 30,
    "base_price_bdt": 1000,
    "cash_cancel_minutes_before": 15,
    "cancellation_full_refund_hours": 24,
    "timezone": "Asia/Dhaka",
    "is_active": True,
}

# Bangladesh mobile: +880 followed by 1[3-9] and 8 more digits.
BD_PHONE_PATTERN = re.compile(r"^\+8801[3-9]\d{8}$")


async def ensure_default_venue(session: AsyncSession) -> Venue:
    log = get_logger(__name__)
    result = await session.execute(select(Venue).where(Venue.name == DEFAULT_VENUE_NAME))
    venue = result.scalar_one_or_none()
    if venue is not None:
        log.info("seed.venue.exists", venue_id=venue.id, name=venue.name)
        return venue

    venue = Venue(name=DEFAULT_VENUE_NAME, **DEFAULT_VENUE_DEFAULTS)
    session.add(venue)
    await session.flush()
    log.info("seed.venue.created", venue_id=venue.id, name=venue.name)
    return venue


async def ensure_first_admin(session: AsyncSession, phone: str) -> User | None:
    log = get_logger(__name__)
    if not phone:
        log.info("seed.admin.skipped", reason="INITIAL_ADMIN_PHONE not set")
        return None

    if not BD_PHONE_PATTERN.match(phone):
        log.warning(
            "seed.admin.invalid_phone",
            phone=phone,
            hint="Expected +8801XXXXXXXXX (E.164, BD mobile)",
        )
        return None

    result = await session.execute(select(User).where(User.phone == phone))
    user = result.scalar_one_or_none()
    if user is not None:
        if user.role != UserRole.ADMIN:
            user.role = UserRole.ADMIN
            log.info("seed.admin.promoted", user_id=user.id, phone=phone)
        else:
            log.info("seed.admin.exists", user_id=user.id, phone=phone)
        return user

    user = User(
        phone=phone,
        name="Initial Admin",
        role=UserRole.ADMIN,
        manually_created=True,
    )
    session.add(user)
    await session.flush()
    log.info("seed.admin.created", user_id=user.id, phone=phone)
    return user


async def run_seed() -> None:
    settings = get_settings()
    log = get_logger(__name__)
    log.info("seed.start", env=settings.app_env)

    async with AsyncSessionLocal() as session:
        await ensure_default_venue(session)
        await ensure_first_admin(session, settings.initial_admin_phone)
        await session.commit()

    log.info("seed.done")


def main() -> None:
    configure_logging()
    asyncio.run(run_seed())


if __name__ == "__main__":
    main()
