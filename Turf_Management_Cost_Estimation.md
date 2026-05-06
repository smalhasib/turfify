# Turf Management Platform — Cost Estimation

**Companion to:** `Turf_Management_Plan.md`
**Currency:** BDT (Bangladeshi Taka). USD conversions assume ~120 BDT/USD.
**Scale assumption:** 500–1,000 daily active users, 50–100 paid bookings/day, average ticket BDT 1,000–3,000.

All figures are estimates based on published pricing as of 2026. Actual costs may vary with usage spikes, currency fluctuation, or vendor changes.

---

## 1. One-Time Setup Costs

| Item | Estimated Cost (BDT) | Notes |
|---|---|---|
| bKash merchant account onboarding | 0 | Free; requires KYC docs (NID, trade license, bank account). 2–4 week review |
| Firebase project setup | 0 | Free tier sufficient for setup |
| Cloudflare account setup | 0 | Free tier |
| Vercel account setup | 0 | Free tier |
| Sentry account setup | 0 | Free tier |
| HetrixTools account setup | 0 | Free tier |
| Privacy Policy + ToS lawyer review | 5,000 – 15,000 | Optional but recommended pre-launch |
| Logo + basic branding | 3,000 – 10,000 | If outsourced; skip if DIY |
| **One-time total** | **8,000 – 25,000** | |

---

## 2. Recurring Annual Fixed Costs

| Item | Annual Cost (BDT) | Notes |
|---|---|---|
| Domain — `smalhasib.com` (already owned) | 0 | Existing |
| Subdomains (`turf.*`, `api.turf.*`) | 0 | Free under owned domain |
| VPS — existing 1c/2GB at `103.174.51.125` | 0 | Sunk cost; assumed already paid |
| Cloudflare (free plan) | 0 | DDoS, HTTP/3 to client, basic analytics, 100k requests/month free |
| Cloudflare R2 backup storage (~10GB usage) | ~600 (~$5) | Free 10GB egress + 1M Class A ops; storage $0.015/GB-month after free tier |
| Vercel (free Hobby tier) | 0 | 100GB bandwidth, 100h compute/month — covers 1k DAU comfortably |
| Sentry (free Developer tier) | 0 | 5k errors + 10k performance events/month; sufficient until traffic spike |
| HetrixTools (free tier) | 0 | 50 monitors, 1-min interval, multi-region |
| Firebase Phone Authentication | 0 – 24,000 | 10k verifications/month free; ~$0.06/verification beyond. At 1k DAU mostly returning, expected near zero. Worst-case viral spike pushed to USD ~$200/year (~24,000 BDT) |
| **Recurring fixed (year)** | **600 – 25,000** | Most likely close to BDT 600–2,000/year |

---

## 3. Variable Costs (Per Transaction)

### bKash Merchant Commission
- Direct merchant rate: **~1.85%** per transaction (subject to negotiation; may be 1.5–2.0% based on volume).
- This is **deducted from settlement**, not paid as a separate invoice.

### Estimated Annual Commission

Assumption: 60 paid online bookings/day × 365 days × BDT 1,500 average ticket = **BDT 32,850,000 gross online revenue/year**.
- bKash commission @ 1.85% = **~BDT 607,725/year**

Cash bookings (collected at venue, no aggregator fee) = no commission.

If 50% of bookings are cash, online revenue is ~50% of total → commission roughly halves:
- Online portion @ 50% = BDT 16,425,000 → **commission ~BDT 303,800/year**

Treat as cost-of-goods, not platform overhead.

---

## 4. Phase 1 (MVP) Total Annual Operating Cost

| Category | Annual Cost (BDT) |
|---|---|
| Recurring fixed infrastructure | 600 – 25,000 |
| One-time setup (amortize Year 1 only) | 8,000 – 25,000 |
| **Year 1 fixed total** | **8,600 – 50,000** |
| **Year 2+ fixed total** | **600 – 25,000** |
| Variable: bKash commission | depends on revenue (1.85% of online portion) |

Excludes:
- bKash transaction commission (revenue-dependent, treated as COGS)
- Development cost (~13–14 weeks solo dev — value depends on rate)
- VPS rental (assumed sunk cost)
- Marketing, customer support staffing

---

## 5. Comparison with Original PRD Estimate

The PRD projected **BDT 28,500 – 60,500/year**. Breakdown:

| PRD Line Item | PRD Estimate (BDT/year) | Actual Plan (BDT/year) | Delta Reasoning |
|---|---|---|---|
| Domain | 1,500 – 2,500 | 0 | Already owned |
| Cloud/VPS | 12,000 – 20,000 | 0 | Already owned |
| SMS Gateway API | 5,000 – 8,000 | 0 | Replaced with Firebase OTP (free at scale) + skipped booking confirmation SMS |
| SSLCommerz | 0 (commission-based) | 0 (commission-based, swapped to bKash direct) | Lower commission rate via direct merchant |
| Maintenance | 10,000 – 30,000 | (not platform cost) | Excluded from this estimate; tracked separately as developer time |
| **PRD total** | **28,500 – 60,500** | | |
| **Plan total (Year 1 fixed)** | | **8,600 – 50,000** | Lower bound much better; upper bound includes lawyer review + Firebase scale buffer |

