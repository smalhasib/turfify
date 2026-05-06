"""Authenticated user-self endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.enums import UserRole
from app.security.deps import CurrentUser

router = APIRouter(tags=["me"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


class MeResponse(BaseModel):
    id: int
    phone: str
    name: str | None
    email: str | None
    role: UserRole
    created_at: str


class UpdateMeIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)


@router.get("/me", response_model=MeResponse)
async def read_me(user: CurrentUser) -> MeResponse:
    return MeResponse(
        id=user.id,
        phone=user.phone,
        name=user.name,
        email=user.email,
        role=user.role,
        created_at=user.created_at.isoformat(),
    )


@router.patch("/me", response_model=MeResponse)
async def update_me(payload: UpdateMeIn, user: CurrentUser, db: DbDep) -> MeResponse:
    if payload.name is not None:
        user.name = payload.name
    if payload.email is not None:
        user.email = payload.email or None
        user.email_verified = False  # require re-verification on change
    await db.commit()
    return MeResponse(
        id=user.id,
        phone=user.phone,
        name=user.name,
        email=user.email,
        role=user.role,
        created_at=user.created_at.isoformat(),
    )


@router.delete("/me", status_code=status.HTTP_202_ACCEPTED)
async def request_self_deletion(user: CurrentUser, db: DbDep) -> dict[str, str]:
    """Mark account for deletion. Anonymized after a 30-day cool-off (Phase 12 job)."""
    if user.deletion_requested_at is None:
        user.deletion_requested_at = datetime.now(UTC)
        await db.commit()
    return {"status": "deletion_requested"}
