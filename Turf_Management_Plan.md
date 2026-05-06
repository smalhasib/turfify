# Turf Management & Booking Platform — Implementation Plan

**Status:** Pre-implementation reference. All design decisions locked through grilling sessions. Source of truth before any code is written.

**Companion docs:**
- `Turf_Management_System_Requirements.md` — original PRD
- `Turf_Management_Cost_Estimation.md` — annual cost breakdown

---

## 1. Scope & Objectives

### 1.1 Business Model
- Hourly rentals of a single sports turf in Bangladesh (default BDT 1,000/hour, dynamic).
- Mobile-first user base, 500–1,000 daily active users target.
- Phone-based identity (Firebase OTP), bKash-first payments.

### 1.2 MVP Goal
A bookable, payable, refundable platform with admin controls for slot management, pricing, walk-in bookings, refunds, and reporting. Schema designed to extend to multi-venue, multi-payment-provider, multi-language without migration pain.

### 1.3 MVP Cut Decisions
- **Single venue** (schema includes `venue_id` FK throughout for future expansion)
- **bKash only** (provider abstraction allows Nagad / Rocket / cards in Phase 3)
- **English UI only** (Bangla deferred Phase 2; Bengali-supporting font preloaded for receipts)
- **No SMS notifications** (booking status visible in-app; email groundwork laid for Phase 2)
- **No multi-day "event package" curation by admin** (users CAN book slots across multiple days in one cart; no admin-published tournament packages)

---

## 2. Technical Stack

| Layer | Choice | Rationale |
|---|---|---|
| Frontend | Next.js (React) | SSR for SEO, image optimization, route groups for `/admin`, Vercel-native |
| Backend | FastAPI (Python) | Async-native (Redis locks + webhooks), Pydantic validation kills XSS/injection at boundary, OpenAPI auto-doc |
| Database | PostgreSQL 15+ | Relational integrity, GIST exclusion constraints for slot booking, JSONB for flexible payloads |
| Cache / Locks | Redis 7+ | Atomic SETNX with TTL for slot holds, JWT refresh token store, rate-limit counters |
| Reverse Proxy | nginx | HTTP/2, mature BD ops familiarity |
| Edge | Cloudflare | DDoS mitigation, HTTP/3 to client, Origin Certificate (15-year cert, no rotation) |
| Frontend Hosting | Vercel (free tier) | Edge CDN, image optimization, GitHub-native deploys |
| Backend Hosting | VPS (1 core, 2GB RAM, IP `103.174.51.125`) | Existing infrastructure |
| Auth | Firebase Phone Authentication | OTP send/verify, brute-force protection, reCAPTCHA, free up to 10k verifications/month |
| Payment | bKash PGW Tokenized Checkout | Direct merchant integration, lower fees than aggregators |
| PDF | WeasyPrint | HTML/CSS to PDF, no headless browser, Bangla unicode support via Noto Sans Bengali |
| Charts | Recharts | React-native, lightweight, accessible |
| Containerization | Docker Compose | Reproducible builds, easy rollback |
| Migrations | Alembic | Auto-generated from SQLAlchemy models |
| Error Tracking | Sentry | Free tier 5k events/month |
| Uptime | HetrixTools | Free tier 50 monitors, multi-region (multiple POPs catch BD routing issues) |
| Email Provider | (None MVP) | Resend interface stubbed; activate Phase 2 |

---

## 3. Architecture

### 3.1 Topology

```
              ┌─────────────────────┐
              │   Cloudflare Edge   │ ← HTTP/3, DDoS, TLS
              └──────────┬──────────┘
                         │
        ┌────────────────┴───────────────┐
        │                                │
        ▼                                ▼
┌───────────────┐              ┌──────────────────┐
│   Vercel      │              │   VPS (Ubuntu)   │
│  Next.js SPA  │              │ ┌──────────────┐ │
│  turf.smalhas │ ───API──→    │ │    nginx     │ │
│  ib.com       │              │ │ HTTP/2, TLS  │ │
└───────────────┘              │ └──────┬───────┘ │
                               │        │         │
                               │   ┌────┴────┐    │
                               │   │ FastAPI │    │
                               │   │ uvicorn │    │
                               │   │ workers │    │
                               │   └────┬────┘    │
                               │        │         │
                               │   ┌────┴────┐    │
                               │   │PostgreSQL│   │
                               │   │  Redis   │   │
                               │   └─────────┘   │
                               └──────────────────┘
```

### 3.2 Domain Layout

| Subdomain | Target | Purpose |
|---|---|---|
| `turf.smalhasib.com` | Vercel | Customer & admin frontend |
| `api.turf.smalhasib.com` | VPS via Cloudflare | API endpoints |
| `demo.turf.smalhasib.com` | Cloudflare Tunnel → laptop | Pre-launch client demos |
| `api.demo.turf.smalhasib.com` | Cloudflare Tunnel → laptop | Demo API |

DNS records configured at Cloudflare (`smalhasib.com` zone). Frontend records use DNS-only mode (Vercel manages TLS); API records are proxied (orange cloud).

### 3.3 VPS Resource Budget (2GB RAM)

| Service | RAM | Notes |
|---|---|---|
| PostgreSQL (`shared_buffers=256MB`) | ~600MB | Tuned for small box |
| Redis (`maxmemory 128MB`) | ~150MB | Locks + sessions only |
| FastAPI (2 uvicorn workers) | ~400MB | |
| nginx | ~50MB | |
| OS + buffers | ~400MB | |
| Headroom | ~400MB | Resize trigger at >85% sustained |

PostgreSQL tuning:
```
shared_buffers = 256MB
work_mem = 8MB
maintenance_work_mem = 64MB
effective_cache_size = 1GB
max_connections = 50
```

