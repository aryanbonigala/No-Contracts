# Kalshi NO Carry (v0.1 — project scaffold)

Production-oriented **research** codebase for testing a statistical thesis on Kalshi binary markets:

**Thesis (informal):** there may be edge in buying high-confidence **NO** contracts when the market-implied NO price is below the “true” NO probability after adjusting for fees, spread, ambiguity risk, and correlated event risk.

This repository is **v0.1** (`Kalshi_NO_Carry_v0.1_ProjectScaffold`): structure, configuration, logging, fee estimates, chronological train/validation/test splitting by event cluster, documentation, and CLI entrypoints — **not** a full data pipeline, API client, database schema, or backtest engine yet.

## Non-goals (this version)

- No live trading or order placement.
- No hardcoded API keys, private paths, or committed secrets.
- No full Kalshi API implementation or collectors.
- No Postgres schema migrations or persistence layer.

## Layout

- `src/kalshi_no_carry/` — application package
- `scripts/` — thin CLI wrappers for future workflows
- `tests/` — pytest suite
- `docs/` — architecture, data plan, and research rules

## Install

From the repo root (`kalshi-no-carry/`):

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Configuration

Copy `.env.example` to `.env` and set variables appropriate to your environment. The app reads settings via `kalshi_no_carry.config`; see `scripts/check_env.py` for a quick sanity check.

## Tests

```bash
pytest
```

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system overview and module boundaries
- [`docs/DATA_SCHEMA.md`](docs/DATA_SCHEMA.md) — planned persistence and entities (not implemented yet)
- [`docs/RESEARCH_RULES.md`](docs/RESEARCH_RULES.md) — rules to avoid leakage and keep research sound

## Deployment note (DigitalOcean VM)

The design assumes a standard Linux VM with Python 3.10+, optional Postgres (managed or co-located), and environment variables injected via your orchestration or shell — not baked into the image.
