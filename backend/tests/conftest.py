"""Shared pytest fixtures.

Integration tests spin up real Postgres + Redis via testcontainers.
Unit tests have no I/O and use no fixtures from here.
"""

from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis, from_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from app.db import get_db
from app.main import app
from app.redis_client import get_redis


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer]:
    """Spin up Postgres for the test session."""
    with PostgresContainer("postgres:15-alpine", driver="asyncpg") as pg:
        yield pg


@pytest.fixture(scope="session")
def redis_container() -> Generator[RedisContainer]:
    """Spin up Redis for the test session."""
    with RedisContainer("redis:7-alpine") as r:
        yield r


@pytest_asyncio.fixture(scope="session")
async def test_engine(postgres_container: PostgresContainer) -> AsyncGenerator[Any]:
    """Build an async engine and apply Alembic migrations once per session."""
    import os

    from alembic.config import Config

    from alembic import command

    url = postgres_container.get_connection_url()
    engine = create_async_engine(url, echo=False, pool_pre_ping=True)

    sync_url = url.replace("+asyncpg", "+psycopg")
    os.environ["ALEMBIC_DATABASE_URL"] = sync_url
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(cfg, "head")

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine: Any) -> AsyncGenerator[AsyncSession]:
    factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def clean_db(test_engine: Any) -> AsyncGenerator[None]:
    """Truncate data tables after each test to keep tests isolated."""
    from sqlalchemy import text

    yield
    tables = [
        "discount_redemptions",
        "refunds",
        "payments",
        "booking_slots",
        "bookings",
        "discount_codes",
        "pricing_rules",
        "slot_overrides",
        "schedule_exceptions",
        "audit_log",
        "outbound_messages",
        "users",
        "venues",
    ]
    async with test_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def redis_client(
    redis_container: RedisContainer,
) -> AsyncGenerator[Redis]:
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    client = from_url(f"redis://{host}:{port}/0", decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession, redis_client: Redis) -> AsyncGenerator[AsyncClient]:
    """HTTP client wired to override DB + Redis dependencies with test fixtures."""

    async def _db_override() -> AsyncGenerator[AsyncSession]:
        yield db_session

    async def _redis_override() -> Redis:
        return redis_client

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[get_redis] = _redis_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