---

## 4. Data Model

### 4.1 Core Tables

```sql
venues
  id PK, name, address, contact_phone,
  open_hour SMALLINT, close_hour SMALLINT,
  slot_duration_min INT DEFAULT 60,
  advance_book_days INT DEFAULT 14,
  cutoff_min INT DEFAULT 30,
  base_price_bdt INT,
  cash_cancel_minutes_before INT DEFAULT 15,
  cancellation_full_refund_hours INT DEFAULT 24,
  timezone TEXT DEFAULT 'Asia/Dhaka',
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ

users
  id PK,
  firebase_uid TEXT UNIQUE NULL,            -- nullable: admin-created users have none
  phone TEXT UNIQUE NOT NULL,
  name TEXT,
  email TEXT NULL UNIQUE,                   -- groundwork for Phase 2
  email_verified BOOLEAN DEFAULT false,
  role role_enum NOT NULL DEFAULT 'customer',  -- customer | staff | admin
  manually_created BOOLEAN DEFAULT false,
  created_by_admin_id FK users NULL,
  no_show_count INT DEFAULT 0,
  cash_disabled BOOLEAN DEFAULT false,      -- admin-blacklisted from cash mode
  deletion_requested_at TIMESTAMPTZ NULL,
  deleted_at TIMESTAMPTZ NULL,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ

schedule_exceptions
  id PK, venue_id FK, exception_date DATE,
  type schedule_exception_type NOT NULL,    -- closed | windows
  windows JSONB NULL,                       -- [{start:"09:00",end:"11:00"},...]
  slot_duration_min INT NULL,
  reason TEXT, note TEXT,
  created_by FK users, created_at TIMESTAMPTZ
  UNIQUE(venue_id, exception_date)

slot_overrides                              -- admin one-off blocks (maintenance, offline reservations)
  id PK, venue_id FK,
  slot_start_at TIMESTAMPTZ, slot_end_at TIMESTAMPTZ,
  reason override_reason_enum,              -- maintenance|tournament|offline|holiday
  note, created_by FK, created_at

pricing_rules
  id PK, venue_id FK, name,
  day_of_week SMALLINT NULL,                -- 0-6 or NULL
  hour_start SMALLINT, hour_end SMALLINT,
  date_start DATE NULL, date_end DATE NULL,
  price_bdt INT, priority INT,
  is_active BOOLEAN, created_at

discount_codes
  id PK, code TEXT UNIQUE,
  type discount_type_enum,                  -- percent | flat
  value INT,
  min_amount_bdt INT, max_discount_bdt INT,
  usage_limit_total INT NULL,
  usage_limit_per_user INT DEFAULT 1,
  valid_from TIMESTAMPTZ, valid_until TIMESTAMPTZ,
  is_active BOOLEAN,
  applies_to JSONB NULL,                    -- {weekday|weekend|specific_dates:[...]}
  created_by FK, created_at

discount_redemptions
  id PK, discount_code_id FK, booking_id FK, user_id FK,
  amount_off_bdt INT, redeemed_at TIMESTAMPTZ,
  voided BOOLEAN DEFAULT false              -- when booking expires/cancels pre-confirm
  UNIQUE(discount_code_id, booking_id)

bookings
  id PK,
  public_id TEXT UNIQUE,                    -- "TRF-2026-000123"
  user_id FK, venue_id FK,
  booking_source booking_source_enum DEFAULT 'web',  -- web | admin
  created_by_admin_id FK users NULL,
  payment_collection payment_collection_enum,        -- online | cash | bkash_manual | free | pending_offline | cash_pending
  subtotal_bdt INT,
  admin_adjustment_bdt INT DEFAULT 0,       -- signed: surcharge or discount
  admin_adjustment_reason TEXT NULL,
  discount_code_id FK NULL,
  discount_amount_bdt INT DEFAULT 0,
  total_amount_bdt INT,
  slot_count INT,
  first_slot_at TIMESTAMPTZ, last_slot_at TIMESTAMPTZ,
  status booking_status_enum,               -- see state machine
  hold_token TEXT, hold_expires_at TIMESTAMPTZ,
  cutoff_override BOOLEAN DEFAULT false,
  free_reason TEXT NULL,
  cancellation_reason TEXT NULL, cancelled_at TIMESTAMPTZ NULL,
  refund_amount_bdt INT DEFAULT 0,
  created_at, updated_at TIMESTAMPTZ

booking_slots
  id PK, booking_id FK CASCADE, venue_id FK,
  slot_start_at TIMESTAMPTZ, slot_end_at TIMESTAMPTZ,
  price_bdt INT,
  price_overridden BOOLEAN DEFAULT false,
  EXCLUDE USING GIST (
    venue_id WITH =,
    tstzrange(slot_start_at, slot_end_at, '[)') WITH &&
  ) WHERE (booking_status IN ('pending_payment','confirmed'))

payments
  id PK, booking_id FK,
  provider payment_provider_enum,           -- bkash | cash | bkash_manual
  provider_payment_id TEXT UNIQUE NULL,     -- bKash paymentID
  provider_txn_id TEXT NULL,                -- bKash trxID
  manual_trx_id TEXT NULL,                  -- when admin types bKash trxID by hand
  collected_by_admin_id FK NULL,
  amount_bdt INT,
  status payment_status_enum,               -- initiated | completed | failed | refunded | pending_offline
  attempt_no INT DEFAULT 1,
  raw_request JSONB NULL, raw_response JSONB NULL,
  created_at, completed_at TIMESTAMPTZ

refunds
  id PK, payment_id FK,
  amount_bdt INT, reason TEXT,
  provider refund_provider_enum,            -- bkash_api | manual
  provider_refund_id TEXT NULL,
  status refund_status_enum,                -- pending | completed | failed
  requested_by FK users,
  created_at, completed_at TIMESTAMPTZ

audit_log
  id PK, actor_user_id FK,
  action TEXT,                              -- 'admin_create_booking', 'admin_refund_manual', etc.
  entity_type TEXT, entity_id BIGINT,
  before JSONB, after JSONB,
  ip TEXT, user_agent TEXT,
  created_at TIMESTAMPTZ

outbound_messages                           -- groundwork for Phase 2 email
  id PK, channel TEXT,                      -- email | (sms-future)
  to_address TEXT, subject TEXT, body_html TEXT,
  status TEXT, attempts INT DEFAULT 0, error TEXT,
  created_at, sent_at TIMESTAMPTZ
```

