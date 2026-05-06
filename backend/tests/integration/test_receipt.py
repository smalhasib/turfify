"""Integration tests for the PDF receipt endpoint."""

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
    venue = Venue(name="Receipt Venue", contact_phone="+8801999999999")
    db.add(venue)
    await db.flush()
    return venue


def _next_weekday() -> date:
    today = datetime.now(UTC).date()
    delta = (5 - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def _slot_iso(day: date, hour: int) -> str:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=DHK).astimezone(UTC).isoformat()


async def _login(api_client: AsyncClient, *, phone: str, fb_uid: str) -> str:
    def fake_verifier(_token: str) -> dict[str, Any]:
        return {"uid": fb_uid, "phone_number": phone}

    app.dependency_overrides[get_firebase_verifier] = lambda: fake_verifier
    try:
        resp = await api_client.post("/v1/auth/firebase", json={"id_token": "x" * 40})
        return resp.json()["access_token"]
    finally:
        app.dependency_overrides.pop(get_firebase_verifier, None)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_receipt_returns_pdf_for_owner(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()

    access = await _login(api_client, phone="+8801719000001", fb_uid="fb_pdf_owner")
    target = _next_weekday()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 19)}],
            "payment_method": "cash",
        },
    )
    booking_id = hold.json()["booking_id"]

    resp = await api_client.get(f"/v1/bookings/{booking_id}/receipt.pdf", headers=_auth(access))
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"].startswith("attachment;")
    body = resp.content
    assert body.startswith(b"%PDF-")
    assert len(body) > 2000  # sanity: more than a stub PDF


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_receipt_404_for_other_user(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    await db_session.commit()

    owner = await _login(api_client, phone="+8801719000002", fb_uid="fb_pdf_o2")
    intruder = await _login(api_client, phone="+8801719000003", fb_uid="fb_pdf_int")
    target = _next_weekday()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(owner),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 17)}],
            "payment_method": "cash",
        },
    )
    booking_id = hold.json()["booking_id"]

    resp = await api_client.get(f"/v1/bookings/{booking_id}/receipt.pdf", headers=_auth(intruder))
    assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_receipt_admin_can_download_anyones(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    venue = await _make_venue(db_session)
    db_session.add(User(phone="+8801719000004", role=UserRole.ADMIN, manually_created=True))
    await db_session.commit()

    cust_access = await _login(api_client, phone="+8801719000005", fb_uid="fb_pdf_cust")
    target = _next_weekday()
    hold = await api_client.post(
        "/v1/bookings/hold",
        headers=_auth(cust_access),
        json={
            "venue_id": venue.id,
            "slots": [{"start_at": _slot_iso(target, 18)}],
            "payment_method": "cash",
        },
    )
    booking_id = hold.json()["booking_id"]

    admin_access = await _login(api_client, phone="+8801719000004", fb_uid="fb_pdf_admin")
    resp = await api_client.get(
        f"/v1/bookings/{booking_id}/receipt.pdf", headers=_auth(admin_access)
    )
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF-")


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_receipt_requires_auth(api_client: AsyncClient, db_session: AsyncSession) -> None:
    resp = await api_client.get("/v1/bookings/1/receipt.pdf")
    assert resp.status_code == 401
