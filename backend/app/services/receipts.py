"""PDF receipt generation.

Receipts are generated synchronously on request (no pre-storage). WeasyPrint
renders a Jinja2 HTML template to a single A4 PDF page. Bangla support via
Noto Sans Bengali is wired in CSS — falls back to system fonts if not
installed in the runtime image, which is fine for the latin-only MVP.
"""

from __future__ import annotations

import base64
import io
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import qrcode
from jinja2 import Environment, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from weasyprint import HTML

from app.enums import PaymentCollection
from app.models import Booking, BookingSlot, DiscountCode, User, Venue

_jinja = Environment(
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Receipt {{ booking.public_id }}</title>
<style>
  @page { size: A4; margin: 18mm 16mm; }
  * { box-sizing: border-box; }
  html, body {
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    color: #1a1f1a;
    font-size: 11pt;
  }
  .wrap { max-width: 180mm; }
  .header { display: flex; justify-content: space-between; align-items: flex-start; }
  .brand { font-size: 24pt; font-weight: 800; letter-spacing: -0.02em; color: #1f5d2c; }
  .meta { text-align: right; font-size: 9pt; color: #555; }
  .badge {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 8pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .badge-paid { background: #1f5d2c; color: #ffffff; }
  .badge-pending { background: #d97706; color: #ffffff; }
  .badge-free { background: #555; color: #ffffff; }
  h1 {
    font-size: 18pt;
    font-weight: 700;
    margin: 16px 0 4px;
    text-transform: uppercase;
    letter-spacing: -0.01em;
  }
  .public-id { font-size: 11pt; color: #555; }
  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 18px;
    font-size: 10pt;
  }
  th, td {
    text-align: left;
    padding: 8px 4px;
    border-bottom: 1px solid #d8e0d8;
  }
  th { font-size: 8pt; text-transform: uppercase; letter-spacing: 0.08em; color: #777; }
  td.right, th.right { text-align: right; }
  .totals { margin-top: 12px; width: 50%; margin-left: auto; font-size: 10pt; }
  .totals td { padding: 4px 8px; border: 0; }
  .totals tr.grand td { border-top: 2px solid #1a1f1a; font-weight: 700; font-size: 13pt; padding-top: 8px; }
  .footer {
    margin-top: 28px;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: 16px;
  }
  .policy { font-size: 8.5pt; color: #555; max-width: 110mm; line-height: 1.45; }
  .qr img { width: 90px; height: 90px; }
  .strike { text-decoration: line-through; color: #999; }
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <div>
      <div class="brand">TURFIFY</div>
      <div style="font-size:9pt; color:#555;">
        {{ venue.name }}<br />
        {% if venue.address %}{{ venue.address }}<br />{% endif %}
        {% if venue.contact_phone %}{{ venue.contact_phone }}{% endif %}
      </div>
    </div>
    <div class="meta">
      <span class="badge badge-{{ status_kind }}">{{ status_label }}</span><br />
      Issued {{ issued_at }}<br />
      Booking ID
      <strong>{{ booking.public_id }}</strong>
    </div>
  </div>

  <h1>Receipt</h1>
  <div class="public-id">For {{ user_name }} — {{ user.phone }}</div>

  <table>
    <thead>
      <tr>
        <th>Date</th>
        <th>Time</th>
        <th class="right">Price (BDT)</th>
      </tr>
    </thead>
    <tbody>
      {% for s in slots %}
      <tr>
        <td>{{ s.date }}</td>
        <td>{{ s.time }}</td>
        <td class="right">{{ "{:,}".format(s.price) }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <table class="totals">
    <tr>
      <td>Subtotal</td>
      <td class="right">{{ "{:,}".format(booking.subtotal_bdt) }}</td>
    </tr>
    {% if booking.admin_adjustment_bdt %}
    <tr>
      <td>Adjustment{% if booking.admin_adjustment_reason %} ({{ booking.admin_adjustment_reason }}){% endif %}</td>
      <td class="right">{{ "{:+,}".format(booking.admin_adjustment_bdt) }}</td>
    </tr>
    {% endif %}
    {% if booking.discount_amount_bdt %}
    <tr>
      <td>Discount{% if discount_code %} ({{ discount_code }}){% endif %}</td>
      <td class="right">−{{ "{:,}".format(booking.discount_amount_bdt) }}</td>
    </tr>
    {% endif %}
    <tr class="grand">
      <td>Total</td>
      <td class="right">BDT {{ "{:,}".format(booking.total_amount_bdt) }}</td>
    </tr>
  </table>

  <div class="footer">
    <div class="policy">
      <strong>Payment:</strong> {{ payment_block }}<br />
      <strong>Cancellation:</strong> Full refund &gt; 24h before kickoff. No
      refund within 24h. Cash bookings auto-cancel
      {{ venue.cash_cancel_minutes_before }} minutes before slot start if
      payment isn&apos;t received. Show this receipt at the gate.
    </div>
    <div class="qr">
      <img src="data:image/png;base64,{{ qr_data_uri }}" alt="QR" />
    </div>
  </div>
</div>
</body>
</html>
"""


def _qr_b64_for(url: str) -> str:
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _payment_block(booking: Booking, payment_kind: str) -> str:
    """Human-readable payment line for the receipt footer."""
    coll = booking.payment_collection
    if coll == PaymentCollection.CASH and payment_kind == "paid":
        return "Cash collected at venue."
    if coll == PaymentCollection.CASH_PENDING:
        return "Awaiting cash on arrival. Pay at the gate before kickoff."
    if coll == PaymentCollection.ONLINE:
        return "Online payment (bKash) — see booking page for trxID."
    if coll == PaymentCollection.BKASH_MANUAL:
        return "bKash collected by admin (manual)."
    if coll == PaymentCollection.FREE:
        return f"Complimentary booking. {booking.free_reason or ''}".strip()
    if coll == PaymentCollection.PENDING_OFFLINE:
        return "Awaiting cash collection (admin-created booking)."
    return coll.value


async def render_receipt_pdf(
    db: AsyncSession,
    *,
    booking: Booking,
    base_url: str,
) -> bytes:
    """Return the PDF bytes for the booking. Caller is responsible for
    auth (owner-or-admin) before invoking.
    """
    venue = (await db.execute(select(Venue).where(Venue.id == booking.venue_id))).scalar_one()
    user = (await db.execute(select(User).where(User.id == booking.user_id))).scalar_one()
    slot_rows = (
        (
            await db.execute(
                select(BookingSlot)
                .where(BookingSlot.booking_id == booking.id)
                .order_by(BookingSlot.slot_start_at)
            )
        )
        .scalars()
        .all()
    )

    discount_code = None
    if booking.discount_code_id is not None:
        dc = (
            await db.execute(
                select(DiscountCode).where(DiscountCode.id == booking.discount_code_id)
            )
        ).scalar_one_or_none()
        if dc is not None:
            discount_code = dc.code

    tz = ZoneInfo(venue.timezone)
    slots: list[dict[str, Any]] = []
    for s in slot_rows:
        local_start = s.slot_start_at.astimezone(tz)
        local_end = s.slot_end_at.astimezone(tz)
        slots.append(
            {
                "date": local_start.strftime("%a, %d %b %Y"),
                "time": (f"{local_start.strftime('%I:%M %p')} - {local_end.strftime('%I:%M %p')}"),
                "price": s.price_bdt,
            }
        )

    # Status badge.
    status_kind = "pending"
    status_label = "PENDING"
    if booking.payment_collection in (
        PaymentCollection.CASH,
        PaymentCollection.ONLINE,
        PaymentCollection.BKASH_MANUAL,
    ):
        status_kind = "paid"
        status_label = "PAID"
    elif booking.payment_collection == PaymentCollection.FREE:
        status_kind = "free"
        status_label = "COMPLIMENTARY"

    payment_kind = "paid" if status_kind == "paid" else "unpaid"
    qr_url = f"{base_url.rstrip('/')}/booking/{booking.id}"

    rendered = _jinja.from_string(_TEMPLATE).render(
        booking=booking,
        venue=venue,
        user=user,
        user_name=user.name or "Player",
        slots=slots,
        discount_code=discount_code,
        status_kind=status_kind,
        status_label=status_label,
        payment_block=_payment_block(booking, payment_kind),
        issued_at=datetime.now(tz).strftime("%d %b %Y, %H:%M %Z"),
        qr_data_uri=_qr_b64_for(qr_url),
    )

    pdf_bytes: bytes = HTML(string=rendered, base_url=base_url).write_pdf()
    return pdf_bytes
