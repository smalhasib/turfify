# Turfify — Turf Management & Booking Platform

Mobile-first turf booking platform for Bangladesh. Hourly slot rentals, bKash payments, admin dashboard.

> **Status:** In active development. See [`Turf_Management_Plan.md`](./Turf_Management_Plan.md) for the locked design.

## Documentation

- [`Turf_Management_System_Requirements.md`](./Turf_Management_System_Requirements.md) — original product requirements
- [`Turf_Management_Plan.md`](./Turf_Management_Plan.md) — implementation plan (single source of truth)
- [`Turf_Management_Cost_Estimation.md`](./Turf_Management_Cost_Estimation.md) — cost breakdown

## Tech Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 14 (TypeScript, Tailwind) |
| Backend | FastAPI (Python 3.13) |
| Database | PostgreSQL 15 |
| Cache / Locks | Redis 7 |
| Auth | Firebase Phone Authentication |
| Payments | bKash PGW Tokenized Checkout |
| PDF | WeasyPrint |
| Reverse Proxy | nginx (HTTP/2) |
| Edge | Cloudflare |
| Frontend Hosting | Vercel |
| Backend Hosting | VPS |
| Monitoring | Sentry + HetrixTools |

## Repository Layout

```
turfify/
├── backend/             # FastAPI service
├── frontend/            # Next.js app
├── docker/              # Docker artifacts (Dockerfiles, configs)
├── scripts/             # Operational scripts (seed, backup, demo)
├── docker-compose.dev.yml
├── Turf_Management_*.md
└── README.md
```

## Local Development Setup

### Prerequisites

- Docker Desktop
- Python 3.13
- Node 22
- pnpm (`npm install -g pnpm`)

### Bootstrap

```bash
# 1. Start infrastructure
docker compose -f docker-compose.dev.yml up -d

# 2. Backend
cd backend
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8800

# 3. Frontend (separate terminal)
cd frontend
pnpm install
pnpm dev
```

App opens at `http://localhost:3000`. API at `http://localhost:8000/v1/docs` (OpenAPI Swagger).

### Useful URLs

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8800 |
| API docs (Swagger) | http://localhost:8800/v1/docs |
| Adminer (DB UI) | http://localhost:8090 |
| Mailpit (email catcher, disabled MVP) | http://localhost:8025 — uncomment in `docker-compose.dev.yml` when email work starts |

## Testing

Three test layers, all required:

```bash
# Backend
cd backend
pytest tests/unit -x          # unit
pytest tests/integration -x   # integration (testcontainers spin up Postgres + Redis)

# Frontend
cd frontend
pnpm test                     # Vitest unit
pnpm test:e2e                 # Playwright E2E (full browser)
```

## Development Phases

See [`Turf_Management_Plan.md` § 20](./Turf_Management_Plan.md). Built incrementally over 16 phases:

- **Phase 0** — Bootstrap (repo, tooling, CI)
- **Phase 1** — Database schema + migrations
- **Phase 2** — Auth (Firebase + JWT)
- **Phase 3** — Slot generation + calendar API
- **Phase 4** — Booking hold + locking
- **Phase 5** — Discount codes
- **Phase 6** — bKash payment integration
- **Phase 7** — Cash on arrival
- **Phase 8** — PDF receipts
- **Phase 9** — Cancellation + refund
- **Phase 10** — Admin booking creation + custom pricing
- **Phase 11** — Admin management UIs
- **Phase 12** — Reporting + customer log
- **Phase 13** — Static pages + polish
- **Phase 14** — Demo setup
- **Phase 15** — Production deploy

## Branching & Commits

- `main` is production. Feature branches → PR → squash merge.
- Commit format: [Conventional Commits](https://www.conventionalcommits.org/) (`feat(scope): subject`, `fix(scope): subject`, `chore(scope): subject`).
- Pre-commit hooks run ruff, prettier, mypy.

## License

Proprietary. All rights reserved.
