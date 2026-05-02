# Data schema (v0.3 DDL + v0.4 ingestion + v0.5 clustering/splits)

This document matches the SQLAlchemy models in `kalshi_no_carry.db.schema`. You can create tables in two ways: **`create_all_tables()`** (see `scripts/init_db.py`) for a **fresh** disposable database, or **Alembic** (`scripts/db_migrate.py`, `alembic/versions/`) for **versioned, explicit** schema DDL on databases that hold research data. **Alembic revision files are frozen** — baseline `0001_initial_schema` uses explicit `op.create_table` operations (not `create_all` inside the migration) and matches the ORM’s **JSON / JSONB** convention (see below).

**v0.4 collectors** populate `raw_events`, `raw_markets`, and `raw_orderbook_snapshots` using `KalshiClient` plus `db.repositories`, and append rows to **`api_fetch_log`**.

**v0.5 split builder** (`research.build_splits`, `scripts/build_splits.py`) reads **`raw_events`** and **`raw_markets`**, upserts **`event_clusters`**, then writes **`strategy_splits`** rows for a required **`split_version`** string (default in the CLI: `v0.5_chronological_60_20_20`).

## Design principles

- **Raw JSON provenance** (`raw_json`) stores the latest API payload (or a faithful copy) next to denormalized columns for indexing and quick filters.
- **Timestamps** use `DateTime(timezone=True)` (PostgreSQL `timestamptz`; SQLite stores UTC without tz — ORM tests normalize).
- **No secrets** in tables (credentials stay in env / vault).
- **Idempotent upserts** in `kalshi_no_carry.db.repositories` preserve `first_seen_at` and refresh `last_seen_at` + `raw_json` where applicable.
- **`raw_orderbook_snapshots` are not split directly.** Split membership flows **market → event cluster → `strategy_splits`** once features/backtests join snapshots to markets. Until that join exists in code, treat orderbook rows as **unlabeled** at rest.

## JSON columns

Portable `JSON` with PostgreSQL `JSONB` variant for efficient storage and indexing on Postgres:

```text
JSON().with_variant(JSONB(), "postgresql")
```

The baseline Alembic revision **`0001_initial_schema`** (v0.5.4+) uses the same shape explicitly: `sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")` via a small `json_type()` helper, so **`create_all` and `0001` agree on Postgres (`JSONB`) vs SQLite (`JSON`)**. **Normal tests do not require live Postgres** — behavior is covered by offline compilation checks.

If you already have a PostgreSQL database where JSON columns were created as plain **`JSON`** (not **`JSONB`**) and you require exact type alignment, you may need a **manual or follow-up migration** (`ALTER TABLE ... ALTER COLUMN ... SET DATA TYPE ...` or rebuild); this repository does not ship an automatic conversion for that case.

## Tables

### `api_fetch_log`

Audit trail for ingestion / HTTP fetches (used by collectors).

| Column | Notes |
|--------|--------|
| `id` | Integer PK, autoincrement (portable across SQLite tests and Postgres). |
| `fetched_at` | When the fetch finished (UTC), indexed. |
| `endpoint` | Logical path or label, e.g. `/markets`. |
| `params_json` | Query/body params as JSON (nullable). |
| `status_code` | HTTP status when applicable. |
| `success` | Boolean outcome. |
| `error_message` | Error text (nullable). |
| `row_count` | Optional count of rows parsed. |
| `source` | Optional pipeline label. |

### `raw_events`

Kalshi **event** objects (ticker-level).

| Column | Notes |
|--------|--------|
| `event_ticker` | Primary key. |
| `series_ticker`, `title`, `category`, `status` | Denormalized; indexed where useful. |
| `raw_json` | Latest raw event document. |
| `first_seen_at`, `last_seen_at`, `fetched_at` | Provenance timestamps. |

### `raw_markets`

Kalshi **market** rows (`GET /markets` style objects).

Denormalized price fields are **integer cents** parsed from Kalshi dollar strings when present (`yes_bid_dollars` → `yes_bid_cents`, etc.). `volume` / `open_interest` approximate fixed-point counts as integers.

| Column | Notes |
|--------|--------|
| `market_ticker` | Primary key (`ticker` in API). |
| `event_ticker`, `series_ticker`, … | Filters for research. |
| `open_time`, `close_time`, `expiration_time`, `settlement_time` | Parsed from ISO fields when present. |
| `result` | Settlement outcome string when set. |
| `raw_json` | Full latest market JSON. |
| `first_seen_at`, `last_seen_at`, `fetched_at` | Provenance. |

### `raw_orderbook_snapshots`

Time series of **order book** snapshots for reconstructing **executable** prices.

Kalshi returns YES and NO **bids** only. Denormalized columns store best bid/ask **cents** and **sizes** (integers) aligned with `derive_executable_prices_from_orderbook()` (asks synthesized as \(100 - \text{opposite bid}\) cents).

| Column | Notes |
|--------|--------|
| `id` | Integer PK, autoincrement. |
| `market_ticker` | Indexed; composite index with `fetched_at`. |
| `fetched_at` | Observation time (UTC), indexed. |
| `best_*_cents`, `best_*_size` | Best executable top-of-book view. |
| `raw_json` | Full orderbook JSON from the API. |

