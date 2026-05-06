"""Demo seed: builds a rich state for client demos in one command.

Idempotent. Wipes and rebuilds the *demo* customer/booking state but
preserves the seeded admin and venue.

Run:
    python -m app.seed_demo
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.enums import (
    BookingSource,
    BookingStatus,
    DiscountType,
    PaymentCollection,
    PaymentProvider,
    PaymentStatus,
    ScheduleExceptionType,
    UserRole,
)
from app.logging_config import configure_logging, get_logger
from app.models import (
    Booking,
    BookingSlot,
    DiscountCode,
    Payment,
    PricingRule,
    ScheduleException,
    User,
    Venue,
)
from app.seed import ensure_default_venue, ensure_first_admin

DHK = ZoneInfo("Asia/Dhaka")


DEMO_CUSTOMERS = [
    ("+8801712100201", "Rakib (regular)"),
    ("+8801712100202", "Sajid (corporate)"),
    ("+8801712100203", "Walk-in #1"),
    ("+8801712100204", "Walk-in #2"),
    ("+8801712100205", "Cancelled-by-system"),
]


async def _wipe_demo_data(db: AsyncSession) -> None:
    """Delete demo customer + booking rows but keep the seeded admin/venue."""
    log = get_logger(__name__)

    demo_phones = [phone for phone, _ in DEMO_CUSTOMERS]
    users = (await db.execute(select(User).where(User.phone.in_(demo_phones)))).scalars().all()
    if not users:
        log.info("seed_demo.no_existing_demo_users")
        return

    for user in users:
        bookings = (
            (await db.execute(select(Booking).where(Booking.user_id == user.id))).scalars().all()
        )
        for booking in bookings:
            await db.delete(booking)
        # Flush per-user so the bookings are gone before the FK check on user delete.
        await db.flush()
        await db.delete(user)
        await db.flush()
    await db.commit()
    log.info("seed_demo.wiped", count=len(users))


async def _ensure_pricing_rules(db: AsyncSession, venue: Venue) -> None:
    existing = (
        (await db.execute(select(PricingRule).where(PricingRule.venue_id == venue.id)))
        .scalars()
        .all()
    )
    if existing:
        return
    db.add(
        PricingRule(
            venue_id=venue.id,
            name="Evening peak (Mon-Thu)",
            day_of_week=None,
            hour_start=18,
            hour_end=22,
            price_bdt=1500,
            priority=10,
        )
    )
    db.add(
        PricingRule(
            venue_id=venue.id,
            name="Weekend evening",
            day_of_week=5,  # Saturday in Python weekday()
            hour_start=18,
            hour_end=23,
            price_bdt=1800,
            priority=20,
        )
    )
    await db.commit()


async def _ensure_demo_discount(db: AsyncSession) -> None:
    existing = (
        await db.execute(select(DiscountCode).where(DiscountCode.code == "WEEKEND10"))
    ).scalar_one_or_none()
    if existing:
        return
    now = datetime.now(UTC)
    db.add(
        DiscountCode(
            code="WEEKEND10",
            type=DiscountType.PERCENT,
            value=10,
            min_amount_bdt=1000,
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=60),
            is_active=True,
        )
    )
    db.add(
        DiscountCode(
            code="STUDENT300",
            type=DiscountType.FLAT,
            value=300,
            min_amount_bdt=1500,
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=60),
            is_active=True,
        )
    )
    await db.commit()


async def _ensure_schedule_exception(db: AsyncSession, venue: Venue) -> None:
    """Mark next Friday as windows-restricted to demo schedule_exceptions."""
    today = datetime.now(UTC).date()
    days_to_fri = (4 - today.weekday()) % 7
    if days_to_fri == 0:
        days_to_fri = 7
    target = today + timedelta(days=days_to_fri)

    existing = (
        await db.execute(
            select(ScheduleException).where(
                ScheduleException.venue_id == venue.id,
                ScheduleException.exception_date == target,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return
    db.add(
        ScheduleException(
            venue_id=venue.id,
            exception_date=target,
            type=ScheduleExceptionType.WINDOWS,
            windows=[
                {"start": "09:00", "end": "11:00"},
                {"start": "16:00", "end": "20:00"},
            ],
            reason="Friday windows demo",
        )
    )
    await db.commit()


async def _create_demo_bookings(db: AsyncSession, *, admin: User, venue: Venue) -> None:
    log = get_logger(__name__)
    now = datetime.now(UTC)

    # Create demo users.
    users: dict[str, User] = {}
    for phone, name in DEMO_CUSTOMERS:
        u = User(
            phone=phone,
            name=name,
            role=UserRole.CUSTOMER,
            manually_created=True,
            created_by_admin_id=admin.id,
        )
        db.add(u)
        users[phone] = u
    await db.flush()

    today = now.date()

    def slot_dt(day_offset: int, hour: int) -> tuple[datetime, datetime]:
        d = today + timedelta(days=day_offset)
        local = datetime(d.year, d.month, d.day, hour, 0, tzinfo=DHK)
        return local.astimezone(UTC), (local + timedelta(hours=1)).astimezone(UTC)

    # Booking 1 — confirmed cash, paid (admin recorded).
    s, e = slot_dt(2, 19)  # 2 days from now @ 7pm
    booking_1 = Booking(
        public_id=f"TRF-{now.year}-D00001",
        user_id=users["+8801712100201"].id,
        venue_id=venue.id,
        booking_source=BookingSource.WEB,
        payment_collection=PaymentCollection.CASH,
        subtotal_bdt=1500,
        total_amount_bdt=1500,
        slot_count=1,
        first_slot_at=s,
        last_slot_at=e,
        status=BookingStatus.CONFIRMED,
    )
    db.add(booking_1)
    await db.flush()
    db.add(
        BookingSlot(
            booking_id=booking_1.id,
            venue_id=venue.id,
            slot_start_at=s,
            slot_end_at=e,
            price_bdt=1500,
            booking_status=BookingStatus.CONFIRMED,
        )
    )
    db.add(
        Payment(
            booking_id=booking_1.id,
            provider=PaymentProvider.CASH,
            amount_bdt=1500,
            status=PaymentStatus.COMPLETED,
            collected_by_admin_id=admin.id,
            completed_at=now - timedelta(hours=1),
        )
    )

    # Booking 2 — multi-slot cash_pending (still awaiting payment).
    s1, e1 = slot_dt(3, 18)
    s2, e2 = slot_dt(3, 19)
    booking_2 = Booking(
        public_id=f"TRF-{now.year}-D00002",
        user_id=users["+8801712100202"].id,
        venue_id=venue.id,
        booking_source=BookingSource.WEB,
        payment_collection=PaymentCollection.CASH_PENDING,
        subtotal_bdt=3000,
        total_amount_bdt=3000,
        slot_count=2,
        first_slot_at=s1,
        last_slot_at=e2,
        status=BookingStatus.CONFIRMED,
    )
    db.add(booking_2)
    await db.flush()
    for s, e in [(s1, e1), (s2, e2)]:
        db.add(
            BookingSlot(
                booking_id=booking_2.id,
                venue_id=venue.id,
                slot_start_at=s,
                slot_end_at=e,
                price_bdt=1500,
                booking_status=BookingStatus.CONFIRMED,
            )
        )

    # Booking 3 — admin-created bkash_manual paid booking.
    s, e = slot_dt(4, 20)
    booking_3 = Booking(
        public_id=f"TRF-{now.year}-D00003",
        user_id=users["+8801712100203"].id,
        venue_id=venue.id,
        booking_source=BookingSource.ADMIN,
        created_by_admin_id=admin.id,
        payment_collection=PaymentCollection.BKASH_MANUAL,
        subtotal_bdt=1500,
        total_amount_bdt=1500,
        slot_count=1,
        first_slot_at=s,
        last_slot_at=e,
        status=BookingStatus.CONFIRMED,
    )
    db.add(booking_3)
    await db.flush()
    db.add(
        BookingSlot(
            booking_id=booking_3.id,
            venue_id=venue.id,
            slot_start_at=s,
            slot_end_at=e,
            price_bdt=1500,
            booking_status=BookingStatus.CONFIRMED,
        )
    )
    db.add(
        Payment(
            booking_id=booking_3.id,
            provider=PaymentProvider.BKASH_MANUAL,
            manual_trx_id="DEMO-TRX-901",
            amount_bdt=1500,
            status=PaymentStatus.COMPLETED,
            collected_by_admin_id=admin.id,
            completed_at=now - timedelta(hours=2),
        )
    )

    # Booking 4 — free / complimentary.
    s, e = slot_dt(5, 17)
    booking_4 = Booking(
        public_id=f"TRF-{now.year}-D00004",
        user_id=users["+8801712100204"].id,
        venue_id=venue.id,
        booking_source=BookingSource.ADMIN,
        created_by_admin_id=admin.id,
        payment_collection=PaymentCollection.FREE,
        subtotal_bdt=1000,
        total_amount_bdt=1000,
        slot_count=1,
        first_slot_at=s,
        last_slot_at=e,
        status=BookingStatus.CONFIRMED,
        free_reason="VIP demo guest",
    )
    db.add(booking_4)
    await db.flush()
    db.add(
        BookingSlot(
            booking_id=booking_4.id,
            venue_id=venue.id,
            slot_start_at=s,
            slot_end_at=e,
            price_bdt=1000,
            booking_status=BookingStatus.CONFIRMED,
        )
    )

    # Booking 5 — cancelled (system-side).
    s, e = slot_dt(6, 21)
    booking_5 = Booking(
        public_id=f"TRF-{now.year}-D00005",
        user_id=users["+8801712100205"].id,
        venue_id=venue.id,
        booking_source=BookingSource.WEB,
        payment_collection=PaymentCollection.CASH_PENDING,
        subtotal_bdt=1500,
        total_amount_bdt=1500,
        slot_count=1,
        first_slot_at=s,
        last_slot_at=e,
        status=BookingStatus.CANCELLED,
        cancelled_at=now - timedelta(hours=4),
        cancellation_reason="admin_cancel",
    )
    db.add(booking_5)
    await db.flush()
    db.add(
        BookingSlot(
            booking_id=booking_5.id,
            venue_id=venue.id,
            slot_start_at=s,
            slot_end_at=e,
            price_bdt=1500,
            booking_status=BookingStatus.CANCELLED,
        )
    )

    await db.commit()
    log.info("seed_demo.bookings_created", count=5)


async def run() -> None:
    settings = get_settings()
    log = get_logger(__name__)
    log.info("seed_demo.start", env=settings.app_env)

    async with AsyncSessionLocal() as db:
        venue = await ensure_default_venue(db)
        await db.commit()

        admin = await ensure_first_admin(db, settings.initial_admin_phone)
        if admin is None:
            log.error("seed_demo.no_admin_seeded — set INITIAL_ADMIN_PHONE")
            return
        await db.commit()

        await _wipe_demo_data(db)
        await _ensure_pricing_rules(db, venue)
        await _ensure_demo_discount(db)
        await _ensure_schedule_exception(db, venue)
        await _create_demo_bookings(db, admin=admin, venue=venue)

    log.info("seed_demo.done")


def main() -> None:
    configure_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
