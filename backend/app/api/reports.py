"""Admin reporting endpoints (revenue, occupancy, customers, audit log).

All routes are gated by AdminUser (role=admin). Live SQL aggregates only —
no rollup tables; the design plan said don't pre-optimize until query lat
crosses 1s on real data.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.enums import (
    BookingSource,
    BookingStatus,
    PaymentCollection,
    PaymentProvider,
    PaymentStatus,
)
from app.models import (
    AuditLog,
    Booking,
    BookingSlot,
    Payment,
    User,
)
from app.security.deps import AdminUser

router = APIRouter(prefix="/admin/reports", tags=["admin", "reports"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RevenueDayRow(BaseModel):
    day: date
    online_bdt: int
    cash_bdt: int
    bkash_manual_bdt: int
    pending_cash_bdt: int  # confirmed bookings still cash_pending
    free_bdt: int  # complimentary lost revenue (informational)
    total_collected_bdt: int


class RevenueResponse(BaseModel):
    from_date: date
    to_date: date
    rows: list[RevenueDayRow]
    totals: RevenueDayRow


class OccupancyDayRow(BaseModel):
    day: date
    booked_slot_count: int
    revenue_bdt: int


class HeatmapCell(BaseModel):
    day_of_week: int  # 0=Monday .. 6=Sunday
    hour: int
    booked_slots: int


class OccupancyResponse(BaseModel):
    from_date: date
    to_date: date
    rows: list[OccupancyDayRow]
    heatmap: list[HeatmapCell]


class CustomerRow(BaseModel):
    user_id: int
    phone: str
    name: str | None
    booking_count: int
    total_spend_bdt: int
    last_booking_at: datetime | None
    no_show_count: int
    cash_disabled: bool
    role: str


class CustomerListResponse(BaseModel):
    rows: list[CustomerRow]
    total: int


class AuditLogRow(BaseModel):
    id: int
    actor_user_id: int | None
    action: str
    entity_type: str | None
    entity_id: int | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Common range parsing
# ---------------------------------------------------------------------------


_PRESETS: dict[str, int] = {
    "today": 0,
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "ytd": 366,  # special-cased below to clamp to year start
    "mtd": 31,  # special-cased below to clamp to month start
}


def _resolve_range(
    *, preset: str | None, from_date: date | None, to_date: date | None
) -> tuple[date, date]:
    today = datetime.now(UTC).date()
    if preset is not None:
        if preset == "today":
            return today, today
        if preset == "ytd":
            return date(today.year, 1, 1), today
        if preset == "mtd":
            return date(today.year, today.month, 1), today
        days = _PRESETS.get(preset)
        if days is not None:
            return today - timedelta(days=days), today
    if from_date is None or to_date is None:
        return today - timedelta(days=30), today
    return from_date, to_date


# ---------------------------------------------------------------------------
# Revenue
# ---------------------------------------------------------------------------


async def _revenue_rows(db: AsyncSession, *, from_date: date, to_date: date) -> list[RevenueDayRow]:
    """Group completed payments by day + provider, plus pending cash and
    complimentary bookings for the same window.
    """
    payment_day_col = func.date(Payment.completed_at).label("day")

    payment_query = (
        select(
            payment_day_col,
            Payment.provider,
            func.sum(Payment.amount_bdt).label("amount"),
        )
        .where(
            Payment.status == PaymentStatus.COMPLETED,
            Payment.completed_at.is_not(None),
            func.date(Payment.completed_at) >= from_date,
            func.date(Payment.completed_at) <= to_date,
        )
        .group_by(func.date(Payment.completed_at), Payment.provider)
    )

    by_day: dict[date, dict[str, int]] = {}
    for row_day, provider, amount in (await db.execute(payment_query)).all():
        d = row_day.date() if isinstance(row_day, datetime) else row_day
        bucket = by_day.setdefault(
            d,
            {"online": 0, "cash": 0, "bkash_manual": 0, "pending_cash": 0, "free": 0},
        )
        if provider == PaymentProvider.BKASH:
            bucket["online"] += int(amount or 0)
        elif provider == PaymentProvider.CASH:
            bucket["cash"] += int(amount or 0)
        elif provider == PaymentProvider.BKASH_MANUAL:
            bucket["bkash_manual"] += int(amount or 0)

    # Pending cash bookings (confirmed but cash_pending) — informational
    # so admins can see how much money is owed at the venue.
    pending_query = (
        select(
            func.date(Booking.first_slot_at).label("day"),
            func.sum(Booking.total_amount_bdt).label("amount"),
        )
        .where(
            Booking.status == BookingStatus.CONFIRMED,
            Booking.payment_collection == PaymentCollection.CASH_PENDING,
            func.date(Booking.first_slot_at) >= from_date,
            func.date(Booking.first_slot_at) <= to_date,
        )
        .group_by(func.date(Booking.first_slot_at))
    )
    for row_day, amount in (await db.execute(pending_query)).all():
        d = row_day.date() if isinstance(row_day, datetime) else row_day
        by_day.setdefault(
            d,
            {"online": 0, "cash": 0, "bkash_manual": 0, "pending_cash": 0, "free": 0},
        )["pending_cash"] = int(amount or 0)

    # Complimentary (free) bookings — lost-revenue line for visibility.
    free_query = (
        select(
            func.date(Booking.created_at).label("day"),
            func.sum(Booking.subtotal_bdt).label("amount"),
        )
        .where(
            Booking.payment_collection == PaymentCollection.FREE,
            func.date(Booking.created_at) >= from_date,
            func.date(Booking.created_at) <= to_date,
        )
        .group_by(func.date(Booking.created_at))
    )
    for row_day, amount in (await db.execute(free_query)).all():
        d = row_day.date() if isinstance(row_day, datetime) else row_day
        by_day.setdefault(
            d,
            {"online": 0, "cash": 0, "bkash_manual": 0, "pending_cash": 0, "free": 0},
        )["free"] = int(amount or 0)

    rows: list[RevenueDayRow] = []
    cur = from_date
    while cur <= to_date:
        b = by_day.get(
            cur,
            {"online": 0, "cash": 0, "bkash_manual": 0, "pending_cash": 0, "free": 0},
        )
        collected = b["online"] + b["cash"] + b["bkash_manual"]
        rows.append(
            RevenueDayRow(
                day=cur,
                online_bdt=b["online"],
                cash_bdt=b["cash"],
                bkash_manual_bdt=b["bkash_manual"],
                pending_cash_bdt=b["pending_cash"],
                free_bdt=b["free"],
                total_collected_bdt=collected,
            )
        )
        cur += timedelta(days=1)
    return rows


def _sum_revenue(rows: list[RevenueDayRow], from_d: date, to_d: date) -> RevenueDayRow:
    return RevenueDayRow(
        day=from_d,
        online_bdt=sum(r.online_bdt for r in rows),
        cash_bdt=sum(r.cash_bdt for r in rows),
        bkash_manual_bdt=sum(r.bkash_manual_bdt for r in rows),
        pending_cash_bdt=sum(r.pending_cash_bdt for r in rows),
        free_bdt=sum(r.free_bdt for r in rows),
        total_collected_bdt=sum(r.total_collected_bdt for r in rows),
    )


@router.get("/revenue", response_model=RevenueResponse)
async def revenue_report(
    _admin: AdminUser,
    db: DbDep,
    preset: Annotated[str | None, Query()] = None,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> RevenueResponse:
    f, t = _resolve_range(preset=preset, from_date=from_date, to_date=to_date)
    rows = await _revenue_rows(db, from_date=f, to_date=t)
    return RevenueResponse(from_date=f, to_date=t, rows=rows, totals=_sum_revenue(rows, f, t))


@router.get("/revenue.csv")
async def revenue_csv(
    _admin: AdminUser,
    db: DbDep,
    preset: Annotated[str | None, Query()] = None,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> Response:
    f, t = _resolve_range(preset=preset, from_date=from_date, to_date=to_date)
    rows = await _revenue_rows(db, from_date=f, to_date=t)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "day",
            "online_bdt",
            "cash_bdt",
            "bkash_manual_bdt",
            "pending_cash_bdt",
            "free_bdt",
            "total_collected_bdt",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.day.isoformat(),
                r.online_bdt,
                r.cash_bdt,
                r.bkash_manual_bdt,
                r.pending_cash_bdt,
                r.free_bdt,
                r.total_collected_bdt,
            ]
        )

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="revenue-{f.isoformat()}-to-{t.isoformat()}.csv"'
            )
        },
    )


# ---------------------------------------------------------------------------
# Occupancy
# ---------------------------------------------------------------------------


@router.get("/occupancy", response_model=OccupancyResponse)
async def occupancy_report(
    _admin: AdminUser,
    db: DbDep,
    preset: Annotated[str | None, Query()] = None,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> OccupancyResponse:
    f, t = _resolve_range(preset=preset, from_date=from_date, to_date=to_date)

    daily = (
        select(
            func.date(BookingSlot.slot_start_at).label("day"),
            func.count(BookingSlot.id).label("count"),
            func.coalesce(func.sum(BookingSlot.price_bdt), 0).label("revenue"),
        )
        .where(
            BookingSlot.booking_status == BookingStatus.CONFIRMED,
            func.date(BookingSlot.slot_start_at) >= f,
            func.date(BookingSlot.slot_start_at) <= t,
        )
        .group_by(func.date(BookingSlot.slot_start_at))
    )

    daily_rows: list[OccupancyDayRow] = []
    by_day: dict[date, OccupancyDayRow] = {}
    for raw_day, count, revenue in (await db.execute(daily)).all():
        d = raw_day.date() if isinstance(raw_day, datetime) else raw_day
        row = OccupancyDayRow(
            day=d, booked_slot_count=int(count or 0), revenue_bdt=int(revenue or 0)
        )
        by_day[d] = row

    cur = f
    while cur <= t:
        daily_rows.append(
            by_day.get(cur, OccupancyDayRow(day=cur, booked_slot_count=0, revenue_bdt=0))
        )
        cur += timedelta(days=1)

    # Heatmap dow × hour. Postgres extract(dow): 0=Sunday..6=Saturday.
    # Normalize to 0=Monday..6=Sunday for ISO consistency.
    iso_dow = case(
        (func.extract("dow", BookingSlot.slot_start_at) == 0, 6),
        else_=func.extract("dow", BookingSlot.slot_start_at) - 1,
    )
    hour_expr = func.extract("hour", BookingSlot.slot_start_at)
    heat = (
        select(
            iso_dow.label("dow"),
            hour_expr.label("hour"),
            func.count(BookingSlot.id).label("count"),
        )
        .where(
            BookingSlot.booking_status == BookingStatus.CONFIRMED,
            func.date(BookingSlot.slot_start_at) >= f,
            func.date(BookingSlot.slot_start_at) <= t,
        )
        .group_by("dow", "hour")
        .order_by("dow", "hour")
    )

    cells = [
        HeatmapCell(day_of_week=int(d), hour=int(h), booked_slots=int(c))
        for d, h, c in (await db.execute(heat)).all()
    ]

    return OccupancyResponse(from_date=f, to_date=t, rows=daily_rows, heatmap=cells)


# ---------------------------------------------------------------------------
# Customer log
# ---------------------------------------------------------------------------


@router.get("/customers", response_model=CustomerListResponse)
async def customer_log(
    _admin: AdminUser,
    db: DbDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Literal["spend", "count", "recent"] = "spend",
) -> CustomerListResponse:
    spend_subq = (
        select(
            Booking.user_id.label("uid"),
            func.count(Booking.id).label("booking_count"),
            func.coalesce(func.sum(Booking.total_amount_bdt), 0).label("total_spend"),
            func.max(Booking.created_at).label("last_booking_at"),
        )
        .where(
            Booking.status.in_(
                [BookingStatus.CONFIRMED, BookingStatus.COMPLETED, BookingStatus.REFUNDED]
            )
        )
        .group_by(Booking.user_id)
        .subquery()
    )

    sort_col = {
        "spend": desc(spend_subq.c.total_spend),
        "count": desc(spend_subq.c.booking_count),
        "recent": desc(spend_subq.c.last_booking_at),
    }[sort]

    base = (
        select(
            User, spend_subq.c.booking_count, spend_subq.c.total_spend, spend_subq.c.last_booking_at
        )
        .outerjoin(spend_subq, spend_subq.c.uid == User.id)
        .where(User.deleted_at.is_(None))
    )

    total = (
        await db.execute(select(func.count()).select_from(User).where(User.deleted_at.is_(None)))
    ).scalar_one()

    rows = (await db.execute(base.order_by(sort_col, User.id).limit(limit).offset(offset))).all()

    out = [
        CustomerRow(
            user_id=u.id,
            phone=u.phone,
            name=u.name,
            booking_count=int(bc or 0),
            total_spend_bdt=int(ts or 0),
            last_booking_at=lba,
            no_show_count=u.no_show_count,
            cash_disabled=u.cash_disabled,
            role=u.role.value,
        )
        for (u, bc, ts, lba) in rows
    ]

    return CustomerListResponse(rows=out, total=int(total))


@router.get("/customers.csv")
async def customers_csv(_admin: AdminUser, db: DbDep) -> Response:
    """Stream the full customer log as CSV. Pagination params skipped — admin
    pulls a complete export.
    """
    spend_subq = (
        select(
            Booking.user_id.label("uid"),
            func.count(Booking.id).label("booking_count"),
            func.coalesce(func.sum(Booking.total_amount_bdt), 0).label("total_spend"),
            func.max(Booking.created_at).label("last_booking_at"),
        )
        .where(
            Booking.status.in_(
                [BookingStatus.CONFIRMED, BookingStatus.COMPLETED, BookingStatus.REFUNDED]
            )
        )
        .group_by(Booking.user_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                User,
                spend_subq.c.booking_count,
                spend_subq.c.total_spend,
                spend_subq.c.last_booking_at,
            )
            .outerjoin(spend_subq, spend_subq.c.uid == User.id)
            .where(User.deleted_at.is_(None))
            .order_by(desc(spend_subq.c.total_spend), User.id)
        )
    ).all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "user_id",
            "phone",
            "name",
            "role",
            "booking_count",
            "total_spend_bdt",
            "last_booking_at",
            "no_show_count",
            "cash_disabled",
        ]
    )
    for u, bc, ts, lba in rows:
        w.writerow(
            [
                u.id,
                u.phone,
                u.name or "",
                u.role.value,
                int(bc or 0),
                int(ts or 0),
                lba.isoformat() if lba else "",
                u.no_show_count,
                u.cash_disabled,
            ]
        )

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="customers.csv"'},
    )


# ---------------------------------------------------------------------------
# Audit log (read-only)
# ---------------------------------------------------------------------------


@router.get("/audit-log", response_model=list[AuditLogRow])
async def audit_log(
    _admin: AdminUser,
    db: DbDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    action: Annotated[str | None, Query()] = None,
    entity_type: Annotated[str | None, Query()] = None,
) -> list[AuditLogRow]:
    q = select(AuditLog)
    if action is not None:
        q = q.where(AuditLog.action == action)
    if entity_type is not None:
        q = q.where(AuditLog.entity_type == entity_type)
    q = q.order_by(desc(AuditLog.created_at)).limit(limit).offset(offset)

    rows = (await db.execute(q)).scalars().all()
    return [
        AuditLogRow(
            id=r.id,
            actor_user_id=r.actor_user_id,
            action=r.action,
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            created_at=r.created_at,
        )
        for r in rows
    ]


# Suppress unused-import warnings for utilities reachable via tests.
_ = (BookingSource, status, Any)