Material savings vs PRD primarily from:
1. Existing VPS sunk cost (saves ~BDT 16,000/yr).
2. Firebase replacing dedicated SMS gateway (saves ~BDT 6,500/yr expected).
3. No transactional SMS confirmations (saves another ~BDT 1,500–2,000/yr at usage rates).
4. Cloudflare R2 cheaper than equivalent S3 / managed backup services.

---

## 6. Cost Triggers — When Each Adds Up

| Trigger | Cost That Activates | Annual Impact (BDT) |
|---|---|---|
| Firebase OTP volume crosses 10k/month | $0.06 per verification beyond 10k | Up to ~24,000/year worst case |
| Sentry events cross 5k/month | Pay tier from $26/month | ~37,000/year if tripped |
| HetrixTools needs >50 monitors or 30s interval | Pro plan from $7/month | ~10,000/year |
| Vercel bandwidth >100GB/month | Pro plan from $20/month | ~29,000/year |
| Cloudflare requests >100k/month or DDoS active | Pro plan from $20/month | ~29,000/year |
| Email sending activated (Phase 2) | Resend from $20/month at scale | ~29,000/year |
| Managed PostgreSQL needed (DB >5GB or HA required) | DigitalOcean Managed DB from $15/month | ~22,000/year |
| Daily backup retention extended | R2 storage scales linearly | minimal at this volume |

These are **not** baseline costs — they activate only when triggered.

---

## 7. Phase 2 Cost Additions

If/when activated:

| Item | Annual Cost (BDT) | Notes |
|---|---|---|
| Resend email transactional (3k free, $20/month after) | 0 – 30,000 | Likely zero MVP volume; activate if volume crosses free tier |
| Domain `.com.bd` (optional local trust signal) | 1,500 – 2,500 | If desired for SEO/trust, not infrastructure-required |
| Bangla i18n font/locale ops | 0 | Free tooling |

---

## 8. Phase 3 Cost Additions

When scaling:

| Item | Annual Cost (BDT) |
|---|---|
| Managed PostgreSQL (DigitalOcean / Supabase) | 22,000 – 50,000 |
| VPS upgrade to 2c/4GB or 4c/8GB | 14,000 – 70,000 |
| Mobile app dev infra (Expo EAS, App Store fees) | 12,000 – 25,000 |
| Push notification service (Firebase Cloud Messaging — free; OneSignal — free at scale) | 0 |
| WhatsApp Business API (per-conversation fee) | depends on volume |
| Multi-venue features (no infra delta until significant data growth) | 0 |
| Nagad / Rocket / card aggregator commissions | revenue-share (varies 1.5%–3.5% per transaction) |

---

## 9. Annual Cost Summary

| Year | Most Likely (BDT) | Worst Case (BDT) |
|---|---|---|
| Year 1 (MVP launch) | 8,600 – 25,000 | 50,000 |
| Year 2+ (steady state) | 600 – 5,000 | 25,000 |
| Year 3+ (Phase 2 activated) | 5,000 – 30,000 | 80,000 |
| Year 4+ (Phase 3, scaling) | 50,000 – 150,000 | 250,000 |

Plus:
- bKash commission (~1.85% of online revenue), **always variable**.
- Developer time, **outside this estimate**.

---

## 10. Key Cost Risk Flags

1. **Firebase Phone Auth pricing.** Verify current rates at start of build — Google adjusts pricing periodically. If BD rates change to per-SMS pricing model, reassess.
2. **bKash commission negotiation.** Larger merchants negotiate down to ~1.5%. Worth requesting after first 6 months of confirmed transaction volume.
3. **VPS reliability.** 1c/2GB is tight; if VPS provider has downtime or performance issues, upgrade timeline accelerates. Budget mental BDT 14,000+/year contingency.
4. **Cloudflare free tier limits.** 100k requests/month is plenty for 1k DAU but a viral moment could push over. Monitor monthly.
5. **Backup storage growth.** Cloudflare R2 stays cheap until DB grows >50GB. Re-estimate at 30GB threshold.

---

## 11. Cost-Saving Optimizations Already Built Into Plan

- Self-managed Postgres + Redis on existing VPS (saves ~BDT 22,000/year vs managed).
- Free tiers across the entire monitoring + frontend hosting stack.
- bKash direct merchant integration (saves ~0.65% per transaction vs SSLCommerz aggregator).
- No transactional SMS dependency (saves ~BDT 6,000–8,000/year vs PRD plan).
- Cloudflare Origin Certificate eliminates Let's Encrypt operational burden.
- Vercel free tier covers entire frontend without hitting paid bandwidth.
- WeasyPrint instead of Playwright/Puppeteer eliminates a heavyweight container dependency.
- No pre-computed analytics rollups MVP (live SQL handles 1k DAU on existing Postgres).

---

## Summary

**MVP launch cost: roughly BDT 8,600–25,000 in Year 1, dropping to BDT 600–5,000/year in Year 2+ as one-time setup amortizes out.**

bKash commission (~1.85% of online revenue) is the dominant variable cost and treated as cost-of-goods.

Plan delivers ~50–70% lower annual fixed cost than the original PRD estimate of BDT 28,500–60,500, primarily by leveraging the existing VPS, replacing SMS gateway with Firebase, and dropping booking-confirmation SMS.
