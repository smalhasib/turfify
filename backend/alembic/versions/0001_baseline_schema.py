"""Baseline schema for Phase 1.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-06

Creates:
- btree_gist extension (required for the booking_slots GIST exclusion).
- All Postgres ENUM types.
- All 13 tables with constraints and indexes per Turf_Management_Plan.md.
- Trigger that mirrors `bookings.status` onto `booking_slots.booking_status`
  so the partial GIST exclusion can run in pure SQL.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Enum value lists (kept as plain strings to keep the migration self-contained
# and avoid importing the live enum module here).
_USER_ROLE = ("customer", "staff", "admin")
_SCHEDULE_EXCEPTION_TYPE = ("closed", "windows")
_SLOT_OVERRIDE_REASON = ("maintenance", "tournament", "offline", "holiday")
_DISCOUNT_TYPE = ("percent", "flat")
_BOOKING_SOURCE = ("web", "admin")
_PAYMENT_COLLECTION = (
    "online",
    "cash",
    "bkash_manual",
    "free",
    "pending_offline",
    "cash_pending",
)
_BOOKING_STATUS = (
    "pending_payment",
    "confirmed",
    "expired",
    "failed",
    "cancelled",
    "auto_cancelled_no_payment",
    "payment_received_no_slot",
    "refund_pending",
    "refunded",
    "refund_failed",
    "completed",
)
_PAYMENT_PROVIDER = ("bkash", "cash", "bkash_manual")
_PAYMENT_STATUS = ("initiated", "completed", "failed", "refunded", "pending_offline")
_REFUND_PROVIDER = ("bkash_api", "manual")
_REFUND_STATUS = ("pending", "completed", "failed")


def upgrade() -> None:
    # ------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # ------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------
    user_role = postgresql.ENUM(*_USER_ROLE, name="user_role")
    schedule_exception_type = postgresql.ENUM(
        *_SCHEDULE_EXCEPTION_TYPE, name="schedule_exception_type"
    )
    slot_override_reason = postgresql.ENUM(*_SLOT_OVERRIDE_REASON, name="slot_override_reason")
    discount_type = postgresql.ENUM(*_DISCOUNT_TYPE, name="discount_type")
    booking_source = postgresql.ENUM(*_BOOKING_SOURCE, name="booking_source")
    payment_collection = postgresql.ENUM(*_PAYMENT_COLLECTION, name="payment_collection")
    booking_status = postgresql.ENUM(*_BOOKING_STATUS, name="booking_status")
    payment_provider = postgresql.ENUM(*_PAYMENT_PROVIDER, name="payment_provider")
    payment_status = postgresql.ENUM(*_PAYMENT_STATUS, name="payment_status")
    refund_provider = postgresql.ENUM(*_REFUND_PROVIDER, name="refund_provider")
    refund_status = postgresql.ENUM(*_REFUND_STATUS, name="refund_status")

    bind = op.get_bind()
    for enum in (
        user_role,
        schedule_exception_type,
        slot_override_reason,
        discount_type,
        booking_source,
        payment_collection,
        booking_status,
        payment_provider,
        payment_status,
        refund_provider,
        refund_status,
    ):
        enum.create(bind, checkfirst=True)

    # ------------------------------------------------------------
    # venues
    # ------------------------------------------------------------
    op.create_table(
        "venues",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.Text),
        sa.Column("contact_phone", sa.String(20)),
        sa.Column("open_hour", sa.SmallInteger, nullable=False, server_default="6"),
        sa.Column("close_hour", sa.SmallInteger, nullable=False, server_default="24"),
        sa.Column("slot_duration_min", sa.Integer, nullable=False, server_default="60"),
        sa.Column("advance_book_days", sa.Integer, nullable=False, server_default="14"),
        sa.Column("cutoff_min", sa.Integer, nullable=False, server_default="30"),
        sa.Column("base_price_bdt", sa.Integer, nullable=False, server_default="1000"),
        sa.Column("cash_cancel_minutes_before", sa.Integer, nullable=False, server_default="15"),
        sa.Column(
            "cancellation_full_refund_hours",
            sa.Integer,
            nullable=False,
            server_default="24",
        ),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Dhaka"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("open_hour >= 0 AND open_hour <= 24", name="ck_venue_open_hour"),
        sa.CheckConstraint("close_hour >= 0 AND close_hour <= 30", name="ck_venue_close_hour"),
        sa.CheckConstraint("slot_duration_min > 0", name="ck_venue_slot_duration"),
        sa.CheckConstraint("base_price_bdt >= 0", name="ck_venue_base_price"),
    )

    # ------------------------------------------------------------
    # users (self-referential FK created_by_admin_id)
    # ------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("firebase_uid", sa.String(128), unique=True),
        sa.Column("phone", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(200)),
        sa.Column("email", sa.String(320), unique=True),
        sa.Column("email_verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "role",
            postgresql.ENUM(*_USER_ROLE, name="user_role", create_type=False),
            nullable=False,
            server_default="customer",
        ),
        sa.Column("manually_created", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_by_admin_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("no_show_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cash_disabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("no_show_count >= 0", name="ck_user_no_show_count"),
    )

    # ------------------------------------------------------------
    # schedule_exceptions
    # ------------------------------------------------------------
    op.create_table(
        "schedule_exceptions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "venue_id",
            sa.BigInteger,
            sa.ForeignKey("venues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("exception_date", sa.Date, nullable=False),
        sa.Column(
            "type",
            postgresql.ENUM(
                *_SCHEDULE_EXCEPTION_TYPE, name="schedule_exception_type", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("windows", postgresql.JSONB),
        sa.Column("slot_duration_min", sa.Integer),
        sa.Column("reason", sa.Text),
        sa.Column("note", sa.Text),
        sa.Column(
            "created_by",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("venue_id", "exception_date", name="uq_schedule_exception_per_date"),
    )

    # ------------------------------------------------------------
    # slot_overrides
    # ------------------------------------------------------------
    op.create_table(
        "slot_overrides",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "venue_id",
            sa.BigInteger,
            sa.ForeignKey("venues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slot_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("slot_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "reason",
            postgresql.ENUM(*_SLOT_OVERRIDE_REASON, name="slot_override_reason", create_type=False),
            nullable=False,
        ),
        sa.Column("note", sa.Text),
        sa.Column(
            "created_by",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("slot_end_at > slot_start_at", name="ck_slot_override_range"),
    )
    op.create_index("ix_slot_override_venue_start", "slot_overrides", ["venue_id", "slot_start_at"])

    # ------------------------------------------------------------
    # pricing_rules
    # ------------------------------------------------------------
    op.create_table(
        "pricing_rules",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "venue_id",
            sa.BigInteger,
            sa.ForeignKey("venues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("day_of_week", sa.SmallInteger),
        sa.Column("hour_start", sa.SmallInteger, nullable=False),
        sa.Column("hour_end", sa.SmallInteger, nullable=False),
        sa.Column("date_start", sa.Date),
        sa.Column("date_end", sa.Date),
        sa.Column("price_bdt", sa.Integer, nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("hour_end > hour_start", name="ck_pricing_rule_hours"),
        sa.CheckConstraint(
            "day_of_week IS NULL OR (day_of_week BETWEEN 0 AND 6)",
            name="ck_pricing_rule_dow",
        ),
        sa.CheckConstraint("price_bdt >= 0", name="ck_pricing_rule_price"),
    )
    op.create_index(
        "ix_pricing_rule_venue_active",
        "pricing_rules",
        ["venue_id", "is_active", "priority"],
    )

    # ------------------------------------------------------------
    # discount_codes
    # ------------------------------------------------------------
    op.create_table(
        "discount_codes",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "type",
            postgresql.ENUM(*_DISCOUNT_TYPE, name="discount_type", create_type=False),
            nullable=False,
        ),
        sa.Column("value", sa.Integer, nullable=False),
        sa.Column("min_amount_bdt", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_discount_bdt", sa.Integer),
        sa.Column("usage_limit_total", sa.Integer),
        sa.Column("usage_limit_per_user", sa.Integer, nullable=False, server_default="1"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("applies_to", postgresql.JSONB),
        sa.Column(
            "created_by",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("valid_until > valid_from", name="ck_discount_validity"),
        sa.CheckConstraint("value > 0", name="ck_discount_value"),
        sa.CheckConstraint(
            "(type = 'percent' AND value <= 100) OR (type = 'flat')",
            name="ck_discount_percent_max",
        ),
    )

    # ------------------------------------------------------------
    # bookings (FK to discount_codes ok; FK to itself ok)
    # ------------------------------------------------------------
    op.create_table(
        "bookings",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.String(32), nullable=False, unique=True),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "venue_id",
            sa.BigInteger,
            sa.ForeignKey("venues.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "booking_source",
            postgresql.ENUM(*_BOOKING_SOURCE, name="booking_source", create_type=False),
            nullable=False,
            server_default="web",
        ),
        sa.Column(
            "created_by_admin_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "payment_collection",
            postgresql.ENUM(*_PAYMENT_COLLECTION, name="payment_collection", create_type=False),
            nullable=False,
        ),
        sa.Column("subtotal_bdt", sa.Integer, nullable=False),
        sa.Column("admin_adjustment_bdt", sa.Integer, nullable=False, server_default="0"),
        sa.Column("admin_adjustment_reason", sa.Text),
        sa.Column(
            "discount_code_id",
            sa.BigInteger,
            sa.ForeignKey("discount_codes.id", ondelete="SET NULL"),
        ),
        sa.Column("discount_amount_bdt", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_amount_bdt", sa.Integer, nullable=False),
        sa.Column("slot_count", sa.Integer, nullable=False),
        sa.Column("first_slot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_slot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*_BOOKING_STATUS, name="booking_status", create_type=False),
            nullable=False,
        ),
        sa.Column("hold_token", sa.String(64)),
        sa.Column("hold_expires_at", sa.DateTime(timezone=True)),
        sa.Column("cutoff_override", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("free_reason", sa.Text),
        sa.Column("cancellation_reason", sa.Text),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("refund_amount_bdt", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("slot_count > 0", name="ck_booking_slot_count"),
        sa.CheckConstraint("total_amount_bdt >= 0", name="ck_booking_total"),
        sa.CheckConstraint("subtotal_bdt >= 0", name="ck_booking_subtotal"),
        sa.CheckConstraint("last_slot_at >= first_slot_at", name="ck_booking_slot_range"),
    )
    op.create_index("ix_booking_user_created", "bookings", ["user_id", "created_at"])
    op.create_index("ix_booking_venue_first_slot", "bookings", ["venue_id", "first_slot_at"])
    op.create_index(
        "ix_booking_pending_hold",
        "bookings",
        ["status", "hold_expires_at"],
        postgresql_where=sa.text("status = 'pending_payment'"),
    )

    # ------------------------------------------------------------
    # booking_slots (with denormalized booking_status + GIST exclusion)
    # ------------------------------------------------------------
    op.create_table(
        "booking_slots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "booking_id",
            sa.BigInteger,
            sa.ForeignKey("bookings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "venue_id",
            sa.BigInteger,
            sa.ForeignKey("venues.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("slot_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("slot_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_bdt", sa.Integer, nullable=False),
        sa.Column(
            "price_overridden",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "booking_status",
            postgresql.ENUM(*_BOOKING_STATUS, name="booking_status", create_type=False),
            nullable=False,
        ),
        sa.CheckConstraint("slot_end_at > slot_start_at", name="ck_booking_slot_range"),
        sa.CheckConstraint("price_bdt >= 0", name="ck_booking_slot_price"),
    )
    op.create_index("ix_booking_slot_start", "booking_slots", ["slot_start_at"])
    op.create_index("ix_booking_slot_venue_start", "booking_slots", ["venue_id", "slot_start_at"])

    # GIST exclusion: same venue + overlapping time range, only when slot is held.
    op.execute(
        """
        ALTER TABLE booking_slots
        ADD CONSTRAINT ex_booking_slot_no_overlap
        EXCLUDE USING gist (
            venue_id WITH =,
            tstzrange(slot_start_at, slot_end_at, '[)') WITH &&
        )
        WHERE (booking_status IN ('pending_payment', 'confirmed'))
        """
    )

    # Trigger: bookings.status changes -> booking_slots.booking_status synced.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sync_booking_slot_status() RETURNS trigger AS $$
        BEGIN
            IF (TG_OP = 'UPDATE' AND OLD.status IS DISTINCT FROM NEW.status) THEN
                UPDATE booking_slots
                   SET booking_status = NEW.status
                 WHERE booking_id = NEW.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sync_booking_slot_status
        AFTER UPDATE ON bookings
        FOR EACH ROW
        EXECUTE FUNCTION sync_booking_slot_status();
        """
    )

    # ------------------------------------------------------------
    # discount_redemptions (FKs to discount_codes, bookings, users)
    # ------------------------------------------------------------
    op.create_table(
        "discount_redemptions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "discount_code_id",
            sa.BigInteger,
            sa.ForeignKey("discount_codes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "booking_id",
            sa.BigInteger,
            sa.ForeignKey("bookings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount_off_bdt", sa.Integer, nullable=False),
        sa.Column("voided", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "redeemed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("discount_code_id", "booking_id", name="uq_discount_per_booking"),
    )
    op.create_index(
        "ix_discount_redemption_user_code",
        "discount_redemptions",
        ["user_id", "discount_code_id"],
    )

    # ------------------------------------------------------------
    # payments
    # ------------------------------------------------------------
    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "booking_id",
            sa.BigInteger,
            sa.ForeignKey("bookings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider",
            postgresql.ENUM(*_PAYMENT_PROVIDER, name="payment_provider", create_type=False),
            nullable=False,
        ),
        sa.Column("provider_payment_id", sa.String(128), unique=True),
        sa.Column("provider_txn_id", sa.String(128)),
        sa.Column("manual_trx_id", sa.String(128)),
        sa.Column(
            "collected_by_admin_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("amount_bdt", sa.Integer, nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*_PAYMENT_STATUS, name="payment_status", create_type=False),
            nullable=False,
        ),
        sa.Column("attempt_no", sa.Integer, nullable=False, server_default="1"),
        sa.Column("raw_request", postgresql.JSONB),
        sa.Column("raw_response", postgresql.JSONB),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount_bdt >= 0", name="ck_payment_amount"),
    )
    op.create_index("ix_payment_status_completed", "payments", ["status", "completed_at"])

    # ------------------------------------------------------------
    # refunds
    # ------------------------------------------------------------
    op.create_table(
        "refunds",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "payment_id",
            sa.BigInteger,
            sa.ForeignKey("payments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount_bdt", sa.Integer, nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column(
            "provider",
            postgresql.ENUM(*_REFUND_PROVIDER, name="refund_provider", create_type=False),
            nullable=False,
        ),
        sa.Column("provider_refund_id", sa.String(128)),
        sa.Column(
            "status",
            postgresql.ENUM(*_REFUND_STATUS, name="refund_status", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "requested_by",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount_bdt >= 0", name="ck_refund_amount"),
    )

    # ------------------------------------------------------------
    # audit_log
    # ------------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "actor_user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(64)),
        sa.Column("entity_id", sa.BigInteger),
        sa.Column("before", postgresql.JSONB),
        sa.Column("after", postgresql.JSONB),
        sa.Column("ip", sa.String(64)),
        sa.Column("user_agent", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_audit_log_actor_created", "audit_log", ["actor_user_id", "created_at"])
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"])

    # ------------------------------------------------------------
    # outbound_messages (Phase 2 email queue, empty in MVP)
    # ------------------------------------------------------------
    op.create_table(
        "outbound_messages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("to_address", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(500)),
        sa.Column("body_html", sa.Text),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_sync_booking_slot_status ON bookings")
    op.execute("DROP FUNCTION IF EXISTS sync_booking_slot_status()")

    op.drop_table("outbound_messages")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_created", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("refunds")
    op.drop_index("ix_payment_status_completed", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_discount_redemption_user_code", table_name="discount_redemptions")
    op.drop_table("discount_redemptions")
    op.drop_index("ix_booking_slot_venue_start", table_name="booking_slots")
    op.drop_index("ix_booking_slot_start", table_name="booking_slots")
    op.drop_table("booking_slots")
    op.drop_index("ix_booking_pending_hold", table_name="bookings")
    op.drop_index("ix_booking_venue_first_slot", table_name="bookings")
    op.drop_index("ix_booking_user_created", table_name="bookings")
    op.drop_table("bookings")
    op.drop_table("discount_codes")
    op.drop_index("ix_pricing_rule_venue_active", table_name="pricing_rules")
    op.drop_table("pricing_rules")
    op.drop_index("ix_slot_override_venue_start", table_name="slot_overrides")
    op.drop_table("slot_overrides")
    op.drop_table("schedule_exceptions")
    op.drop_table("users")
    op.drop_table("venues")

    for enum_name in (
        "refund_status",
        "refund_provider",
        "payment_status",
        "payment_provider",
        "booking_status",
        "payment_collection",
        "booking_source",
        "discount_type",
        "slot_override_reason",
        "schedule_exception_type",
        "user_role",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