### 4.2 Critical Design Notes

- **No `slots` table.** Slots are derived: `(venue.open, close)` × not in `slot_overrides` × not in active `booking_slots`, modified by `schedule_exceptions`.
- **Partial unique via GIST exclusion** on `booking_slots` is the bulletproof DB-level guard against double bookings. Redis lock is UX-layer (8min hold); GIST is correctness.
- **All money columns are `INTEGER` BDT.** No fractional taka.
- **All timestamps `TIMESTAMPTZ` UTC.** Render `Asia/Dhaka` in app layer.
- **`venue_id` FK everywhere** for future multi-tenancy.
- **`raw_request` / `raw_response` JSONB** on payments table is debugging gold for bKash issues.
- **Postgres extension required:** `CREATE EXTENSION btree_gist;` for the exclusion constraint.

### 4.3 Indexes

```sql
CREATE INDEX ON bookings(user_id, created_at DESC);
CREATE INDEX ON bookings(venue_id, first_slot_at);
CREATE INDEX ON bookings(status, hold_expires_at) WHERE status = 'pending_payment';
CREATE INDEX ON booking_slots(slot_start_at);
CREATE INDEX ON booking_slots(venue_id, slot_start_at);
CREATE INDEX ON payments(status, completed_at);
CREATE INDEX ON payments(provider_payment_id);
CREATE INDEX ON audit_log(actor_user_id, created_at DESC);
CREATE INDEX ON audit_log(entity_type, entity_id);
CREATE INDEX ON discount_redemptions(user_id, discount_code_id);
```

---

## 5. Authentication

### 5.1 Customer Flow
1. Client calls Firebase JS SDK `signInWithPhoneNumber('+880...')` with invisible reCAPTCHA.
2. Firebase sends OTP, user enters, Firebase returns ID token.
3. Client `POST /v1/auth/firebase` with the ID token.
4. Backend verifies token with `firebase-admin` Python SDK, extracts `firebase_uid` and `phone`, upserts user row.
5. Backend mints app JWT (HS256, 15min lifetime, claims: `user_id`, `role`, `iat`, `exp`) plus a refresh token (UUID, 30d, single-use rotation, stored in Redis).
6. Client uses `Authorization: Bearer <jwt>` for all subsequent calls.

### 5.2 Admin Flow
Identical to customer flow — same Firebase OTP. Server-side `users.role` decides admin permissions. No separate password.

### 5.3 Re-OTP for Refunds (Customer Only)
For customer-initiated cancellations that trigger a refund:
1. `POST /v1/bookings/{id}/cancel/initiate` — backend computes refund tier, returns OTP session ID.
2. Client triggers Firebase phone re-OTP, user enters new code.
3. `POST /v1/bookings/{id}/cancel/confirm` with fresh Firebase ID token (verified to be issued within last 5 minutes).
4. Backend executes cancellation + refund.

Admin refunds and admin cancellations bypass re-OTP (logged in audit_log).

### 5.4 Token Lifecycle
- Access JWT: 15min, stateless.
- Refresh: 30d, Redis-backed, single-use rotation (issued new on each use).
- Revocation: delete refresh from Redis (logout, abuse).

---

## 6. Booking Flow Variants

### 6.1 Slot Generation
```python
def slots_for(venue, date):
    exc = schedule_exceptions.find(venue, date)
    if exc and exc.type == 'closed':
        return []
    if exc and exc.type == 'windows':
        slots = []
        duration = exc.slot_duration_min or venue.slot_duration_min
        for w in exc.windows:
            slots += grid(w.start, w.end, duration)
    else:
        slots = grid(venue.open_hour, venue.close_hour, venue.slot_duration_min)
    slots -= slot_overrides.ranges_for(venue, date)
    slots -= booking_slots.active_for(venue, date)
    return slots  # each slot tagged with rule-resolved price
```

### 6.2 Standard Web Booking (multi-day capable)
1. `GET /v1/venues/1/calendar?from=...&to=...` returns N days of slot grids.
2. User selects any combination of slots across any allowed dates (within `advance_book_days`, after T-30min cutoff).
3. `POST /v1/bookings/hold` with slot list, optional discount code.
   - Lua-atomic Redis SETNX on every slot key (8min TTL). All-or-nothing.
   - Insert booking row (`status='pending_payment'`).
   - Insert `booking_slots` rows (GIST exclusion is final correctness guard).
   - Validate and insert `discount_redemptions` row if code applied.
   - Returns `{booking_id, total_bdt, hold_expires_at}`.
4. Payment method picker: bKash online / Cash on arrival.

### 6.3 bKash Online Path
1. `POST /v1/payments/bkash/create`
   - Backend obtains/refreshes bKash access token (cached in Redis ~50min).
   - Calls bKash `/checkout/create` with `merchantInvoiceNumber=TRF-{booking_id}-{nonce}`.
   - Returns `{paymentID, bkashURL}`.
