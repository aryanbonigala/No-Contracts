# Kalshi NO Carry (v0.5.4 — JSON/JSONB Alembic alignment; clustering and research splits)

Production-oriented **research** codebase for testing a statistical thesis on Kalshi binary markets:

**Thesis (informal):** there may be edge in buying high-confidence **NO** contracts when the market-implied NO price is below the “true” NO probability after adjusting for fees, spread, ambiguity risk, and correlated event risk.

This repository is **v0.5.4** (`Kalshi_NO_Carry_v0.5.4_JSONBMigrationAlignment`). **v0.5** added **deterministic event clustering** and **leakage-safe chronological train / validation / test assignment** on top of **v0.4** read-only collectors. **v0.5.1** fixed **`strategy_splits`** to use a composite primary key **`(cluster_id, split_version)`**. **v0.5.2** added **Alembic** infrastructure. **v0.5.3** froze **`0001_initial_schema`** as explicit DDL. **v0.5.4** aligns that migration’s JSON columns with the ORM: **JSONB on Postgres**, **JSON on SQLite**, via **`sa.JSON().with_variant(postgresql.JSONB(...), "postgresql")`** — same convention as **`create_all`**. Collectors still persist **raw events**, **raw markets**, **append-only orderbook snapshots**, and **API fetch logs**. This release does **not** trade, place orders, engineer strategy features, train models, or run the NO-carry backtester.

## Safety / scope

- **Read-only:** all ingestion uses public `GET` (and optional authenticated read) paths only.
- **Secrets:** never commit `.env`, keys, or passwords. Scripts print **summary JSON** only — no raw `DATABASE_URL`, no API keys.

## Layout

- `src/kalshi_no_carry/collectors/` — `events.py`, `markets.py`, `orderbooks.py`, `common.py`
- `src/kalshi_no_carry/db/` — schema + repositories
- `src/kalshi_no_carry/research/` — `event_clustering.py`, `splits.py`, `build_splits.py` (clustering + split materialization)
- `scripts/` — collectors, `build_splits.py`, `init_db.py`, `db_migrate.py`, `db_revision.py`, …
- `alembic/` — versioned DDL (see **Database setup** below)
- `tests/` — fakes + SQLite in-memory (**no live Kalshi or Postgres required** for default pytest)

## Install

```bash
cd kalshi-no-carry
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration

- **Kalshi:** `KALSHI_BASE_URL` (full `…/trade-api/v2`), optional auth env vars — see `.env.example`.
- **Database:** **`DATABASE_URL` is required for collector scripts and for `build_splits.py`** (Postgres recommended on a VM; `scripts/check_env.py` shows a **redacted** preview). **Offline unit tests** use SQLite in-memory and do not need `DATABASE_URL`.

### Database setup (two options)

1. **Fresh local / disposable dev database** — `SQLAlchemy` **`create_all`** (does **not** alter existing tables; safe for empty SQLite or a new Postgres database):

   ```bash
   python scripts/init_db.py
   ```

   Collector scripts may also use **`--create-tables`**, which calls the same helper.

2. **Versioned schema (recommended for any database with data you care about)** — **Alembic** tracks applied revisions and runs explicit upgrade steps:

   ```bash
   python scripts/db_migrate.py
   ```

   Requires **`DATABASE_URL`**. This runs **`alembic upgrade head`**. The Alembic environment reads `DATABASE_URL` from the environment or from `.env` via **`get_settings()`**; it never prints the raw URL.

**`create_all` vs migrations:** `create_all_tables()` only creates missing tables from the **current** ORM metadata. It will **not** migrate an older physical schema (for example, a pre–v0.5.1 `strategy_splits` primary key). Use **`create_all`** only for **quick empty DB / test bootstraps**. For databases with data you care about, use **Alembic** (`scripts/db_migrate.py`).

**Frozen revisions:** committed Alembic files under `alembic/versions/` are **version-controlled, explicit DDL**. Do **not** implement production migrations as **`Base.metadata.create_all`** inside a revision — that would re-bind migration history to whatever the ORM happens to be when someone runs an old revision on a new checkout. Add new revisions with explicit `op.create_table` / `alter_column` (or autogenerate **plus hand review**) for each schema change.

**New revisions:** after editing ORM models, generate a migration (review the file before committing):

```bash
python scripts/db_revision.py "describe change"
# optional: compare DB to models (requires DATABASE_URL)
python scripts/db_revision.py "describe change" --autogenerate
```

## Run collectors (requires `DATABASE_URL` + network to Kalshi)

Events + markets (one combined CLI):

```bash
python scripts/collect_markets.py --create-tables --limit 100 --max-pages 1
```

Orderbooks for explicit tickers or for currently open markets:

```bash
python scripts/collect_orderbooks.py --ticker SOME-TICKER
python scripts/collect_orderbooks.py --active-markets --limit 50 --max-pages 1
```

End-to-end smoke (exchange status optional, one page events/markets, first N market orderbooks):

```bash
python scripts/collect_snapshot.py --create-tables --limit 20 --orderbook-count 10
```

## Build event clusters and splits (requires `DATABASE_URL`, no Kalshi)

Run **after** collectors have populated `raw_events` and `raw_markets`. This upserts **`event_clusters`** from raw data, then writes **`strategy_splits`** for the given **`--split-version`** (you may store several versions side by side). **`--overwrite`** replaces rows for **that version only**.

```bash
python scripts/build_splits.py --split-version v0.5_chronological_60_20_20
python scripts/build_splits.py --overwrite --split-version v0.5_chronological_60_20_20
python scripts/build_splits.py --clusters-only
python scripts/build_splits.py --splits-only --split-version v0.5_chronological_60_20_20
```

The script prints a **safe JSON** summary (no secrets). Use `--create-tables` if the schema is not initialized yet.

## Tests

Offline-only default suite (mocks + SQLite):

```bash
pytest
```

Optional Postgres smoke: set `RUN_DB_INTEGRATION_TESTS=1` and `DATABASE_URL` (unchanged from v0.3).

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — ingestion + research split flow
- [`docs/DATA_SCHEMA.md`](docs/DATA_SCHEMA.md) — tables and how collectors / split builder fill them
- [`docs/RESEARCH_RULES.md`](docs/RESEARCH_RULES.md) — research guardrails and sealed test policy

## Deferred (not in this track)

Strategy features, model training, NO-carry backtester, order placement, portfolio, execution.
