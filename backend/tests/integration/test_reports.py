"""Integration tests for Phase 10 admin reporting endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_firebase_verifier
from app.enums import UserRole
from app.main import app
from app.models import User, Venue

DHK = ZoneInfo("Asia/Dhaka")


async def _make_venue(db: AsyncSession) -> Venue:
    venue = Venue(name="Reports Venue")
    db.add(venue)
    await db.flush()
    return venue


def _slot_iso(day: date, hour: int) -> str:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=DHK).astimezone(UTC).isoformat()


async def _login(api_client: AsyncClient, *, phone: str, fb_uid: str) -> str:
    def fake(_t: str) -> dict[str, Any]:
        return {"uid": fb_uid, "phone_number": phone}

    app.dependency_overrides[get_firebase_verifier] = lambda: fake
    try:
        resp = await api_client.post("/v1/auth/firebase", json={"id_token": "x" * 40})
        return resp.json()["access_token"]
    finally:
        app.dependency_overrides.pop(get_firebase_verifier, None)


def _auth(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_revenue_endpoint_aggregates_payments(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    db_session.add(User(phone="+8801722000001", role=UserRole.ADMIN, manually_created=True))
    await db_session.commit()
    admin = await _login(api_client, phone="+8801722000001", fb_uid="fb_rev_admin")

    target = datetime.now(UTC).date() + timedelta(days=10)
    create = await api_client.post(
        "/v1/admin/bookings",
        headers=_auth(admin),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_collection": "cash",
            "quick_create_phone": "+8801722000099",
        },
    )
    assert create.status_code == 201

    resp = await api_client.get(
        "/v1/admin/reports/revenue",
        headers=_auth(admin),
        params={"preset": "today"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["totals"]["cash_bdt"] == 1000
    assert data["totals"]["total_collected_bdt"] == 1000


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_revenue_csv_streams(api_client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(User(phone="+8801722000002", role=UserRole.ADMIN, manually_created=True))
    await db_session.commit()
    admin = await _login(api_client, phone="+8801722000002", fb_uid="fb_rev_csv")

    resp = await api_client.get(
        "/v1/admin/reports/revenue.csv",
        headers=_auth(admin),
        params={"preset": "7d"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    body = resp.text
    assert body.splitlines()[0].startswith("day,online_bdt,cash_bdt")


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_occupancy_endpoint(api_client: AsyncClient, db_session: AsyncSession) -> None:
    venue = await _make_venue(db_session)
    db_session.add(User(phone="+8801722000003", role=UserRole.ADMIN, manually_created=True))
    await db_session.commit()
    admin = await _login(api_client, phone="+8801722000003", fb_uid="fb_occ_admin")

    target = datetime.now(UTC).date() + timedelta(days=2)
    await api_client.post(
        "/v1/admin/bookings",
        headers=_auth(admin),
        json={
            "venue_id": venue.id,
            "slots": [
                {"start_at": _slot_iso(target, 18)},
                {"start_at": _slot_iso(target, 19)},
            ],
            "payment_collection": "cash",
            "quick_create_phone": "+8801722000098",
        },
    )

    resp = await api_client.get(
        "/v1/admin/reports/occupancy",
        headers=_auth(admin),
        params={
            "from": (datetime.now(UTC).date()).isoformat(),
            "to": (datetime.now(UTC).date() + timedelta(days=5)).isoformat(),
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert any(r["booked_slot_count"] == 2 for r in data["rows"])
    assert any(c["booked_slots"] == 1 for c in data["heatmap"])


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_customer_log_orders_by_spend(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    db_session.add(User(phone="+8801722000004", role=UserRole.ADMIN, manually_created=True))
    await db_session.commit()
    admin = await _login(api_client, phone="+8801722000004", fb_uid="fb_cust_admin")

    target = datetime.now(UTC).date() + timedelta(days=3)
    # Big spender
    await api_client.post(
        "/v1/admin/bookings",
        headers=_auth(admin),
        json={
            "venue_id": venue.id,
            "slots": [
                {"start_at": _slot_iso(target, 16), "price_bdt": 2500},
                {"start_at": _slot_iso(target, 17), "price_bdt": 2500},
            ],
            "payment_collection": "cash",
            "quick_create_phone": "+8801722000050",
        },
    )
    # Small spender
    await api_client.post(
        "/v1/admin/bookings",
        headers=_auth(admin),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 18), "price_bdt": 500}],
            "payment_collection": "cash",
            "quick_create_phone": "+8801722000051",
        },
    )

    resp = await api_client.get(
        "/v1/admin/reports/customers", headers=_auth(admin), params={"sort": "spend"}
    )
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    spends = [r["total_spend_bdt"] for r in rows if r["total_spend_bdt"] > 0]
    assert spends == sorted(spends, reverse=True)
    # Big spender (5000) appears before small spender (500).
    big = next(r for r in rows if r["phone"] == "+8801722000050")
    small = next(r for r in rows if r["phone"] == "+8801722000051")
    assert rows.index(big) < rows.index(small)


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_reports_require_admin_role(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    cust = await _login(api_client, phone="+8801722000005", fb_uid="fb_cust_rep")
    resp = await api_client.get("/v1/admin/reports/revenue", headers=_auth(cust))
    assert resp.status_code == 403
