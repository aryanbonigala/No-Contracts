# Kalshi NO Carry (v0.12 — orderbook price extraction audit + backtest session fix; read-only)

Production-oriented **research** codebase for testing a statistical thesis on Kalshi binary markets:

**Thesis (informal):** there may be edge in buying high-confidence **NO** contracts when the market-implied NO price is below the "true" NO probability after adjusting for fees, spread, ambiguity risk, and correlated event risk.

This repository is **v0.12.0** (`Kalshi_NO_Carry_v0.12_OrderbookPriceExtractionAndBacktestSessionFix`). **v0.12** fixes **persisted backtest** SQLAlchemy session handling (no nested `begin()` after reads), adds **`research/orderbook_audit.py`** + **`scripts/audit_orderbook_prices.py`** for read-only diagnosis of stored orderbooks, and corrects **best-bid** selection in **`derive_executable_prices_from_orderbook`** (Kalshi lists bids **ascending**; the **best** bid is the **last** level — previously the code used the first/worst level). **v0.11** collector summary normalization, **v0.10** reporting, **v0.9** pipeline, **v0.8** labels, **v0.7** backtests remain below.

## Safety / scope

- **Read-only vs Kalshi:** all ingestion uses public `GET` (and optional authenticated read) paths only; **collectors never place orders** — they only persist read-only market and orderbook snapshots into your database.
- **Backtests:** consume **frozen** `research_feature_rows` only; they **never** submit orders or move balances.
- **Labels:** normalized outcomes live in **`research_market_labels`** (and optionally on feature rows via **`--label-version`**) for **scoring and coverage only** — not for pricing or entry-feature computation.
- **Secrets:** never commit `.env`, keys, or passwords. Scripts print **summary JSON** only — no raw `DATABASE_URL`, no API keys.

## Layout

- `src/kalshi_no_carry/collectors/` — `events.py`, `markets.py`, `orderbooks.py`, `common.py`
- `src/kalshi_no_carry/db/` — schema + repositories
- `src/kalshi_no_carry/research/` — clustering, splits, **`features.py`**, **`feature_dataset.py`**, **`orderbook_audit.py`**, **`outcomes.py`**, **`dataset_audit.py`**, **`pipeline_runner.py`**, **`reporting.py`**, **`backtest_config.py`**, **`backtest_no_carry.py`**, `build_splits.py`
- `scripts/` — collectors, `build_splits.py`, **`build_labels.py`**, **`build_features.py`**, **`audit_research_dataset.py`**, **`audit_orderbook_prices.py`**, **`run_research_pipeline.py`**, **`run_research_report.py`**, **`run_backtest.py`**, `init_db.py`, `db_migrate.py`, `db_revision.py`, …
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
- **Database:** **`DATABASE_URL` is required** for collector scripts, `build_splits.py`, **`build_labels.py`**, **`build_features.py`**, **`audit_research_dataset.py`**, **`run_research_pipeline.py`**, **`run_research_report.py`**, and **`run_backtest.py`** (Postgres recommended on a VM; `scripts/check_env.py` shows a **redacted** preview). **Offline unit tests** use SQLite in-memory and do not need `DATABASE_URL`.

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

## Local public-data smoke (optional; network + Kalshi)

On a **disposable** SQLite file (schema already migrated or use **`--migrate --create-tables`** on the pipeline as needed):

```bash
export DATABASE_URL="sqlite+pysqlite:///./research.db"
python scripts/run_research_pipeline.py --collect-markets --collect-orderbooks --limit 25
```

- Collectors issue **read-only HTTP** to Kalshi public market endpoints and upsert **`raw_*`** rows only.
- **Repeat runs:** if **`strategy_splits`** already exists for your default **`--split-version`**, **`build_splits`** fails with an explicit message. Use **`--overwrite-splits`** to rebuild splits for that version, and consider **`--delete-existing-labels`** / **`--delete-existing-features`** when re-materializing downstream artifacts for the same label/feature versions. **Nothing** is auto-deleted unless you pass those flags.
- Normal **pytest** does not call Kalshi; use **mocks** and SQLite only.

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

## Orderbook price extraction audit (v0.12; requires `DATABASE_URL`, no Kalshi)

**Read-only:** scans **`raw_orderbook_snapshots`**, classifies JSON shape, recomputes executable prices with the same **`derive_executable_prices_from_orderbook`** helper used at ingest, and optionally joins **`research_feature_rows`** to flag extraction gaps.

```bash
python scripts/audit_orderbook_prices.py
python scripts/audit_orderbook_prices.py --limit 50 --show-samples
python scripts/audit_orderbook_prices.py --split-version v0.5_chronological_60_20_20 --feature-version v0.6_orderbook_snapshot_features
python scripts/audit_orderbook_prices.py --output-json reports/orderbook-price-audit.json
```

**How to read results:**

- **`snapshots_empty_both_sides`** high → books had no YES/NO bid levels (illiquid or empty snapshot); missing **`no_ask`** on feature rows is expected — **do not fabricate** prices.
- **`snapshots_unrecognized_shape`** high → payload is not `orderbook_fp` / `yes_dollars` / `no_dollars` as documented; inspect **`shape_samples`** (fingerprints only, not full JSON).
- **`feature_raw_executable_no_ask_feature_missing_no_ask`** > 0 → raw book supports an implied **NO ask** but the linked feature row lacks **`no_ask_cents`** (rebuild features after fixing extraction, or investigate join/version mismatch).