2. Browser redirects to `bkashURL`.
3. User completes bKash auth on bKash hosted page.
4. bKash redirects to `callbackURL` with `paymentID` and status.
5. Backend immediately calls `/checkout/execute/{paymentID}` to finalize.
6. Defense-in-depth: also call `/checkout/payment/status/{paymentID}` to cross-verify.
7. Update booking `status='confirmed'`, payment `status='completed'`.
8. Release Redis lock keys.
9. Frontend polls `/v1/bookings/{id}/status`, renders success page with download receipt button.

### 6.4 Cash on Arrival Path (Web)
1. `POST /v1/bookings/confirm` with `payment_method='cash'`.
2. Booking inserted as `status='confirmed'`, `payment_collection='cash_pending'`.
3. No payment row yet.
4. Slot held (GIST locked).
5. Receipt PDF shows "AWAITING PAYMENT" watermark.
6. On customer arrival, admin marks paid in admin panel:
   - Insert payment row (`provider='cash'`, `status='completed'`).
   - Booking watermark cleared.
7. Auto-cancel guard: background job cancels booking if not marked paid by `first_slot_at - 15min` (configurable). Increments `users.no_show_count`.
8. Auto-blacklist: `no_show_count >= 3` → `users.cash_disabled=true`. Admin can manually unblock.

