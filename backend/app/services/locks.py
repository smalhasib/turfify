"""Redis-backed slot locks.

A "hold" reserves a set of slots for one booking attempt. The lock is enforced
by a Lua script that runs server-side and atomically:
  1. inspects every requested slot key,
  2. fails if any key is already held by a different hold token,
  3. otherwise sets every key to the requesting token with the TTL.

This makes multi-slot acquisition all-or-nothing under concurrent contention,
so two users targeting overlapping slot sets cannot both win partial holds.
The Postgres GIST exclusion constraint on `booking_slots` is the second line
of defense: even if Redis state is lost (eviction, crash, or operator drop),
the database refuses to insert overlapping rows.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Iterable
from datetime import UTC, datetime
from typing import Any, Final, cast

from redis.asyncio import Redis

from app.config import get_settings

LOCK_KEY_PREFIX: Final[str] = "lock:slot:"

# Default hold lifetime in seconds. Per the design plan, 8 minutes is the
# pre-payment hold; bKash's tokenized checkout redirect can take 4-6 minutes
# on flaky 3G plus the user's own dithering. 5 minutes was too tight.
DEFAULT_HOLD_TTL_SECONDS: Final[int] = 8 * 60

# Lua: acquire all keys atomically, or none.
#   KEYS = slot keys
#   ARGV[1] = hold token, ARGV[2] = TTL seconds
# Returns 1 on success, 0 on conflict.
_ACQUIRE_LUA: Final[str] = """
local n = #KEYS
for i = 1, n do
  local existing = redis.call('GET', KEYS[i])
  if existing and existing ~= ARGV[1] then
    return 0
  end
end
for i = 1, n do
  redis.call('SET', KEYS[i], ARGV[1], 'EX', ARGV[2])
end
return 1
"""

# Lua: release only the keys still owned by the given token. Idempotent.
_RELEASE_LUA: Final[str] = """
local removed = 0
for i = 1, #KEYS do
  local existing = redis.call('GET', KEYS[i])
  if existing == ARGV[1] then
    redis.call('DEL', KEYS[i])
    removed = removed + 1
  end
end
return removed
"""


class SlotLockConflictError(Exception):
    """Raised when at least one requested slot is already locked by another."""


def make_slot_key(venue_id: int, slot_start_at: datetime) -> str:
    """Stable Redis key for a slot.

    Slots are uniquely identified by `(venue_id, slot_start_at_utc)`. The end
    time is implied by the booking row but the lock granularity is per start.
    """
    if slot_start_at.tzinfo is None:
        raise ValueError("slot_start_at must be timezone-aware")
    iso = slot_start_at.astimezone(UTC).isoformat(timespec="seconds")
    return f"{LOCK_KEY_PREFIX}{venue_id}:{iso}"


def generate_hold_token() -> str:
    """Cryptographic, URL-safe hold token (lock value + DB hold_token)."""
    return secrets.token_urlsafe(24)


def hold_ttl_seconds() -> int:
    """Effective hold TTL. Sourced from settings if a custom value is set
    later; for now the default applies until an admin override exists.
    """
    return DEFAULT_HOLD_TTL_SECONDS


async def acquire_slot_locks(
    redis: Redis,
    *,
    venue_id: int,
    slot_starts: Iterable[datetime],
    hold_token: str,
    ttl_seconds: int | None = None,
) -> None:
    """Atomically lock every slot in the iterable for `hold_token`.

    Raises `SlotLockConflictError` if any slot is already held by a different token.
    Idempotent: re-acquiring with the same token refreshes the TTL.
    """
    keys = [make_slot_key(venue_id, s) for s in slot_starts]
    if not keys:
        return

    ttl = ttl_seconds if ttl_seconds is not None else hold_ttl_seconds()
    result = await cast(Awaitable[Any], redis.eval(_ACQUIRE_LUA, len(keys), *keys, hold_token, ttl))
    if int(result) != 1:
        raise SlotLockConflictError("one_or_more_slots_already_held")


async def release_slot_locks(
    redis: Redis,
    *,
    venue_id: int,
    slot_starts: Iterable[datetime],
    hold_token: str,
) -> int:
    """Release only the slots still owned by `hold_token`. Returns count freed."""
    keys = [make_slot_key(venue_id, s) for s in slot_starts]
    if not keys:
        return 0
    removed = await cast(Awaitable[Any], redis.eval(_RELEASE_LUA, len(keys), *keys, hold_token))
    return int(removed)


# `_settings` is currently unused but keeps the import warm; future config
# (per-venue hold TTL override) will read from it.
_settings = get_settings()