**Backtest note:** With **zero scorable** rows (missing labels or missing executable quotes), **`run_research_report.py --run-backtest`** / **`run_research_pipeline.py --run-backtest`** should still **complete**: **`scored_trades`** may be **0** with warnings — not a session crash.

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

## Research audit report (v0.10; requires `DATABASE_URL`)

After labels and features are built, generate a **Markdown + JSON** bundle for humans and tools:

```bash
python scripts/run_research_report.py
python scripts/run_research_report.py --dry-run
python scripts/run_research_report.py --run-backtest
python scripts/run_research_report.py --migrate --run-backtest
python scripts/run_research_report.py --output-dir reports/local-smoke --run-backtest
python scripts/run_research_report.py --include-test --run-backtest
```

- **Outputs (non–`--dry-run`):** `reports/<timestamp>/` or `reports/<--report-name>/` containing **`summary.json`** (pretty-printed, sorted keys) and **`report.md`**. Stdout prints **safe paths** and **readiness_level** only — no secrets, no raw `DATABASE_URL`.
- **`--dry-run` stdout:** JSON includes **`dry_run`**, **`files_written`:** false, **`database_writes_performed`:** false, **`ignored_write_flags`**, and **`warnings`** (no artifact directory created).
- **Default:** stored-data pipeline only (**no Kalshi** collectors in this script). **Test split excluded** unless **`--include-test`**.
- **`--dry-run`:** **read-only preview** — does **not** write `summary.json` / `report.md`, does **not** run migrations or `create_all`, and does **not** mutate research tables (no splits, labels, features, or persisted backtest rows). It runs **`audit_research_dataset`** only (unless **`--skip-audit`**) against the current DB and prints readiness + Markdown-like content to stdout. **Write-oriented flags** (`--migrate`, `--create-tables`, `--overwrite-splits`, `--delete-existing-labels`, `--delete-existing-features`, pipeline stages that would materialize or persist backtests) are **ignored** with warnings; stdout JSON lists them under **`ignored_write_flags`**.
- **Git / sharing:** do **not** commit reports if they embed sensitive local paths, operational notes, or anything that could expose credentials. Treat reports as **local artifacts** unless redacted.
- **Readiness:** the `readiness` object in **`summary.json`** (from **`compute_research_readiness`**) uses **fixed conservative thresholds** (see `research/reporting.py`); it does **not** prove edge. **Live trading** is never recommended.

## Run read-only backtest (requires `DATABASE_URL`, no Kalshi)

**Default:** **train + validation** feature rows only — **test is excluded** unless **`--include-test`**. **Hypothetical PnL** is computed **only when** `label_market_result` (and friends) are present on feature rows; missing labels yield **unscored** trades — the harness **does not** invent outcomes.

```bash
python scripts/run_backtest.py --max-no-ask-cents 95 --dry-run
python scripts/run_backtest.py --max-no-ask-cents 90 --min-seconds-to-close 3600
python scripts/run_backtest.py --include-test --backtest-version v0.7_no_carry_baseline_FINAL_TEST_ONCE
```

Use **`--dry-run`** to compute summaries without writing **`backtest_runs`** / **`backtest_trades`**.

**Deterministic `run_id`:** persisted runs use a stable UUID derived from the full **`BacktestConfig`** (see **`compute_backtest_run_id`**). Re-running **`run_backtest.py`** or the pipeline/report with the **same** parameters **replaces** the prior row for that id in one transaction (existing **`backtest_trades`** for that run are removed first) instead of inserting duplicates. Summary JSON includes **`overwritten_existing_run`**, **`prior_run_deleted`**, and **`prior_trades_deleted`** when a prior persisted row existed. Opt out with **`--no-overwrite-existing-run`** (you will get a duplicate-key error if the row already exists).

**Deprecated:** **`--delete-existing-run`** is ignored (overwrite-on-persist is the default).

Strategies include `no_carry_price_threshold_v0` (default) and `no_carry_required_prob_placeholder_v0` (probability buckets only, no entries). This is **not** live trading.

## Tests

Offline-only default suite (mocks + SQLite):

```bash
pytest
```

Optional Postgres smoke: set `RUN_DB_INTEGRATION_TESTS=1` and `DATABASE_URL`.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — ingestion + pipeline + **reporting** + splits + features + labels + audit + backtest harness
- [`docs/DATA_SCHEMA.md`](docs/DATA_SCHEMA.md) — tables including `research_feature_rows`, `research_market_labels`, `backtest_runs`, `backtest_trades`
- [`docs/RESEARCH_RULES.md`](docs/RESEARCH_RULES.md) — leakage + sealed test + feature + label + backtest rules

## Deferred (not in v0.12)

**Probability models**, **strategy optimization**, **order placement**, **portfolio**, **live execution** — v0.12 focuses on **orderbook diagnostics**, **correct executable derivation**, and **safe backtest persistence**; modeling and trading remain out of scope.
