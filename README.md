# Kalshi NO Carry (v0.4 — read-only collectors)

Production-oriented **research** codebase for testing a statistical thesis on Kalshi binary markets:

**Thesis (informal):** there may be edge in buying high-confidence **NO** contracts when the market-implied NO price is below the “true” NO probability after adjusting for fees, spread, ambiguity risk, and correlated event risk.

This repository is **v0.4** (`Kalshi_NO_Carry_v0.4_ReadOnlyCollectors`). It layers **read-only data collectors** on top of **v0.2** `KalshiClient` and **v0.3** SQLAlchemy persistence. Collectors persist **raw events**, **raw markets**, **append-only orderbook snapshots** (with derived executable quotes), and **API fetch logs**. They do **not** trade, place orders, or touch portfolio endpoints.

## Safety / scope

- **Read-only:** all ingestion uses public `GET` (and optional authenticated read) paths only.
- **Secrets:** never commit `.env`, keys, or passwords. Scripts print **summary JSON** from `to_public_dict()` only — no raw `DATABASE_URL`, no API keys.

## Layout

- `src/kalshi_no_carry/collectors/` — `events.py`, `markets.py`, `orderbooks.py`, `common.py`
- `src/kalshi_no_carry/db/` — schema + repositories
- `scripts/` — `collect_markets.py`, `collect_orderbooks.py`, `collect_snapshot.py`, `init_db.py`, …
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
- **Database:** **`DATABASE_URL` is required for collector scripts** (Postgres recommended on a VM; `scripts/check_env.py` shows a **redacted** preview).

Initialize schema once (optional; scripts can pass `--create-tables`):

```bash
python scripts/init_db.py
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

## Tests

Offline-only default suite (mocks + SQLite):

```bash
pytest
```

Optional Postgres smoke: set `RUN_DB_INTEGRATION_TESTS=1` and `DATABASE_URL` (unchanged from v0.3).

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — collector + persistence flow
- [`docs/DATA_SCHEMA.md`](docs/DATA_SCHEMA.md) — tables and how collectors fill them
- [`docs/RESEARCH_RULES.md`](docs/RESEARCH_RULES.md) — research guardrails

## Deferred (not in v0.4)

Event clustering, persisting train/validation/test splits, feature engineering, NO-carry backtester, order execution.
