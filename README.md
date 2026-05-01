# Kalshi NO Carry (v0.3 — Postgres persistence layer)

Production-oriented **research** codebase for testing a statistical thesis on Kalshi binary markets:

**Thesis (informal):** there may be edge in buying high-confidence **NO** contracts when the market-implied NO price is below the “true” NO probability after adjusting for fees, spread, ambiguity risk, and correlated event risk.

This repository is **v0.3** (`Kalshi_NO_Carry_v0.3_PostgresPersistenceLayer`): it keeps the **v0.2** read-only **`KalshiClient`**, and adds a **SQLAlchemy** schema plus **repository** helpers for Postgres (SQLite in unit tests). **Collectors are not implemented yet** — nothing automatically fetches Kalshi into the database in this version.

## Safety / scope

- **Read-only API usage:** `KalshiClient` has no order placement; collectors will remain read-only when added.
- **Secrets:** never commit `.env`, PEM keys, API keys, or database passwords. `scripts/check_env.py` prints only **redacted** database URL forms.

## Layout

- `src/kalshi_no_carry/` — `kalshi_client.py`, `database.py`, `db/schema.py`, `db/repositories.py`
- `scripts/` — `init_db.py`, `db_healthcheck.py`, `check_env.py`, `run_market_snapshot.py`, …
- `tests/` — pytest (default suite uses in-memory SQLite; **no live Postgres required**)
- `docs/` — architecture, **implemented** data schema, research rules

## Install

From the repo root (`kalshi-no-carry/`):

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Runtime dependencies include **SQLAlchemy** and **psycopg** for PostgreSQL drivers.

## Configuration

Copy `.env.example` to `.env`. See `scripts/check_env.py` for a safe summary.

### Kalshi (unchanged from v0.2)

- `KALSHI_BASE_URL=https://api.elections.kalshi.com/trade-api/v2` (full path required)
- Optional: `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH` for authenticated reads

### Database (optional until you initialize tables)

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE_NAME
```

`DATABASE_URL` may be omitted at import time; scripts that need a DB exit with a clear error if it is missing.

For **optional** integration tests against a real Postgres:

```env
RUN_DB_INTEGRATION_TESTS=1
DATABASE_URL=postgresql://...
```

## Initialize database (DDL)

Requires `DATABASE_URL`:

```bash
python scripts/init_db.py
```

Creates all tables from `Base.metadata` (idempotent if tables already exist). **Does not print credentials.**

## Database healthcheck

```bash
python scripts/db_healthcheck.py
```

Runs `SELECT 1` on the configured database.

## Run tests

```bash
pytest
```

Default tests use **SQLite in-memory** (no Docker Postgres needed). One integration test is **skipped** unless `RUN_DB_INTEGRATION_TESTS=1` and `DATABASE_URL` are set.

## Market snapshot (smoke test, no DB)

```bash
python scripts/run_market_snapshot.py
python scripts/run_market_snapshot.py --ticker YOUR-MARKET-TICKER
```

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — v0.3 database + client boundaries
- [`docs/DATA_SCHEMA.md`](docs/DATA_SCHEMA.md) — table and column reference
- [`docs/RESEARCH_RULES.md`](docs/RESEARCH_RULES.md) — methodological guardrails

## Deployment note (DigitalOcean VM)

Use a managed Postgres instance (or container) and inject `DATABASE_URL` via environment — do not bake secrets into images.