### 6.5 Admin-Created Booking
1. Admin opens `/admin/bookings/new`.
2. Picks date(s) and slots (cutoff override allowed via checkbox).
3. Customer identification:
   - Search existing user by phone, OR
   - Quick-create new user (name + phone, no Firebase OTP, `manually_created=true`), OR
   - Self (use admin's own user_id).
4. Pricing:
   - Per-slot price overridable.
   - Booking-level adjustment (signed BDT, requires reason if non-zero).
   - Discount code stackable.
5. Payment collection mode:
   - Online (bKash link to share with customer)
   - Cash (admin records, immediate confirm)
   - bKash manual (admin records trxID after collecting via personal bKash)
   - Free (requires `free_reason`)
   - Pending offline (confirm now, collect later)
6. Submit → atomic Redis lock + GIST insert + payment row (varies by mode).
7. Audit log entry created with `action='admin_create_booking'`.

### 6.6 Failure Variants

| Variant | Trigger | Resolution |
|---|---|---|
| F1: Lock expired | User idle >8min | Hold released, booking → `expired`, slots free |
| F2: Payment cancelled | User aborts on bKash page | Booking → `cancelled`, slots released |
| F3: Payment failed | Wrong PIN, insufficient balance | Booking → `failed`, slots released, retry offered |
| F4: Payment timeout | bKash unresponsive | Background job (Dramatiq cron 1min) reconciles via `/payment/status` |
| F5: Late webhook, slot free | Webhook arrives after lock expired but slot empty | Reconcile, confirm booking |
| F6: Late webhook, slot taken | GIST blocks insert | Booking → `payment_received_no_slot`, auto-refund triggered, admin alert |
| F7: Refund API fails | bKash 5xx | Refund row `status='failed'` → admin queue → manual retry |
| F8: User closes tab | Browser closed mid-flow | Same as F4, lock TTL governs |

### 6.7 Booking State Machine

```
                  ┌─→ confirmed ─→ cancelled ─→ refund_pending ─→ refunded
                  │      │                              └────────→ refund_failed
pending_payment ──┤      └─→ completed (after last_slot_at via cron)
                  ├─→ expired
                  ├─→ failed
                  ├─→ cancelled (during pending)
                  ├─→ auto_cancelled_no_payment (cash didn't arrive)
                  └─→ payment_received_no_slot ─→ refund_pending ─→ refunded
```

### 6.8 Race Condition Safeguards
1. **Redis Lua-atomic SETNX** across all requested slot keys with 8min TTL.
2. **PostgreSQL GIST exclusion constraint** on `booking_slots` (ultimate correctness layer).
3. **Background reconciliation cron** every 60 seconds:
   - Find `pending_payment` bookings past `hold_expires_at`.
   - Query bKash `/payment/status` for any with paymentID.
   - Confirm or expire based on result.
4. **Frontend SSE channel** for live slot grid updates (others' locks visible immediately).

---

## 7. Pricing Engine

### 7.1 Resolution Order

For a given slot at `(venue, date, hour)`:

1. If `booking_slots.price_overridden=true` (admin override): use that.
2. Else if `schedule_exceptions.windows[i].price` exists for that exact slot: use that.
3. Else if active `pricing_rules` matches `(date, hour, dow)`: use highest-priority match.
4. Else fallback to `venues.base_price_bdt`.

### 7.2 Booking Total

```
subtotal       = sum(booking_slots.price_bdt)
admin_adjust   = bookings.admin_adjustment_bdt    (signed, web bookings = 0)
discount       = computed from discount_codes if applied
total          = max(0, subtotal + admin_adjust - discount)
```

If `total = 0` → treat as `payment_collection='free'`, no payment flow needed.

---

## 8. Cancellation & Refund Policy

### 8.1 Tiers (Binary)
- More than 24 hours before slot start: 100% refund of that slot.
- Less than 24 hours before: 0% refund.

### 8.2 Per-Slot Evaluation (Multi-day Bookings)
Each slot evaluated against its own `slot_start_at`. Refund total = sum across slots.

```python
def compute_refund(booking, now):
    refund = 0
    for slot in booking.slots:
        hrs_until = (slot.start_at - now).total_seconds() / 3600
        if hrs_until > 24:
            refund += slot.price_bdt
    return refund
```

### 8.3 Cancellation Initiator Matrix

| Initiator | Re-OTP | Refund Path |
|---|---|---|
| Customer (bKash-paid) | Yes (Firebase re-OTP) | bKash refund API auto |
| Customer (cash-pending unpaid) | No (no payment to return) | Booking → `cancelled` |
| Customer (cash-paid via admin) | Yes (re-OTP) | Manual return at venue, marked `refunds.provider='manual'` |
| Admin (cash) | No | Manual return marked, audit log |
| Admin (online bKash) | No | bKash API auto |
| Admin (free) | No | No refund applicable |
| System (F6 race) | No | bKash API auto |

### 8.4 Partial Cancellation
**Not supported in MVP.** Cancellation is whole-booking only. Refund amount IS computed per-slot tier. Per-slot drop deferred to Phase 2.

---

## 9. Admin Capabilities

### 9.1 Roles

| Role | Permissions |
|---|---|
| `customer` | Book own slots, view own history, request own cancellation |
| `staff` | View bookings, mark cash paid, mark no-show, block slots, view reports. **Cannot:** override prices (configurable flag, default OFF), issue refunds, manage users, manage pricing rules |
| `admin` | All staff permissions plus: refund, pricing rules, schedule_exceptions, role management, discount codes, audit log access |

### 9.2 First Admin Bootstrap
- `.env` variable `INITIAL_ADMIN_PHONE`.
- On first boot, FastAPI startup hook upserts user with `role='admin'` if phone matches and no admin exists.
- Idempotent: re-run safe.
- Backup: CLI command `python -m app.cli promote-admin +880XXXXXXXXX`.

### 9.3 Privacy
- **Phone numbers masked by default** in admin tables (e.g., `+8801XX-XX5678`). Click row to see full.
- **User self-deletion** via `DELETE /v1/me`:
  - Sets `deletion_requested_at = now()`.
  - Background job runs after 30 days: anonymize PII (`name='[deleted]'`, `phone=NULL`, `email=NULL`, `firebase_uid=NULL`), set `deleted_at`.
  - Bookings retained for revenue ledger.

---

## 10. Reporting & Analytics

### 10.1 Strategy
Live SQL aggregates per dashboard load. Postgres handles 1k DAU comfortably with proper indexes. No pre-computed rollups MVP. Add only when individual query crosses 1s.

### 10.2 Dashboards

**Revenue:**
- Filter: today | 7d | 30d | MTD | YTD | custom range.
- Splits: online (bKash), cash collected at venue (web cash + admin cash), bKash manual (admin), pending cash (booked, awaiting collection), lost revenue (auto-cancelled cash bookings).
- Discount given breakdown: admin overrides, discount codes, refunds.

**Occupancy:**
- Daily occupancy rate = booked-hour / available-hour.
- Heatmap: day-of-week × hour-of-day, last 90 days.
- Peak hours / popular days.

**Customer Log:**
- Paginated table: phone (masked), name, total bookings, total spend, last booking, no-show count, status (active/blacklisted/deleted).
- Click row → drawer with full booking history.
- Sort/filter by spend, count, recency.

**Per-admin metrics:**
- Bookings created by each admin/staff.
- Discount given by each admin (top discounters).
- Manual refunds issued.

### 10.3 CSV Export
All table views support streaming CSV download endpoint. PDF report skipped MVP (Excel pivots better).

---

## 11. PDF Receipts

### 11.1 Generation
- Synchronous on download: `GET /v1/bookings/{id}/receipt.pdf`.
- WeasyPrint renders Jinja2 HTML template.
- Fonts: Inter for Latin, Noto Sans Bengali for Bangla names.
- Auth required: booking owner or admin only.
- `Content-Disposition: attachment; filename="Receipt-TRF-2026-000123.pdf"`.
- `Cache-Control: private, max-age=300`.

### 11.2 Receipt Contents
- Logo + venue name + address + contact
- "Receipt" header + booking public ID (`TRF-2026-000123`)
- Customer name + masked phone
- Slot table: date, time, duration, unit price, override indicator
- Subtotal, admin adjustment (with reason), discount (with code), total
- Payment method-specific block:
  - Online: "PAID via bKash — trxID xxx"
  - Cash unpaid: "AWAITING PAYMENT" watermark
  - Cash paid: "PAID in cash — collected by [admin] at [time]"
  - bKash manual: "PAID via bKash (manual) — trxID xxx"
  - Free: "COMPLIMENTARY — reason: …"
- Status badge: PAID / REFUNDED / PARTIAL / PENDING
- Footer: cancellation policy summary + support contact
- QR code linking to verifiable booking page

---

## 12. Notifications & Email Groundwork

### 12.1 MVP State
No outbound notifications sent. Booking status visible in:
- In-app booking history
- Receipt download

### 12.2 Email Groundwork (Phase 2-ready)
- `users.email` and `users.email_verified` columns.
- Settings page UI captures email on opt-in.
- `EmailProvider` Python interface with `NoopEmailProvider` impl (logs only).
- Booking confirm and refund hooks call provider — no-op MVP.
- `outbound_messages` queue table empty MVP.
- Receipt template doubles as email body via shared Jinja2 partial.
- Env vars: `EMAIL_PROVIDER=noop|resend`, `RESEND_API_KEY=`.
- Phase 2 activation: set env, swap impl class, deploy. Zero refactor.

---

## 13. Discount Codes

### 13.1 Validation Order at Hold Time
1. Code exists, `is_active=true`.
2. `now()` in `[valid_from, valid_until]`.
3. Total redemptions < `usage_limit_total`.
4. User redemption count < `usage_limit_per_user`.
5. Booking subtotal >= `min_amount_bdt`.
6. `applies_to` matches (weekday/weekend/specific_dates).
7. Discount computed: `min(percent_or_flat_value, max_discount_bdt)`.

### 13.2 Lifecycle
- Inserted at hold (`discount_redemptions` row) — counts toward limits immediately.
- If booking expires/fails/cancels pre-confirm → mark `voided=true`, decrement effective count.
- After confirm → permanent.

### 13.3 Removable Pre-Payment
`DELETE /v1/bookings/{id}/discount` while `status='pending_payment'`.

---

## 14. Hosting & Deployment

### 14.1 VPS Setup
- Ubuntu 22.04/24.04 LTS on `103.174.51.125`.
- nginx as reverse proxy: HTTP/2 + Cloudflare Origin Certificate (15-year, no rotation).
- Cloudflare proxied (orange cloud) on `api.turf.smalhasib.com` — provides HTTP/3 to client transparently.
- Docker Compose stack: PostgreSQL + Redis + FastAPI (uvicorn 2 workers).
- Frontend on Vercel free tier (auto-deploy from GitHub on `main`).

### 14.2 Cloudflare DNS Records (`smalhasib.com`)

```
turf.smalhasib.com           CNAME  cname.vercel-dns.com           (DNS-only)
api.turf.smalhasib.com       A      103.174.51.125                 (proxied)
demo.turf.smalhasib.com      CNAME  <tunnel-uuid>.cfargotunnel.com (proxied, demo only)
api.demo.turf.smalhasib.com  CNAME  <tunnel-uuid>.cfargotunnel.com (proxied, demo only)
```

### 14.3 SSL
Cloudflare → Origin → "Full (strict)" mode. Cloudflare Origin Certificate (free, 15-year) installed at nginx. No certbot, no rotation pain.

### 14.4 Deploy Mechanism
GitHub Actions workflow on `main` push:
1. Run unit + integration tests (testcontainers).
2. Build Docker images.
3. SSH to VPS, `git pull`, `docker compose up -d --build`.
4. Run `alembic upgrade head` on container boot (entrypoint script).
5. Vercel auto-deploys frontend from same commit.

### 14.5 Backups
- Nightly `pg_dump` cron → encrypted (`age` tool) → Cloudflare R2 bucket.
- Retention: 7 daily + 4 weekly + 3 monthly.
- Quarterly restore drill (untested backup = no backup).
- VPS provider snapshot weekly if available.

### 14.6 Resize Plan
1. RAM > 85% sustained → upgrade VPS to 2c/4GB (live resize where supported).
2. DB > 5GB or write-heavy → migrate to managed PostgreSQL (~$15/mo).
3. Redis-as-bottleneck (rare at this scale) → split Redis off.

---

## 15. CI/CD & Testing

### 15.1 Source Control
GitHub. `main` = prod. Feature branches → PR → squash merge. Branch protection: require all checks green.

### 15.2 Test Stack — Three Layers

| Layer | Scope | Tools | Speed |
|---|---|---|---|
| Unit | Pure functions, no I/O | pytest, Vitest | <1s/test |
| Integration | API → real DB + Redis | pytest, httpx, testcontainers-python | 1–10s/test |
| E2E | Full browser journey | Playwright | 10–60s/test |

### 15.3 Backend Layout
```
tests/
  unit/
    test_pricing.py
    test_slot_generator.py
    test_refund_computation.py
  integration/
    test_booking_flow.py
    test_auth_flow.py
    test_payment_webhook.py
    test_admin_actions.py
  conftest.py                  # testcontainers fixtures
```

### 15.4 Frontend Layout
```
__tests__/                    # Vitest (component logic, hooks, utils)
e2e/
  signup.spec.ts
  booking-multi-day.spec.ts
  booking-cash.spec.ts
  receipt-download.spec.ts
  cancel-with-otp.spec.ts
  admin-create-booking.spec.ts
  admin-pricing-override.spec.ts
  race-condition.spec.ts
```

### 15.5 CI Pipeline (GitHub Actions)
Required jobs gating merge:
- `backend-unit`: `pytest tests/unit -x`
- `backend-integration`: `pytest tests/integration -x`
- `frontend-unit`: `vitest run`
- `e2e`: `playwright test` against Vercel preview

### 15.6 Coverage Aspiration
Backend 70%, frontend 50%. No hard gate (avoids test-for-coverage anti-pattern). Enforced via review:
- Every bug fix ships with regression test.
- Every new endpoint: happy path + auth-failure test minimum.

### 15.7 Critical E2E Flows
1. New user signup via OTP (Firebase test phone numbers, fixed OTP).
2. Returning user login.
3. Multi-day booking → bKash sandbox → confirmation → receipt download.
4. Cash on arrival → admin marks paid.
5. Customer cancellation with re-OTP → refund issued.
6. Admin: block slot, change pricing, view report, create offline booking.
7. Race: two users target same slot — second sees "Reserved" / lock error.

### 15.8 Test Data Isolation
- Integration: testcontainer per session, transaction rollback per test.
- E2E: dedicated test database with seeded fixtures, reset between test runs.

---

## 16. Monitoring & Observability

### 16.1 Stack
- **Sentry** (free tier 5k events/month): backend + frontend error tracking, performance traces.
- **HetrixTools** (free tier): uptime checks from multiple regions on `api.turf.smalhasib.com/health` and `turf.smalhasib.com`. Alerts via email + Telegram. Bonus blacklist monitoring on VPS IP.
- **Cloudflare Analytics**: traffic + cache stats (free).
- **Postgres pg_stat_statements**: slow query log (>500ms).
- **System metrics** MVP: `htop` + cron disk-space alert via Telegram. Add Prometheus + Grafana when VPS upgraded.

### 16.2 Logging
- FastAPI: structured JSON logs (`structlog`) → stdout → Docker → file `/var/log/turf/api.log` rotated by `logrotate`.
- PostgreSQL: file logs, slow query log on.
- No external aggregator MVP (Loki/Datadog cost). Sentry breadcrumbs cover high-value debug context.

### 16.3 Health Check
`GET /v1/health` returns:
```json
{
  "status": "ok",
  "checks": {
    "db": "ok",
    "redis": "ok",
    "bkash_token_age_sec": 1247,
    "version": "1.0.0"
  }
}
```

---

## 17. Security

### 17.1 Surface Hardening
- **TLS everywhere**: Cloudflare → origin Full (strict).
- **HSTS** header at nginx.
- **CSP** strict on Next.js (no inline scripts beyond Firebase SDK).
- **Rate limiting** on auth + booking endpoints (Redis-backed, per-user + per-IP).
- **Pydantic validation** at every API boundary (kills XSS/SQLi class).
- **Parameterized queries** via SQLAlchemy (never raw string concat).
- **CORS** strict: `https://turf.smalhasib.com` only.
- **Secrets**: `.env` not in git; GitHub Secrets for CI; VPS `/srv/turf/.env` mode 600 root-owned.
- **JWT**: HS256 with rotated secret, short lifetime, Redis refresh.

### 17.2 API Versioning
All endpoints prefixed `/v1/...` from day one. Cheap insurance for future v2.

### 17.3 Audit Trail
Every admin action writes `audit_log` row: actor, action, before/after JSONB, IP, user agent. Filterable by entity, action, time range.

### 17.4 Bulk Action Throttling
Admin booking creation rate-limited 30/hour/admin to detect abuse.

### 17.5 Privacy
- Phone masking in admin views by default.
- 30-day cooling period on user-initiated deletion before anonymization.
- Receipt downloads: owner or admin only.

---

## 18. Legal & Compliance

### 18.1 Required Pages (MVP)
- **Privacy Policy** — single static page. Must mention: data collected (name, phone, payment metadata), Firebase auth, bKash data flow, retention, deletion rights, contact for data requests.
- **Terms of Service** — single static page. Must mention: booking T&Cs, cancellation policy, refund policy, no-show consequences, disputes, governing law (Bangladesh).
- **Refund Policy** — separate page or section in ToS.

Generic templates customized for BD turf rental. Lawyer review post-launch. **Required for bKash merchant onboarding KYC.**

### 18.2 Data Retention
- Active bookings, audit log: forever.
- Cancelled/expired bookings: forever (revenue ledger).
- User PII on deletion request: anonymized after 30-day cooling period.

### 18.3 VAT
**Not handled in MVP.** No VAT line on receipts, no `tax_rate` column. BD VAT exemption likely applies under turnover threshold; consult accountant before crossing it.

---

## 19. Local Dev & Demo Workflow

### 19.1 Local Dev Stack
`docker-compose.dev.yml`:
- PostgreSQL 15 + Redis 7 + adminer (DB UI) + mailpit (email catcher for Phase 2 testing)
- FastAPI + Next.js run native via `pnpm dev` / `uvicorn --reload` for hot reload speed

```bash
make dev          # start everything
make migrate      # alembic upgrade head
make seed         # demo data
make test         # all three test layers
make demo-reset   # wipe + reseed in 5 seconds
```

### 19.2 Demo Workflow (Pre-VPS Deploy)

**Why local + tunnel first:** validate full UX with client before committing to production deploy.

**Cloudflare Tunnel setup:**
```bash
brew install cloudflared
cloudflared tunnel login
cloudflared tunnel create turf-demo
```

DNS records (added at Cloudflare):
- `demo.turf.smalhasib.com` → `<tunnel-uuid>.cfargotunnel.com`
- `api.demo.turf.smalhasib.com` → same tunnel (path rule)

`~/.cloudflared/turf-demo.yml`:
```yaml
tunnel: <uuid>
credentials-file: ~/.cloudflared/<uuid>.json
ingress:
  - hostname: api.demo.turf.smalhasib.com
    service: http://localhost:8000
  - hostname: demo.turf.smalhasib.com
    service: http://localhost:3000
  - service: http_status:404
```

Run: `cloudflared tunnel run turf-demo`

### 19.3 Demo `.env.demo`
- `BKASH_MODE=sandbox` + sandbox creds
- `FIREBASE_PROJECT=turf-demo` (separate Firebase project, not prod)
- Demo Firebase project has `demo.turf.smalhasib.com` in authorized domains
- bKash sandbox merchant configured with callback `https://api.demo.turf.smalhasib.com/v1/payments/bkash/callback`
- Firebase test phone numbers configured (e.g., `+8801500000000` → fixed OTP `123456`) — no real SMS

### 19.4 Demo-Day Checklist
- [ ] `docker compose -f docker-compose.dev.yml up`
- [ ] `make demo-reset`
- [ ] FastAPI + Next.js running with logs visible
- [ ] `cloudflared tunnel run turf-demo`
- [ ] Smoke test from mobile (4G, not wifi)
- [ ] Login with Firebase test number
- [ ] bKash sandbox booking end-to-end
- [ ] Admin booking with price override + cash
- [ ] Receipt download
- [ ] Reports view

### 19.5 Demo Risks & Mitigations
- Laptop sleeps → `caffeinate` on macOS / "Prevent sleep" on Win.
- Wifi drops → mobile hotspot backup.
- Accidental reset → disable demo-reset keybinding during meeting.

---

## 20. Phasing

### Phase 1 — MVP (~13–14 weeks solo)

**Auth & Identity**
- Firebase phone OTP, app JWT, refresh in Redis
- 3 roles: customer, staff, admin
- First-admin bootstrap via env

**Booking Engine**
- Single venue, multi-day capable bookings
- 1hr default slots, configurable per-date via schedule_exceptions
- Redis 8min hold + Postgres GIST exclusion
- 14d advance window, T-30min cutoff
- bKash PGW + Cash on arrival + Admin-created (online/cash/bkash_manual/free/pending_offline)

**Pricing**
- Pricing rules (day-of-week, hour, date range, priority)
- Admin per-slot price override + booking-level adjustment
- Discount codes with usage limits

**Cancellation & Refund**
- Binary tier (>24h: 100%, ≤24h: 0%) per-slot evaluated
- Customer re-OTP for refunds, admin no re-OTP
- Auto-refund on system fault (race, timeout)

**Admin**
- Multi-staff
- Slot block, schedule_exceptions (closed | windows)
- Pricing rule management
- Discount code management
- Customer log with drill-down
- Reports: revenue (split by source), occupancy (heatmap), CSV export
- Audit log viewer
- Phone masking + unmask
- Re-OTP on customer-initiated refund only

**Receipts**
- WeasyPrint PDF on-demand
- Payment-method-specific rendering

**Schedule Exceptions**
- closed | windows types
- Custom slot duration override
- Admin UI for date-specific rules

**Operations**
- nginx HTTP/2 + Cloudflare proxy + Origin cert
- Docker Compose deploy via SSH from GitHub Actions
- Alembic migrations on container boot
- Sentry + HetrixTools monitoring
- Nightly pg_dump → encrypted → Cloudflare R2

**Testing**
- Unit + integration + E2E with mandatory coverage of 7 critical flows
- testcontainers for real Postgres/Redis in integration

**Legal**
- Privacy Policy + Terms of Service stubs

**Email Groundwork (no sending)**
- Schema, settings UI, NoopEmailProvider stub

**Local-First Demo**
- Cloudflare Tunnel demo workflow
- `.env.demo` with sandbox creds

---

### Phase 2 — Post-Launch

- Email sending activation (Resend) — booking confirms with PDF attached
- Bangla UI (i18n integration)
- Cloudflare R2 backup automation hardening
- HetrixTools multi-region tuning
- Per-slot partial cancellation
- BD holiday quick-insert helper UI (opt-in, not auto-seed)
- Audit log advanced filters

### Phase 3 — Scale & Expand

- Multi-venue UI (schema already supports)
- Nagad / Rocket / card payment providers (provider abstraction ready)
- Mobile apps (React Native sharing API)
- WhatsApp / push notifications
- Loyalty / membership tiers
- Admin-curated event packages (tournaments, multi-day with capacity limits)
- VAT line on receipts (when threshold crossed)
- Cohort retention, LTV analytics
- Managed PostgreSQL migration (when DB > 5GB)

---

## 21. Open Questions / Future Considerations

- **bKash merchant approval timeline** (~2–4 weeks KYC) — start application Week 1 of dev so creds available by Week 8.
- **Privacy Policy + ToS** — finalize wording with lawyer before bKash KYC submission.
- **Demo Firebase project** — create early, configure test phone numbers before client demo.
- **Frontend design language** — not addressed in grilling; consider engaging design pass before final UI build.
- **Backup restore drill** — schedule first quarterly drill date in calendar.
- **VPS upgrade trigger** — set HetrixTools alert at 85% sustained RAM.

---

## 22. Decision Lock Log

| # | Branch | Decision |
|---|---|---|
| 1 | Scope | Single venue MVP, multi-venue schema-ready |
| 2 | Stack | Next.js + FastAPI + Postgres + Redis |
| 3 | Slot model | 1hr default, multi-slot contiguous, 6am-12am, 14d advance, T-30min cutoff |
| 4 | Locking | Redis SETNX 8min + Postgres GIST exclusion |
| 5 | Edge | nginx HTTP/2 + Cloudflare proxy (HTTP/3 to client transparently) |
| 6 | Auth | Firebase Phone Auth → app JWT + Redis refresh |
| 7 | Payment | bKash PGW only MVP, provider abstraction for future |
| 8 | Notifications | No SMS; in-app + PDF only; email groundwork stubbed |
| 9 | Schedule exceptions | `closed | windows` types, JSONB windows, optional duration override |
| 10 | Multi-day | User-driven multi-day bookings supported; no admin event packages |
| 11 | Schema | GIST exclusion via btree_gist; INTEGER BDT; TIMESTAMPTZ UTC |
| 12 | Admin model | Multi-staff, 3 roles (customer/staff/admin), env-seeded first admin |
| 13 | Re-OTP | Customer-initiated refunds only; admin actions audit-logged |
| 14 | Reporting | Live SQL + Recharts + CSV export, revenue splits by payment source |
| 15 | PDF | WeasyPrint on-demand, Bangla font preloaded |
| 16 | Hosting | VPS (1c/2GB) + Vercel + Cloudflare; Origin Certificate |
| 17 | CI/CD | GitHub Actions, Docker Compose, Alembic, 3-tier tests, testcontainers |
| 18 | Monitoring | Sentry + HetrixTools |
| 19 | Admin booking | Yes, with payment toggle (online/cash/bkash_manual/free/pending) |
| 20 | Custom pricing | Per-slot override + booking-level adjustment for admin |
| 21 | Cash on arrival | Yes for web users; auto-cancel at T-15min if unpaid; no-show blacklist at 3 |
| 22 | Refund tiers | Binary (>24h: 100%, ≤24h: 0%), per-slot evaluation |
| 23 | Language | English only MVP, Bangla Phase 2 |
| 24 | Legal | PP + ToS stubs MVP |
| 25 | Retention | Indefinite for revenue; user-deletion 30-day cool-off + anonymize |
| 26 | Phone masking | On by default in admin tables |
| 27 | API versioning | `/v1/...` from day one |
| 28 | Local dev | docker-compose.dev.yml with adminer + mailpit |
| 29 | Holiday seed | Skipped — turf demand spikes on holidays |
| 30 | First admin | Env-seeded on boot, idempotent |
| 31 | Demo workflow | Cloudflare Tunnel before VPS deploy |
