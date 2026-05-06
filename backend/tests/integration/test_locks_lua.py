"""Direct integration tests for the Redis Lua lock script.

These bypass the API + SQLAlchemy entirely and prove the all-or-nothing
contract of `acquire_slot_locks` against a real Redis testcontainer.
Truly concurrent acquisition is exercised here because Redis async clients
ARE safe to share across coroutines. The corresponding API-level test stops
at sequential conflict because `AsyncSession` would deadlock under
`asyncio.gather`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis

from app.services.locks import (
    SlotLockConflictError,
    acquire_slot_locks,
    generate_hold_token,
    make_slot_key,
    release_slot_locks,
)


def _slot(hour: int) -> datetime:
    base = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    return base + timedelta(hours=hour)


@pytest.mark.integration
async def test_acquire_then_release_round_trip(redis_client: Redis) -> None:
    token = generate_hold_token()
    starts = [_slot(48), _slot(49)]

    await acquire_slot_locks(redis_client, venue_id=1, slot_starts=starts, hold_token=token)
    for s in starts:
        assert await redis_client.get(make_slot_key(1, s)) == token

    freed = await release_slot_locks(redis_client, venue_id=1, slot_starts=starts, hold_token=token)
    assert freed == 2
    for s in starts:
        assert await redis_client.get(make_slot_key(1, s)) is None


@pytest.mark.integration
async def test_acquire_conflict_when_other_token_holds(
    redis_client: Redis,
) -> None:
    starts = [_slot(50)]
    a, b = generate_hold_token(), generate_hold_token()

    await acquire_slot_locks(redis_client, venue_id=1, slot_starts=starts, hold_token=a)
    with pytest.raises(SlotLockConflictError):
        await acquire_slot_locks(redis_client, venue_id=1, slot_starts=starts, hold_token=b)

    # Cleanup.
    await release_slot_locks(redis_client, venue_id=1, slot_starts=starts, hold_token=a)


@pytest.mark.integration
async def test_acquire_is_all_or_nothing(redis_client: Redis) -> None:
    """If ONE of the requested slots is already taken, NONE get locked."""
    a, b = generate_hold_token(), generate_hold_token()

    pre_held = _slot(51)
    requested = [_slot(52), pre_held, _slot(53)]

    await acquire_slot_locks(redis_client, venue_id=1, slot_starts=[pre_held], hold_token=a)

    with pytest.raises(SlotLockConflictError):
        await acquire_slot_locks(redis_client, venue_id=1, slot_starts=requested, hold_token=b)

    # The two slots NOT pre-held by `a` must remain free — the Lua script
    # should not have written them under `b`.
    assert await redis_client.get(make_slot_key(1, _slot(52))) is None
    assert await redis_client.get(make_slot_key(1, _slot(53))) is None
    # The pre-held one is still under token a.
    assert await redis_client.get(make_slot_key(1, pre_held)) == a

    await release_slot_locks(redis_client, venue_id=1, slot_starts=[pre_held], hold_token=a)


@pytest.mark.integration
async def test_concurrent_acquire_only_one_wins(redis_client: Redis) -> None:
    """Two coroutines target the same slot via asyncio.gather. Only one wins.

    This is the core race-condition proof for the booking hold flow. The
    Postgres-level GIST exclusion (covered in test_schema.py) plus this
    Redis-level Lua atomicity together guarantee that even in the worst
    interleaving no two bookings ever hold the same slot.
    """
    starts = [_slot(54)]
    tokens = [generate_hold_token() for _ in range(2)]

    async def attempt(token: str) -> bool:
        try:
            await acquire_slot_locks(redis_client, venue_id=1, slot_starts=starts, hold_token=token)
            return True
        except SlotLockConflictError:
            return False

    results = await asyncio.gather(*[attempt(t) for t in tokens])
    assert results.count(True) == 1
    assert results.count(False) == 1

    # Cleanup using whichever token actually won.
    for token, won in zip(tokens, results, strict=True):
        if won:
            await release_slot_locks(redis_client, venue_id=1, slot_starts=starts, hold_token=token)


@pytest.mark.integration
async def test_acquire_idempotent_for_same_token(redis_client: Redis) -> None:
    """Re-acquiring the same slot with the same token refreshes the TTL
    rather than failing — necessary if a client retries the same hold call.
    """
    token = generate_hold_token()
    starts = [_slot(55)]

    await acquire_slot_locks(
        redis_client, venue_id=1, slot_starts=starts, hold_token=token, ttl_seconds=60
    )
    # Re-acquire shorter TTL — should succeed without raising.
    await acquire_slot_locks(
        redis_client, venue_id=1, slot_starts=starts, hold_token=token, ttl_seconds=30
    )

    ttl = await redis_client.ttl(make_slot_key(1, starts[0]))
    assert 0 < ttl <= 30

    await release_slot_locks(redis_client, venue_id=1, slot_starts=starts, hold_token=token)


@pytest.mark.integration
async def test_release_only_owns_keys(redis_client: Redis) -> None:
    a, b = generate_hold_token(), generate_hold_token()
    shared = [_slot(56)]

    await acquire_slot_locks(redis_client, venue_id=1, slot_starts=shared, hold_token=a)
    # Releasing with the wrong token is a no-op.
    freed = await release_slot_locks(redis_client, venue_id=1, slot_starts=shared, hold_token=b)
    assert freed == 0
    assert await redis_client.get(make_slot_key(1, shared[0])) == a

    # Releasing with the correct token works.
    freed = await release_slot_locks(redis_client, venue_id=1, slot_starts=shared, hold_token=a)
    assert freed == 1
