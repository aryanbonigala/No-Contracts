# Architecture

High-level design of the **Kalshi NO carry** research stack: **v0.16** connectivity diagnostics, **v0.15** market lifecycle refresh, and the **v0.13 / v0.14** coverage and deployment additions described below.

This codebase supports **offline research** for a Kalshi thesis around **NO** contracts: explore potential mispricing after costs (fees, spread), ambiguity, and correlation — **without live trading**.


## Table of Contents

- [Purpose](#purpose)
- [Release highlights](#release-highlights)
- [Process boundaries](#process-boundaries)
- [Data and orchestration flows](#data-and-orchestration-flows)
- [Modules (current)](#modules-current)
- [Ingestion design](#ingestion-design)
- [What is explicitly deferred](#what-is-explicitly-deferred)


## Purpose

The system ingests read-only Kalshi market data, builds deterministic splits and features, audits coverage, and runs **read-only** backtests. Labels support **scoring and audits**, not pricing-feature inputs at decision time.

**v0.16** adds `kalshi_no_carry.diagnostics.kalshi_connectivity`: **read-only** JSON diagnostics (`run_kalshi_connectivity_diagnostics`) and `scripts/check_kalshi_connectivity.py` to validate configuration (redacted), **`GET /exchange/status`**, `KalshiClient` exchange and markets smoke, **optional** authenticated **`GET /events?limit=1`**, and **optional** batched **`GET /markets?tickers=`** / per-ticker **`GET /markets/{ticker}`** probes — **no** database requirement, **no** orders, **no** portfolio or fill endpoints.


## Release highlights

| Version | Focus |
|:--------|:------|
| **v0.5** | Deterministic **clustering and splits** on top of **v0.4** collectors. |
| **v0.6** | **`research_feature_rows`** materialization. |
| **v0.7** | Read-only **backtest harness** (`backtest_runs` / `backtest_trades`). |
| **v0.8** | **`research_market_labels`** from **`raw_markets`** (`research/outcomes.py`), optional merge into feature rows via **`--label-version`**, and **`research/dataset_audit.py`**. |
| **v0.9** | **`research/pipeline_runner.py`**: ordered orchestration (optional migrate or collectors, splits, labels, features with `label_version`, audit, optional backtest) with one safe JSON summary. |
| **v0.10** | **`research/reporting.py`**: Markdown + readiness via **`compute_research_readiness`** (`scripts/run_research_report.py`). |
| **v0.11** | **`collectors.common.normalize_collector_summary`** flattens each collector return (dataclass, dict, or Pydantic) into a **JSON-serializable** stage payload with a consistent **`success`** bit before merge into **`run_research_pipeline`** output. |
| **v0.12** | **`research/orderbook_audit.py`**: read-only **`raw_orderbook_snapshots`** inspection; **`run_no_carry_backtest_persisted`** uses **separate** SQLAlchemy transactional scopes and **replaces** existing rows for the same deterministic **`run_id`** in one transaction. |
| **v0.13** | **Status-aware market listing** (`collect_markets_multi_status`); **`collection_coverage`** aggregates stored-ingestion and **data_readiness_notes**. |
| **v0.14** | **DigitalOcean** scaffolding: `deploy/digitalocean/` systemd templates, **`collector.env.example`**, **`scripts/deployment_smoke_check.py`**, **`scripts/render_systemd_units.py`**, **`docs/DEPLOYMENT_DIGITALOCEAN.md`**; pipeline adds **`--collect-max-pages`**. |
| **v0.15** | **`collectors/market_lifecycle`**: refresh **upserts `raw_markets`** (batched `GET /markets?tickers=` with per-ticker fallback); **`collection_coverage`** adds orderbook↔label **lifecycle alignment** metrics. |
| **v0.16** | **`kalshi_connectivity`** diagnostics + **`check_kalshi_connectivity`** CLI (**read-only**, no DB). |

**Connectivity diagnostics (v0.16)**

```mermaid
flowchart LR
  CFG[Settings / env] --> RAW[Raw httpx GET /exchange/status]
  RAW --> KC[KalshiClient]
  KC --> ST[GET /exchange/status]
  ST --> M1[GET /markets limit=1]
  M1 --> AUTH[Optional GET /events authenticated]
  M1 --> BT[Optional tickers batch / single-ticker]
```

**Droplet deployment (v0.14)**

```mermaid
flowchart LR
  subgraph deploy [v0.14 Droplet deployment]
    VM[Linux VM / Droplet]
    ST[Systemd timers]
    COL[Collector oneshot service]
    REP[Report oneshot service]
    VM --> ST
    ST --> COL
    ST --> REP
  end
  subgraph clis [Public CLIs]
    RP[run_research_pipeline.py]
    RR[run_research_report.py]
  end
  DB[(PostgreSQL)]
  COL --> RP
  REP --> RR
  RP --> DB
  RR --> DB
```

- **Timers** trigger **generic** commands only (coverage-oriented collection; stored-data report **without** default **`--run-backtest`** in committed templates).
- **Secrets** load via systemd **`EnvironmentFile=`** (ignored paths on disk — not committed).
- **Rendered** unit files under **`build/systemd/`** are **local outputs** — keep them out of git.
- **Private** alpha modules or proprietary filters must **not** be wired into public unit templates; use local or private wrappers outside this repo if needed.

**v0.13** adds **status-aware market listing** (`collect_markets_multi_status`): Kalshi allows one `status` filter per request, so the collector **loops** statuses and merges tickers with duplicate-skipping diagnostics. **Orderbook collection** records per-book **liquidity / executable-quote** counters using **`orderbook_json_coverage_flags`**, supports **`orderbook_source_status`** (default **open**), and warns when sourcing books from non-open listings. **`research/collection_coverage.py`** aggregates **stored** market-status mixes, label-result histograms, snapshot executable ratios, and **data_readiness_notes** (embedded into **`audit_research_dataset`** and Markdown reports). **v0.12** orderbook price audit + **idempotent persisted backtests** remain in use below.


## Process boundaries

```mermaid
flowchart LR
  subgraph client [HTTP]
    KC[kalshi_client.KalshiClient]
  end
  subgraph ingest [v0.4]
    COL[collectors.events / markets / orderbooks]
  end
  subgraph persistence [v0.3+]
    REP[db.repositories]
    SCH[db.schema]
  end
  subgraph migrations [Alembic]
    ALB[Frozen revision DDL]
  end
  subgraph splits [v0.5]
    BC[research.build_splits]
    CL[event_clustering]
  end
  API[Kalshi Trade API v2]
  KC <--> API
  COL --> KC
  COL --> REP
  BC --> REP
  BC --> CL
  REP --> SCH
  DB[(Postgres / SQLite)]
  SCH --> DB
  ALB --> DB
  subgraph features [v0.6]
    FBUILD[research.feature_dataset]
    RFR[research_feature_rows]
  end
  subgraph backtest [v0.7]
    BTSEL[research.backtest_no_carry]
    BTR[backtest_runs]
    BTT[backtest_trades]
  end
  DB --> BC
  DB --> FBUILD
  FBUILD --> RFR
  DB --> RFR
  RFR --> BTSEL
  BTSEL --> BTR
  BTSEL --> BTT
  DB --> BTR
  DB --> BTT
```

**v0.5 research split flow:** `raw_events` + `raw_markets` → **event clustering** → `event_clusters` → **split assignment** → `strategy_splits`.

**v0.6 feature flow:** `raw_orderbook_snapshots` (with **`derive_executable_prices_from_orderbook`** at ingest) → join markets + clusters + `strategy_splits` → **`research.feature_dataset`** → **`research_feature_rows`**. **v0.12** optional **`audit_orderbook_price_extraction`** validates stored **`raw_json`** vs. columns and vs. feature rows before trusting readiness or backtests.

**v0.8 label flow:** **`raw_markets`** → **`research.outcomes`** → **`research_market_labels`** → *(optional)* merge at **`build_features.py`** into **`label_*`** on **`research_feature_rows`** → backtest **scoring** + **`dataset_audit`**.

**v0.7 backtest flow:** **`research_feature_rows`** → **`research.backtest_no_carry`** (select hypothetical NO entries, score vs **`label_*`** only) → **`backtest_runs`** + **`backtest_trades`** → *future* execution or models **not implemented here**.


## Data and orchestration flows

**v0.9+ pipeline (orchestration):** optional **`migrate` / `create_tables`** → optional **collectors** → **v0.15 optional `lifecycle_refresh`** (**`GET /markets/{ticker}`** → upsert **`raw_markets`**) → **`build_event_clusters_from_raw_data` + `assign_chronological_splits`** → **`build_market_outcome_labels_from_raw_markets`** → **`build_research_feature_rows_pipeline`** (with **`label_version`**) → **`audit_research_dataset`** → optional **`run_no_carry_backtest_persisted`**. Implemented in **`research.pipeline_runner`**; entry CLI **`scripts/run_research_pipeline.py`**. Default invocation uses **stored DB data only** (no network). **v0.11:** **`normalize_collector_summary`** (see **`collectors/common.py`**) is applied to **`collect_orderbooks`** so pipeline JSON never assumes a bespoke attribute layout on collector objects.

```mermaid
flowchart TD
  subgraph v09 [v0.9 pipeline runner]
    RPR[research.pipeline_runner.run_research_pipeline]
  end
  subgraph optional_net [optional explicit collectors]
    CM[collect_events / collect_markets]
    CO[collect_orderbooks_*]
    LR[collectors.market_lifecycle refresh]
  end
  RAW[(raw_* tables)]
  RPR --> CM
  RPR --> CO
  CM --> RAW
  CO --> RAW
  RPR --> LR
  LR --> RAW
  RPR --> BC[research.build_splits]
  BC --> RAW
  RPR --> LB[research.outcomes labels]
  LB --> RAW
  RPR --> FE[research.feature_dataset]
  FE --> RFR[research_feature_rows]
  RPR --> AUD[research.dataset_audit]
  RPR --> BT[research.backtest_no_carry]
```

**v0.10 reporting:** **`run_research_pipeline`** summary → **`research.reporting.build_research_audit_report`** / **`compute_research_readiness`** → `report.md` + `summary.json` (via **`scripts/run_research_report.py`** when not **`--dry-run`**). Readiness is **conservative** and **does not** assert tradable edge.

**`--dry-run` preview (report):** does **not** invoke **`run_research_pipeline`**; it calls **`audit_research_dataset`** (read-only) and reporting helpers on a **synthetic in-memory** pipeline summary so no report files or DB writes occur. Write-oriented CLI flags are **ignored** and listed in stdout JSON as **`ignored_write_flags`**.

```mermaid
flowchart LR
  subgraph normal [run_research_report non-dry-run]
    RPR[run_research_pipeline]
    SUM[pipeline summary dict]
    RPT[research.reporting]
    MD[report.md]
    JS[summary.json]
    RPR --> SUM
    SUM --> RPT
    RPT --> MD
    RPT --> JS
  end
  subgraph preview [run_research_report --dry-run]
    AUD[audit_research_dataset]
    SYN[synthetic preview summary]
    RPT2[research.reporting]
    STD[stdout only]
    AUD --> SYN
    SYN --> RPT2
    RPT2 --> STD
  end
```


## Modules (current)

| Path | Responsibility today |
|:-----|:---------------------|
| `kalshi_no_carry.diagnostics.kalshi_connectivity` | **v0.16** read-only connectivity JSON diagnostics (config sanity, exchange status, markets smoke, optional auth + ticker probes) |
| `kalshi_no_carry.kalshi_client` | Read-only Trade API v2 (`get_events`, `iter_events`, markets, orderbooks, status) |
| `kalshi_no_carry.collectors.*` | `collect_events`, `collect_markets`, `collect_orderbooks_*`, **`market_lifecycle` (ticker refresh)** |
| `kalshi_no_carry.database` | Engine + `create_all` / `drop_all` + `healthcheck` + URL redaction |
| `alembic/` + `scripts/db_migrate.py` | Versioned DDL via **explicit** Alembic revisions (`alembic upgrade head`); baseline `0001` is frozen `op.create_table` DDL — not `create_all` in migrations |
| `kalshi_no_carry.db.*` | ORM + idempotent upserts + snapshot insert + clustering/split **read helpers** |
| `kalshi_no_carry.research.event_clustering` | Deterministic cluster keys / ids from raw dict rows |
| `kalshi_no_carry.research.splits` | Pure chronological partition math (integer % and float fractions) |
| `kalshi_no_carry.research.build_splits` | `build_event_clusters_from_raw_data`, `assign_chronological_splits` |
| `kalshi_no_carry.research.features` | Pure deterministic primitives (mids, spreads, time-to-close, NO-carry scaffolding) |
| `kalshi_no_carry.research.feature_dataset` | `JoinedFeatureSource`, `build_feature_row_from_joined_record`, **`build_research_feature_rows_pipeline`**, validation |
| `kalshi_no_carry.research.outcomes` | Deterministic `extract_market_outcome_label*`, label builder from `raw_markets` |
| `kalshi_no_carry.research.dataset_audit` | `audit_research_dataset` coverage / join diagnostics |
| `kalshi_no_carry.research.collection_coverage` | **`summarize_collection_coverage`** stored-ingestion + **lifecycle alignment** metrics |
| `kalshi_no_carry.research.backtest_config` | Versioned `BacktestConfig` (Pydantic) for read-only runs |
| `kalshi_no_carry.research.pipeline_runner` | **`ResearchPipelineConfig`**, **`run_research_pipeline`**, **`recommend_next_action`** (v0.15 default **`pipeline_version`**) |
| `kalshi_no_carry.research.orderbook_audit` | v0.12 **`audit_orderbook_price_extraction`**: read-only orderbook JSON + executable price diagnostics |
| `kalshi_no_carry.research.backtest_no_carry` | Candidate selection, `score_no_trade`, summaries; **`run_no_carry_backtest_persisted`** |
| `scripts/build_splits.py` | CLI: materialize clusters + splits (requires `DATABASE_URL`) |
| `scripts/run_research_pipeline.py` | CLI: full pipeline, JSON summary (test excluded by default); **lifecycle refresh flags** |
| `scripts/refresh_market_lifecycle.py` | CLI: standalone **ticker** refresh JSON (**`DATABASE_URL`** required) |
| `scripts/run_research_report.py` | CLI: pipeline + Markdown/JSON audit report + readiness; **`--dry-run`** = audit-only preview, no files / no DB writes |
| `scripts/build_labels.py` | CLI: populate `research_market_labels` |
| `scripts/build_features.py` | CLI: build / persist `research_feature_rows` (test excluded by default) |
| `scripts/audit_orderbook_prices.py` | CLI: read-only orderbook price audit JSON |
| `scripts/run_backtest.py` | CLI: load feature rows, run baseline NO-carry rules, optional persist |
| `scripts/check_kalshi_connectivity.py` | **v0.16** CLI: safe JSON connectivity diagnostics (**no `DATABASE_URL`**; no DB writes) |
| `scripts/deployment_smoke_check.py` | v0.14 DB smoke JSON (no secrets; optional `--check-tables` / `--create-tables`) |
| `scripts/render_systemd_units.py` | v0.14 render `deploy/digitalocean/*.service` or `*.timer` → **`build/systemd/`** |
| `deploy/digitalocean/` | v0.14 **systemd** templates + **`collector.env.example`** (placeholders only) |


## Ingestion design

- **Synchronous** loops; optional `sleep_seconds` between orderbook fetches to be polite.
- **One `api_fetch_log` row per successful page** (events/markets) **or per orderbook attempt** (success or failure after rollback).
- **Orderbook rows** are always **inserted** (append-only snapshots); executable bests come from `derive_executable_prices_from_orderbook()`.
- **Split builder** is **read-only** with respect to Kalshi: it only reads the database.


## What is explicitly deferred

- **Live** order placement, portfolio, and execution against Kalshi
- Model training and calibrated **probability** models
- Automated **strategy selection** based on test-set peeking

See [`DATA_SCHEMA.md`](DATA_SCHEMA.md) and [`RESEARCH_RULES.md`](RESEARCH_RULES.md).
