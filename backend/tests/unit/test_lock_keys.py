"""Unit tests for the slot lock key formatter + helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.locks import (
    LOCK_KEY_PREFIX,
    generate_hold_token,
    hold_ttl_seconds,
    make_slot_key,
)


@pytest.mark.unit
def test_make_slot_key_uses_utc() -> None:
    dt_dhk = datetime(2026, 5, 12, 19, 0, tzinfo=ZoneInfo("Asia/Dhaka"))
    expected_utc = dt_dhk.astimezone(UTC).isoformat(timespec="seconds")
    key = make_slot_key(1, dt_dhk)
    assert key == f"{LOCK_KEY_PREFIX}1:{expected_utc}"


@pytest.mark.unit
def test_make_slot_key_rejects_naive() -> None:
    with pytest.raises(ValueError):
        make_slot_key(1, datetime(2026, 5, 12, 19, 0))


@pytest.mark.unit
def test_hold_token_is_random_and_long() -> None:
    a = generate_hold_token()
    b = generate_hold_token()
    assert a != b
    # token_urlsafe(24) -> ~32 chars
    assert len(a) >= 30


@pytest.mark.unit
def test_hold_ttl_default() -> None:
    assert hold_ttl_seconds() == 8 * 60
