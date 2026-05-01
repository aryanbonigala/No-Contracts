# Data schema (v0.3 — implemented)

This document matches the SQLAlchemy models in `kalshi_no_carry.db.schema`. Tables are created via `create_all_tables()` (see `scripts/init_db.py`). **Alembic** is not wired yet; schema evolution will add versioned migrations when needed.

## Design principles

- **Raw JSON provenance** (`raw_json`) stores the latest API payload (or a faithful copy) next to denormalized columns for indexing and quick filters.
- **Timestamps** use `DateTime(timezone=True)` (PostgreSQL `timestamptz`; SQLite stores UTC without tz — ORM tests normalize).
- **No secrets** in tables (credentials stay in env / vault).
- **Idempotent upserts** in `kalshi_no_carry.db.repositories` preserve `first_seen_at` and refresh `last_seen_at` + `raw_json`.
- **Splits:** `event_clusters` + `strategy_splits` support chronological **60/20/20** assignments at **cluster** granularity (see `RESEARCH_RULES.md`). The **test** holdout must not be tuned against after assignment.

## JSON columns

Portable `JSON` with PostgreSQL `JSONB` variant for efficient storage and indexing on Postgres:

```text
JSON().with_variant(JSONB(), "postgresql")
```

## Tables

### `api_fetch_log`

Audit trail for ingestion / HTTP fetches (used by future collectors).

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

**Why snapshots matter:** backtests must use **executable** bid/ask assumptions, not last trade, per `RESEARCH_RULES.md`. Storing each pull’s raw book preserves auditability; denormalized bests speed queries.

### `event_clusters`

Groups markets/events for **correlation-aware** research and **splits**.

| Column | Notes |
|--------|--------|
| `cluster_id` | Primary key (stable string / UUID as text). |
| `cluster_key` | Optional hash/key for clustering version. |
| `event_ticker`, `series_ticker`, `category` | Optional linkage. |
| `representative_title` | Human-readable label. |
| `close_time` | Optional reference time for chronological ordering. |
| `raw_json` | Optional clustering metadata blob. |
| `created_at`, `updated_at` | Maintained by repositories. |

### `strategy_splits`

**One row per cluster** — assignment into train / validation / test.

| Column | Notes |
|--------|--------|
| `cluster_id` | PK, FK → `event_clusters.cluster_id` (cascade delete). |
| `split_name` | One of: `train`, `validation`, `test` (enforced in Python). |
| `split_version` | Version string, e.g. rule + data cutoff (indexed). |
| `assigned_at` | When the split row was written. |
| `notes` | Optional. |

The **final test** fraction must remain **untouched** after assignment for honest reporting (`RESEARCH_RULES.md`).

## Indexes

- `raw_orderbook_snapshots`: `(market_ticker, fetched_at)` composite; individual indexes on `fetched_at` and `market_ticker` as defined in the model.

## Migrations

v0.3 uses `Base.metadata.create_all()`. Future work: add Alembic with autogenerate against this metadata for zero-drift production deploys.
