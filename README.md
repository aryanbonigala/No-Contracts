# Kalshi NO Carry (v0.9 — end-to-end research pipeline runner; read-only)

Production-oriented **research** codebase for testing a statistical thesis on Kalshi binary markets:

**Thesis (informal):** there may be edge in buying high-confidence **NO** contracts when the market-implied NO price is below the "true" NO probability after adjusting for fees, spread, ambiguity risk, and correlated event risk.

This repository is **v0.9.0** (`Kalshi_NO_Carry_v0.9_EndToEndResearchPipelineRunner`). **v0.9** adds **`research/pipeline_runner.py`** and **`scripts/run_research_pipeline.py`**: a **single orchestrated command** that runs migrations (optional), **opt-in** Kalshi collectors, cluster/split build, outcome labels, feature rows (with **`label_version`**), dataset audit, and an optional read-only backtest — printing **one JSON summary** (no secrets). **Default behavior is stored-DB only** (no network). **`v0.8`** labeling + audit and **`v0.7`** backtests remain as documented below.

## Safety / scope

- **Read-only vs Kalshi:** all ingestion uses public `GET` (and optional authenticated read) paths only; no order placement.
- **Backtests:** consume **frozen** `research_feature_rows` only; they **never** submit orders or move balances.
- **Labels:** normalized outcomes live in **`research_market_labels`** (and optionally on feature rows via **`--label-version`**) for **scoring and coverage only** — not for pricing or entry-feature computation.
- **Secrets:** never commit `.env`, keys, or passwords. Scripts print **summary JSON** only — no raw `DATABASE_URL`, no API keys.

## Layout

- `src/kalshi_no_carry/collectors/` — `events.py`, `markets.py`, `orderbooks.py`, `common.py`
- `src/kalshi_no_carry/db/` — schema + repositories
- `src/kalshi_no_carry/research/` — clustering, splits, **`features.py`**, **`feature_dataset.py`**, **`outcomes.py`**, **`dataset_audit.py`**, **`backtest_config.py`**, **`backtest_no_carry.py`**, `build_splits.py`
- `scripts/` — collectors, `build_splits.py`, **`build_labels.py`**, **`build_features.py`**, **`audit_research_dataset.py`**, **`run_research_pipeline.py`**, **`run_backtest.py`**, `init_db.py`, `db_migrate.py`, `db_revision.py`, …
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
- **Database:** **`DATABASE_URL` is required** for collector scripts, `build_splits.py`, **`build_labels.py`**, **`build_features.py`**, **`audit_research_dataset.py`**, **`run_research_pipeline.py`**, and **`run_backtest.py`** (Postgres recommended on a VM; `scripts/check_env.py` shows a **redacted** preview). **Offline unit tests** use SQLite in-memory and do not need `DATABASE_URL`.

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

**`create_all` vs migrations:** `create_all_tables()` only creates missing tables from the **current** ORM metadata. It will **not** migrate an older physical schema. Use **`create_all`** only for **quick empty DB / test bootstraps**. For databases with data you care about, use **Alembic** (`scripts/db_migrate.py`).

**Frozen revisions:** committed Alembic files under `alembic/versions/` are **version-controlled, explicit DDL**. Baseline **`0001`** … **`0004_market_outcome_labels`** (labels + feature-row label columns) are explicit migrations.

**New revisions:** after editing ORM models, generate a migration (review the file before committing):

