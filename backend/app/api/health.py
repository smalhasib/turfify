"""Health check endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.db import get_db
from app.redis_client import get_redis

router = APIRouter(tags=["health"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]


class ComponentChecks(BaseModel):
    db: str
    redis: str
    version: str


class HealthResponse(BaseModel):
    status: str
    checks: ComponentChecks


@router.get("/health", status_code=status.HTTP_200_OK, response_model=HealthResponse)
async def health(db: DbDep, redis: RedisDep) -> HealthResponse:
    db_ok = "ok"
    redis_ok = "ok"

    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        db_ok = f"error: {exc.__class__.__name__}"

    try:
        result = redis.ping()
        if hasattr(result, "__await__"):
            await result
    except Exception as exc:  # noqa: BLE001
        redis_ok = f"error: {exc.__class__.__name__}"

    overall = "ok" if db_ok == "ok" and redis_ok == "ok" else "degraded"

    return HealthResponse(
        status=overall,
        checks=ComponentChecks(db=db_ok, redis=redis_ok, version=__version__),
    )