**Splits:** rows inherit **train / validation / test** only **indirectly** via their `market_ticker` → `raw_markets.event_ticker` → `event_clusters` → `strategy_splits` (future feature/backtest joins). Do not assign split labels per orderbook row in storage.

### `event_clusters`

Groups related **raw events** and **raw markets** so **all markets under the same `event_ticker`** share one cluster (with a deterministic fallback key when `event_ticker` is missing on a market row).

| Column | Notes |
|--------|--------|
| `cluster_id` | Primary key; deterministic string from `cluster_key` (see `research.event_clustering`). |
| `cluster_key` | Stable logical key (e.g. `event_ticker:…` or `fallback:…`). |
| `event_ticker`, `series_ticker`, `category` | Optional linkage / metadata. |
| `representative_title` | Human-readable label. |
| `close_time` | Reference instant for **chronological ordering** of clusters (earliest per-row reference time across members; see clustering code). |
| `raw_json` | Provenance: source tickers, cluster key copy, etc. |
| `created_at`, `updated_at` | Maintained by repositories. |

### `strategy_splits`

**One row per `(cluster_id, split_version)`** — assignment into `train` / `validation` / `test` for that version. The same cluster may appear in **multiple** `split_version` rows at once (e.g. frozen baseline vs experimental relabel).

| Column | Notes |
|--------|--------|
| `cluster_id` | Composite PK (with `split_version`), FK → `event_clusters.cluster_id` (cascade delete). |
| `split_version` | Composite PK; explicit version label, e.g. `v0.5_chronological_60_20_20`. |
| `split_name` | One of: `train`, `validation`, `test` (enforced in Python). |
| `assigned_at` | When the split row was written. |
| `notes` | Optional. |

**Design (v0.5.1):** the table uses a **composite primary key** `(cluster_id, split_version)` so `split_version` is a real versioning dimension, not a decorative column. SQLite and Postgres both accept this layout via SQLAlchemy `create_all`.

**`split_version` semantics**

- Identifies a **frozen rule + data snapshot** policy. **Multiple versions can coexist** in one database; compare or select among them explicitly in downstream code.
- Once a `split_version` has been used for model or strategy **selection**, **do not overwrite it casually**; prefer creating a **new** `split_version` string for a new experimental split policy.
- **`overwrite=True`** in `assign_chronological_splits` is for **controlled rebuilds only**: it deletes **only** rows matching the requested `split_version`, then rebuilds assignments for **all** rows in `event_clusters` at that moment. Other `split_version` values are left unchanged.

The **final test** bucket must remain **sealed** after honest reporting (see `RESEARCH_RULES.md`).

## Indexes

- `raw_orderbook_snapshots`: `(market_ticker, fetched_at)` composite; individual indexes on `fetched_at` and `market_ticker` as defined in the model.

## Migrations (v0.5.2+; frozen baseline; JSONB alignment v0.5.4)

**Alembic** is the supported mechanism for **changing** the schema over time. Revisions live under `alembic/versions/`; `alembic/env.py` still exposes `Base.metadata` for **autogenerate** comparisons only. Run **`python scripts/db_migrate.py`** (requires `DATABASE_URL`) to apply `alembic upgrade head`.

**Frozen revision files:** each committed migration should contain **explicit operations** (`op.create_table`, `op.add_column`, …) so a given revision id always means the same DDL. The baseline **`0001_initial_schema`** is **frozen explicit DDL**; it does **not** call `Base.metadata.create_all`. **Do not** add new migrations that delegate upgrades to `create_all` for production paths — use incremental, reviewable DDL (or autogenerate + edit) per change.

**JSON / JSONB (v0.5.4):** **`0001_initial_schema`** defines JSON-ish columns with the same **`JSON` / `JSONB`** dialect mapping as the ORM (`SQLite` → `JSON`, `PostgreSQL` → `JSONB`), so paths **`init_db` / `create_all`** and **`db_migrate` / `0001`** are intended to match on a fresh database.

**`create_all` (unchanged):** `scripts/init_db.py` and collector `--create-tables` still call `Base.metadata.create_all()`. That remains appropriate for **empty** SQLite files or disposable dev databases. It does **not** alter existing tables when the ORM definition diverges (no automatic `ALTER TABLE`).

**`strategy_splits` (v0.5.1):** the primary key is **`(cluster_id, split_version)`** (composite). **`0001_initial_schema`** encodes that layout explicitly, including **`ON DELETE CASCADE`** on `cluster_id` → `event_clusters.cluster_id`.

**Pre–v0.5.1 databases:** if `strategy_splits` was created with **`cluster_id` only** as the primary key, **neither** `create_all` **nor** replaying **`0001`** on an existing DB will safely reshape that table in place. **Recreate** the database (or write a **custom** follow-on migration with explicit `ALTER TABLE` / rebuild steps) before relying on Alembic history. There is no automated upgrade path from the old PK layout in this repository.
