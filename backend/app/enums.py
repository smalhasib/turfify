"""Enum types used across the domain."""

from enum import StrEnum


class UserRole(StrEnum):
    CUSTOMER = "customer"
    STAFF = "staff"
    ADMIN = "admin"


class ScheduleExceptionType(StrEnum):
    CLOSED = "closed"
    WINDOWS = "windows"


class SlotOverrideReason(StrEnum):
    MAINTENANCE = "maintenance"
    TOURNAMENT = "tournament"
    OFFLINE = "offline"
    HOLIDAY = "holiday"


class DiscountType(StrEnum):
    PERCENT = "percent"
    FLAT = "flat"


class BookingSource(StrEnum):
    WEB = "web"
    ADMIN = "admin"


class PaymentCollection(StrEnum):
    ONLINE = "online"
    CASH = "cash"
    BKASH_MANUAL = "bkash_manual"
    FREE = "free"
    PENDING_OFFLINE = "pending_offline"
    CASH_PENDING = "cash_pending"


class BookingStatus(StrEnum):
    PENDING_PAYMENT = "pending_payment"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AUTO_CANCELLED_NO_PAYMENT = "auto_cancelled_no_payment"
    PAYMENT_RECEIVED_NO_SLOT = "payment_received_no_slot"
    REFUND_PENDING = "refund_pending"
    REFUNDED = "refunded"
    REFUND_FAILED = "refund_failed"
    COMPLETED = "completed"


class PaymentProvider(StrEnum):
    BKASH = "bkash"
    CASH = "cash"
    BKASH_MANUAL = "bkash_manual"


class PaymentStatus(StrEnum):
    INITIATED = "initiated"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    PENDING_OFFLINE = "pending_offline"


class RefundProvider(StrEnum):
    BKASH_API = "bkash_api"
    MANUAL = "manual"


class RefundStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
