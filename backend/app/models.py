"""SQLAlchemy 2.0 declarative models for the Turfify domain."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, ExcludeConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.enums import (
    BookingSource,
    BookingStatus,
    DiscountType,
    PaymentCollection,
    PaymentProvider,
    PaymentStatus,
    RefundProvider,
    RefundStatus,
    ScheduleExceptionType,
    SlotOverrideReason,
    UserRole,
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


def _pg_enum(enum_cls: type, name: str) -> Enum:
    """Create a Postgres ENUM column type for a Python enum class."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=True,
        create_type=True,
        values_callable=lambda x: [m.value for m in x],
    )


# ---------------------------------------------------------------------------
# Venue
# ---------------------------------------------------------------------------


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    contact_phone: Mapped[str | None] = mapped_column(String(20))

    open_hour: Mapped[int] = mapped_column(SmallInteger, default=6, nullable=False)
    close_hour: Mapped[int] = mapped_column(SmallInteger, default=24, nullable=False)
    slot_duration_min: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    advance_book_days: Mapped[int] = mapped_column(Integer, default=14, nullable=False)
    cutoff_min: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    base_price_bdt: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    cash_cancel_minutes_before: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    cancellation_full_refund_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Dhaka", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("open_hour >= 0 AND open_hour <= 24", name="ck_venue_open_hour"),
        CheckConstraint("close_hour >= 0 AND close_hour <= 30", name="ck_venue_close_hour"),
        CheckConstraint("slot_duration_min > 0", name="ck_venue_slot_duration"),
        CheckConstraint("base_price_bdt >= 0", name="ck_venue_base_price"),
    )


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    firebase_uid: Mapped[str | None] = mapped_column(String(128), unique=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    role: Mapped[UserRole] = mapped_column(
        _pg_enum(UserRole, "user_role"), default=UserRole.CUSTOMER, nullable=False
    )

    manually_created: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_admin_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    no_show_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cash_disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (CheckConstraint("no_show_count >= 0", name="ck_user_no_show_count"),)


# ---------------------------------------------------------------------------
# Schedule exceptions & slot overrides
# ---------------------------------------------------------------------------


class ScheduleException(Base):
    __tablename__ = "schedule_exceptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    venue_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("venues.id", ondelete="CASCADE"), nullable=False
    )
    exception_date: Mapped[date] = mapped_column(Date, nullable=False)
    type: Mapped[ScheduleExceptionType] = mapped_column(
        _pg_enum(ScheduleExceptionType, "schedule_exception_type"), nullable=False
    )
    windows: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    slot_duration_min: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("venue_id", "exception_date", name="uq_schedule_exception_per_date"),
    )


class SlotOverride(Base):
    __tablename__ = "slot_overrides"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    venue_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("venues.id", ondelete="CASCADE"), nullable=False
    )
    slot_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    slot_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[SlotOverrideReason] = mapped_column(
        _pg_enum(SlotOverrideReason, "slot_override_reason"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("slot_end_at > slot_start_at", name="ck_slot_override_range"),
        Index("ix_slot_override_venue_start", "venue_id", "slot_start_at"),
    )


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


class PricingRule(Base):
    __tablename__ = "pricing_rules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    venue_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("venues.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    day_of_week: Mapped[int | None] = mapped_column(SmallInteger)  # 0-6 or NULL = any
    hour_start: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    hour_end: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    date_start: Mapped[date | None] = mapped_column(Date)
    date_end: Mapped[date | None] = mapped_column(Date)
    price_bdt: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("hour_end > hour_start", name="ck_pricing_rule_hours"),
        CheckConstraint(
            "day_of_week IS NULL OR (day_of_week BETWEEN 0 AND 6)",
            name="ck_pricing_rule_dow",
        ),
        CheckConstraint("price_bdt >= 0", name="ck_pricing_rule_price"),
        Index("ix_pricing_rule_venue_active", "venue_id", "is_active", "priority"),
    )


# ---------------------------------------------------------------------------
# Discount codes
# ---------------------------------------------------------------------------


class DiscountCode(Base):
    __tablename__ = "discount_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    type: Mapped[DiscountType] = mapped_column(
        _pg_enum(DiscountType, "discount_type"), nullable=False
    )
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    min_amount_bdt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_discount_bdt: Mapped[int | None] = mapped_column(Integer)
    usage_limit_total: Mapped[int | None] = mapped_column(Integer)
    usage_limit_per_user: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    applies_to: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("valid_until > valid_from", name="ck_discount_validity"),
        CheckConstraint("value > 0", name="ck_discount_value"),
        CheckConstraint(
            "(type = 'percent' AND value <= 100) OR (type = 'flat')",
            name="ck_discount_percent_max",
        ),
    )


class DiscountRedemption(Base):
    __tablename__ = "discount_redemptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    discount_code_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("discount_codes.id", ondelete="CASCADE"), nullable=False
    )
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    amount_off_bdt: Mapped[int] = mapped_column(Integer, nullable=False)
    voided: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("discount_code_id", "booking_id", name="uq_discount_per_booking"),
        Index("ix_discount_redemption_user_code", "user_id", "discount_code_id"),
    )


