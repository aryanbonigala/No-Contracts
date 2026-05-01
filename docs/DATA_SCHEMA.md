# Data schema plan (not implemented in v0.1)

This document describes **intended** Postgres entities once ingestion and migrations exist. Table names and columns may change; v0.1 does not create tables.

## Design principles

- **Immutable raw payloads** stored alongside normalized rows (JSON/BLOB column or object storage pointer).
- **Provenance**: `ingested_at`, source request identifiers, and API version.
- **Time in UTC** with timezone-aware types (`timestamptz`).
- **No secrets** in rows (API keys stay in env / vault).

## Core entities (planned)

### `markets`

- `market_id` (text, PK)
- `event_ticker`, `market_ticker` (text)
- `open_time`, `close_time` (`timestamptz`, nullable)
- `status` (text / enum)
- `rules_summary` or `rules_hash` (text) — pointer to full rules text
- `raw_payload` (jsonb)
- `ingested_at` (`timestamptz`)

### `orderbook_snapshots`

- `id` (bigserial PK)
- `market_id` (FK → `markets.market_id`)
- `observed_at` (`timestamptz`) — wall clock when snapshot was taken
- `sequence` or `api_cursor` (bigint/text, nullable)
- `bids` / `asks` (jsonb) — price levels for YES/NO legs as ingested
- `raw_payload` (jsonb)

### `trades`

- `id` (bigserial PK)
- `market_id` (FK)
- `trade_time` (`timestamptz`)
- `price_cents`, `contracts`, `side` (int/smallint/text)
- `raw_payload` (jsonb)

### `candles` (if sourced)

- `market_id`, `interval`, `period_start` (PK composite)
- OHLCV numeric columns
- `raw_payload` (jsonb)

### `settlements`

- `market_id` (PK or unique)
- `settled_at` (`timestamptz`)
- `outcome` (text / smallint — YES/NO/void per Kalshi encoding)
- `raw_payload` (jsonb)

### `event_clusters`

- `cluster_id` (text/uuid PK)
- `reference_time_utc` (`timestamptz`) — must align with split rules in `RESEARCH_RULES.md`
- `metadata` (jsonb) — human label, keywords, risk notes
- Optional: linkage table `cluster_markets(cluster_id, market_id)`

### `research_splits`

Materialized split assignments (optional convenience table):

- `cluster_id` (PK, FK)
- `split_name` (`train` | `validation` | `test`)
- `generated_at`, `split_rules_version`

## Indexes (planned)

- `orderbook_snapshots(market_id, observed_at)`
- `trades(market_id, trade_time)`
- `markets(event_ticker, open_time)`

## Migrations

Future work: introduce Alembic (or equivalent) under something like `migrations/` and keep DDL out of application import side-effects.