```bash
python scripts/db_revision.py "describe change"
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

```bash
python scripts/build_splits.py --split-version v0.5_chronological_60_20_20
python scripts/build_splits.py --overwrite --split-version v0.5_chronological_60_20_20
python scripts/build_splits.py --clusters-only
python scripts/build_splits.py --splits-only --split-version v0.5_chronological_60_20_20
```

The script prints a **safe JSON** summary (no secrets). Use `--create-tables` if the schema is not initialized yet.

## Build outcome labels (requires `DATABASE_URL`, no Kalshi)

Populate **`research_market_labels`** from stored **`raw_markets`** using **`research/outcomes.py`** (deterministic; no title inference; no live API). Default **`--label-version`**: **`v0.8_market_outcome_labels`**.

```bash
python scripts/build_labels.py --label-version v0.8_market_outcome_labels
python scripts/build_labels.py --delete-existing --label-version v0.8_market_outcome_labels
```

Optional: **`--market-ticker`** (repeatable), **`--status`**, **`--limit`**, **`--migrate`**, **`--create-tables`**.

## Build feature dataset (requires `DATABASE_URL`, no Kalshi)

**Default:** **train + validation only** — the **sealed test** split is **excluded** unless you pass **`--include-test`**. Feature rows are **versioned** with **`--feature-version`** (default `v0.6_orderbook_snapshot_features`) and tied to **`--split-version`** (default `v0.5_chronological_60_20_20`). This step **does not** open positions or hit the trading API.

```bash
python scripts/build_features.py --split-version v0.5_chronological_60_20_20
python scripts/build_features.py --dry-run --limit 100
python scripts/build_features.py --include-test --split-version v0.5_chronological_60_20_20
python scripts/build_features.py --delete-existing --split-version v0.5_chronological_60_20_20 --feature-version v0.6_orderbook_snapshot_features
python scripts/build_features.py --split-version v0.5_chronological_60_20_20 --label-version v0.8_market_outcome_labels
python scripts/build_features.py --migrate --create-tables   # dev bootstrap only
```

Flags: **`--label-version`** (optional) merges **`research_market_labels`** into feature row **label_* columns** for backtests/audits; **`--splits`** (comma-separated, default `train,validation`), **`--market-ticker`** (repeatable), **`--dry-run`**, **`--delete-existing`**, **`--migrate`**, **`--create-tables`**.

## Audit research dataset (requires `DATABASE_URL`, no Kalshi)

```bash
python scripts/audit_research_dataset.py --split-version v0.5_chronological_60_20_20 --feature-version v0.6_orderbook_snapshot_features
python scripts/audit_research_dataset.py --label-version v0.8_market_outcome_labels
python scripts/audit_research_dataset.py --include-test --label-version v0.8_market_outcome_labels
```

**Default:** feature-row portion of the audit **excludes test** (same as **`build_features`** / **`run_backtest`**). Use **`--include-test`** only when intentionally auditing the sealed split.

## End-to-end research pipeline (v0.9; requires `DATABASE_URL`)

**`scripts/run_research_pipeline.py`** runs stages in order: optional **Alembic migrate** and **`create_all`**, **opt-in** `--collect-markets` / `--collect-orderbooks` (network + credentials), **build splits**, **build labels**, **build features** (with **`--label-version`**), **audit**, optional **`--run-backtest`**. It prints a **single JSON object** with per-stage summaries, **`high_level_counts`** (when audit ran), **`next_recommended_action`**, and **no secrets**.

- **Default:** **no Kalshi HTTP** — only reads/writes the database (same philosophy as running the individual scripts on a filled DB).
- **Test split:** omitted by default; **`--include-test`** adds a loud **`TEST_SPLIT_INCLUDED`** warning in the summary.
- **Skipping:** `--skip-splits`, `--skip-labels`, `--skip-features`, `--skip-audit`.

```bash
python scripts/run_research_pipeline.py
python scripts/run_research_pipeline.py --migrate
python scripts/run_research_pipeline.py --delete-existing-labels --delete-existing-features
python scripts/run_research_pipeline.py --run-backtest --max-no-ask-cents 95
python scripts/run_research_pipeline.py --collect-markets --collect-orderbooks --limit 100   # explicit network
python scripts/run_research_pipeline.py --include-test --run-backtest   # sealed test — document why
```

## Run read-only backtest (requires `DATABASE_URL`, no Kalshi)

**Default:** **train + validation** feature rows only — **test is excluded** unless **`--include-test`**. **Hypothetical PnL** is computed **only when** `label_market_result` (and friends) are present on feature rows; missing labels yield **unscored** trades — the harness **does not** invent outcomes.

```bash
python scripts/run_backtest.py --max-no-ask-cents 95 --dry-run
python scripts/run_backtest.py --max-no-ask-cents 90 --min-seconds-to-close 3600
python scripts/run_backtest.py --include-test --backtest-version v0.7_no_carry_baseline_FINAL_TEST_ONCE
```

Use **`--dry-run`** to compute summaries without writing **`backtest_runs`** / **`backtest_trades`**. **`--delete-existing-run`** removes a prior run with the same deterministic **`run_id`** (derived from the full config). Strategies include `no_carry_price_threshold_v0` (default) and `no_carry_required_prob_placeholder_v0` (probability buckets only, no entries). This is **not** live trading.

## Tests

Offline-only default suite (mocks + SQLite):

```bash
pytest
```

Optional Postgres smoke: set `RUN_DB_INTEGRATION_TESTS=1` and `DATABASE_URL`.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — ingestion + v0.9 pipeline + splits + features + labels + audit + backtest harness
- [`docs/DATA_SCHEMA.md`](docs/DATA_SCHEMA.md) — tables including `research_feature_rows`, `research_market_labels`, `backtest_runs`, `backtest_trades`
- [`docs/RESEARCH_RULES.md`](docs/RESEARCH_RULES.md) — leakage + sealed test + feature + label + backtest rules

## Deferred (not in v0.9)

**Probability models**, **strategy optimization**, **order placement**, **portfolio**, **live execution** — v0.9 adds **orchestration** only; modeling and trading remain out of scope.