# ---------------------------------------------------------------------------
# Bookings & slots
# ---------------------------------------------------------------------------


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    venue_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("venues.id", ondelete="RESTRICT"), nullable=False
    )

    booking_source: Mapped[BookingSource] = mapped_column(
        _pg_enum(BookingSource, "booking_source"),
        default=BookingSource.WEB,
        nullable=False,
    )
    created_by_admin_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    payment_collection: Mapped[PaymentCollection] = mapped_column(
        _pg_enum(PaymentCollection, "payment_collection"), nullable=False
    )

    subtotal_bdt: Mapped[int] = mapped_column(Integer, nullable=False)
    admin_adjustment_bdt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    admin_adjustment_reason: Mapped[str | None] = mapped_column(Text)
    discount_code_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("discount_codes.id", ondelete="SET NULL")
    )
    discount_amount_bdt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_amount_bdt: Mapped[int] = mapped_column(Integer, nullable=False)

    slot_count: Mapped[int] = mapped_column(Integer, nullable=False)
    first_slot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_slot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[BookingStatus] = mapped_column(
        _pg_enum(BookingStatus, "booking_status"), nullable=False
    )

    hold_token: Mapped[str | None] = mapped_column(String(64))
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cutoff_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    free_reason: Mapped[str | None] = mapped_column(Text)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refund_amount_bdt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    slots: Mapped[list[BookingSlot]] = relationship(
        "BookingSlot", back_populates="booking", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("slot_count > 0", name="ck_booking_slot_count"),
        CheckConstraint("total_amount_bdt >= 0", name="ck_booking_total"),
        CheckConstraint("subtotal_bdt >= 0", name="ck_booking_subtotal"),
        CheckConstraint("last_slot_at >= first_slot_at", name="ck_booking_slot_range"),
        Index("ix_booking_user_created", "user_id", "created_at"),
        Index("ix_booking_venue_first_slot", "venue_id", "first_slot_at"),
        Index(
            "ix_booking_pending_hold",
            "status",
            "hold_expires_at",
            postgresql_where=(status == BookingStatus.PENDING_PAYMENT),
        ),
    )


class BookingSlot(Base):
    __tablename__ = "booking_slots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
    )
    venue_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("venues.id", ondelete="RESTRICT"), nullable=False
    )
    slot_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    slot_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_bdt: Mapped[int] = mapped_column(Integer, nullable=False)
    price_overridden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Denormalized from bookings.status. Kept in sync by a Postgres trigger so
    # the partial GIST exclusion constraint below can reference it directly.
    booking_status: Mapped[BookingStatus] = mapped_column(
        _pg_enum(BookingStatus, "booking_status"), nullable=False
    )

    booking: Mapped[Booking] = relationship("Booking", back_populates="slots")

    __table_args__ = (
        CheckConstraint("slot_end_at > slot_start_at", name="ck_booking_slot_range"),
        CheckConstraint("price_bdt >= 0", name="ck_booking_slot_price"),
        Index("ix_booking_slot_start", "slot_start_at"),
        Index("ix_booking_slot_venue_start", "venue_id", "slot_start_at"),
        ExcludeConstraint(
            ("venue_id", "="),
            (func.tstzrange(text("slot_start_at"), text("slot_end_at"), "[)"), "&&"),
            name="ex_booking_slot_no_overlap",
            using="gist",
            where=text("booking_status IN ('pending_payment', 'confirmed')"),
        ),
    )


# ---------------------------------------------------------------------------
# Payments & refunds
# ---------------------------------------------------------------------------


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[PaymentProvider] = mapped_column(
        _pg_enum(PaymentProvider, "payment_provider"), nullable=False
    )
    provider_payment_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    provider_txn_id: Mapped[str | None] = mapped_column(String(128))
    manual_trx_id: Mapped[str | None] = mapped_column(String(128))
    collected_by_admin_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )

    amount_bdt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        _pg_enum(PaymentStatus, "payment_status"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    raw_request: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("amount_bdt >= 0", name="ck_payment_amount"),
        Index("ix_payment_status_completed", "status", "completed_at"),
    )


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    payment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False
    )
    amount_bdt: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[RefundProvider] = mapped_column(
        _pg_enum(RefundProvider, "refund_provider"), nullable=False
    )
    provider_refund_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[RefundStatus] = mapped_column(
        _pg_enum(RefundStatus, "refund_status"), nullable=False
    )
    requested_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("amount_bdt >= 0", name="ck_refund_amount"),)


# ---------------------------------------------------------------------------
# Audit log & outbound message queue
# ---------------------------------------------------------------------------


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_log_actor_created", "actor_user_id", "created_at"),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )


class OutboundMessage(Base):
    """Email / future SMS outbound queue. Empty in MVP; activated in Phase 2."""

    __tablename__ = "outbound_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    to_address: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(500))
    body_html: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = [
    "Base",
    "Venue",
    "User",
    "ScheduleException",
    "SlotOverride",
    "PricingRule",
    "DiscountCode",
    "DiscountRedemption",
    "Booking",
    "BookingSlot",
    "Payment",
    "Refund",
    "AuditLog",
    "OutboundMessage",
]


# Suppress unused-import warning for TSTZRANGE (Alembic introspects it)
_ = TSTZRANGE
