# DigitalOcean Read-Only Collector Deployment

This runbook describes **optional** infrastructure for running **generic, read-only** research collection and reporting on a Linux host (for example a **DigitalOcean Droplet**). It does **not** cover live trading, order placement, or proprietary strategy logic.

All **real** credentials, database URLs, hostnames, and file paths must stay in **private** configuration on the server — never in this public repository.


## Purpose

Longitudinal research datasets benefit from:

- Periodic **market** and **orderbook** snapshots while instruments are **open**
- Later **refresh** after markets **resolve**, using the same read-only collectors (including **optional v0.15 ticker-level `raw_markets` refresh** via **`scripts/refresh_market_lifecycle.py`** or **`run_research_pipeline.py`** flags — **generic** selection only in public templates)
- A host that runs on a **schedule** while a laptop is offline

This deployment uses **systemd timers** to invoke the same **public** CLI entrypoints used locally: **`scripts/run_research_pipeline.py`** (optional network to Kalshi) and **`scripts/run_research_report.py`** (stored database only). **Nothing** in the default templates places orders or executes trades.


## Architecture

At a high level:

```text
DigitalOcean Droplet
  -> systemd timers (collector + report)
  -> read-only Python CLIs (pipeline + report)
  -> PostgreSQL (managed or local)
  -> local/private reports/ and journal logs (not committed)
```

- **Timers** trigger **oneshot services** that load environment variables from a **private** `EnvironmentFile` (for example `deploy/.env` on the server).
- The **database** stores `raw_*` rows, research tables, and optional backtest metadata already defined in this repo’s schema.
- **Reports** under `reports/` are **local artifacts**. Treat them as **private** unless explicitly sanitized for sharing.
- **Cloud Firewall** rules (who may reach Postgres or SSH) are configured in the **DigitalOcean control plane** or **doctl** — not hardcoded here.

## Prerequisites

- An existing **Droplet** (or other Linux VM) with SSH access
- A **PostgreSQL** database reachable from that Droplet (see **Database Options**)
- **Python 3.10+**, **git**, and (for managed Postgres over TLS) CA certificates as provided by the OS
- A **Kalshi** read credential **only if** you enable authenticated read paths; public market data may work with no key depending on endpoint policy
- Familiarity with **systemd** (`systemctl`, `journalctl`)

This document uses **placeholders** such as `YOUR_NON_ROOT_USER`, `YOUR_DROPLET_IP`, and `/opt/kalshi-no-carry` — replace them with your real values on the server.

## Secrets and Environment Variables

- Commit **only** templates like **`deploy/digitalocean/collector.env.example`**
- On the server, copy to a **private** path (for example `/opt/kalshi-no-carry/deploy/.env`) and **`chmod 600`**
- Store **PEM / private keys** outside the git tree; **`chmod 600`** key files
- Point **`EnvironmentFile=`** in rendered systemd units at that private file
- Never paste secrets into issues, chats, or public CI logs

`DATABASE_URL` must be set for collectors and reports. Other variables follow **`kalshi_no_carry.config.Settings`** (see root **`.env.example`** for the full list).

## Database Options

### Option A: DigitalOcean Managed PostgreSQL (preferred)

**Managed Postgres** reduces operational burden (backups, patching, HA options). Typical pattern:

- Create a **private** database cluster in the same region as the Droplet
- Use **private networking** or **trusted sources** so the DB is not exposed to the public internet without need
- Use **`sslmode=require`** (or stricter) in `DATABASE_URL` when connecting over paths that require TLS
- Run **`python scripts/db_migrate.py`** (Alembic) for versioned schema upgrades on databases you care about

### Option B: PostgreSQL Installed on the Droplet

Acceptable for **low-cost** or **experimental** setups. You operate backups, upgrades, and disk sizing yourself. Ensure listen addresses and firewalls restrict access appropriately.

## Droplet Setup

Sketch (placeholders only):

```bash
ssh YOUR_NON_ROOT_USER@YOUR_DROPLET_IP

sudo apt update
sudo apt install -y git python3 python3-venv python3-pip postgresql-client
```

## Repo Setup

```bash
git clone git@github.com:aryanbonigala/No-Contracts.git /opt/kalshi-no-carry
cd /opt/kalshi-no-carry
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Environment File Setup

```bash
sudo mkdir -p /opt/kalshi-no-carry/deploy
sudo nano /opt/kalshi-no-carry/deploy/.env
sudo chmod 600 /opt/kalshi-no-carry/deploy/.env
```

Populate using **`deploy/digitalocean/collector.env.example`** as a **non-secret** reference; use real values only in the private copy.

## Database Migration and Smoke Checks

After **`DATABASE_URL`** is set in the environment (or loaded from your private env file when you run commands interactively):

- Prefer **Alembic** for production-like databases:

```bash
source .venv/bin/activate
python scripts/db_migrate.py
```

- Use **`scripts/deployment_smoke_check.py`** for a **safe JSON** summary (no raw URL, no passwords):

```bash
source .venv/bin/activate
python scripts/deployment_smoke_check.py --check-tables
```

Optional bootstrap (empty disposable databases only):

```bash
python scripts/deployment_smoke_check.py --create-tables --check-tables
```

Optional write probe for report directories:

```bash
python scripts/deployment_smoke_check.py --reports-dir /opt/kalshi-no-carry/reports
```

## Manual Collector Run

Read-only **ingest** example (requires network to Kalshi where applicable):

```bash
source .venv/bin/activate
python scripts/run_research_pipeline.py \
  --collect-markets \
  --collect-status-set active_and_resolved \
  --collect-orderbooks \
  --limit 200
```

### Optional manual lifecycle refresh (v0.15)

After you have **stored orderbook snapshots**, you can **re-fetch the same tickers** so `raw_markets` picks up later **settlement / result** fields before rebuilding labels/features. This is **read-only `GET /markets/{ticker}`** traffic — **not** order placement.

Prefer running this **manually** or via a **private** wrapper until you have reviewed cost/latency; the committed **systemd timers** stay on **generic** ingest/report commands only.

```bash
source .venv/bin/activate
python scripts/refresh_market_lifecycle.py --limit 500
# or integrate flags on the pipeline:
python scripts/run_research_pipeline.py --refresh-lifecycle-markets --refresh-limit 500
```

## Manual Report Run

Stored-data **report** example (no Kalshi network; uses database only):

```bash
source .venv/bin/activate
python scripts/run_research_report.py \
  --report-name droplet-manual-smoke \
  --overwrite-splits \
  --delete-existing-labels \
  --delete-existing-features
```

The **default scheduled** report template uses a generic `--report-name scheduled-latest` and **does not** pass **`--run-backtest`**. Add backtests only with explicit, reviewed unit files — not in the committed default.

## systemd Service and Timer Setup

Templates live under **`deploy/digitalocean/`** with placeholders: `__USER__`, `__WORKING_DIRECTORY__`, `__ENVIRONMENT_FILE__`, `__PYTHON_PATH__`.

Render them **locally or on the Droplet** into **`build/systemd/`** (which is **gitignored**):

```bash
python scripts/render_systemd_units.py \
  --template-dir deploy/digitalocean \
  --output-dir build/systemd \
  --user kalshi \
  --working-directory /opt/kalshi-no-carry \
  --environment-file /opt/kalshi-no-carry/deploy/.env \
  --python-path /opt/kalshi-no-carry/.venv/bin/python
```

Install units (paths may vary by distribution):

```bash
sudo cp build/systemd/*.service build/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kalshi-no-carry-collector.timer
sudo systemctl enable --now kalshi-no-carry-report.timer
```

**Timers (operational defaults, not strategy timing):**

| Unit | `OnBootSec` | `OnUnitActiveSec` | Purpose |
|:-----|:-------------|:------------------|:--------|
| `kalshi-no-carry-collector.timer` | 5min | 15min | Periodic read-only ingest |
| `kalshi-no-carry-report.timer` | 10min | 60min | Less frequent stored-data report |

Adjust intervals for **capacity**, **API courtesy**, and **ops** — not as a substitute for proprietary scheduling logic (which belongs outside this public repo).

## Logs and Monitoring

```bash
systemctl list-timers | grep kalshi
journalctl -u kalshi-no-carry-collector.service -n 100 --no-pager
journalctl -u kalshi-no-carry-report.service -n 100 --no-pager
```

Prefer **log aggregation** (external to this repo) for retention and alerts. Do not commit raw logs.

## Updating the Deployment

- `git pull` in the working tree
- Refresh the virtualenv if dependencies changed: `python -m pip install -e ".[dev]"`
- Run **`python scripts/db_migrate.py`** when Alembic revisions ship
- Re-render systemd units if templates or paths change, then `daemon-reload` and restart timers

## Rollback

- Check out the previous **git** revision
- Re-run **`db_migrate.py`** only with a **tested** downgrade strategy (Alembic downgrade is project-specific — coordinate with `alembic/` history)
- Restore **database** from backups if schema or data migration fails — infrastructure responsibility, not automated here

## Security Checklist

- [ ] SSH keys and `sudo` access follow your org baseline
- [ ] **Managed DB** private network or firewall restricts clients
- [ ] **`deploy/.env`** is `600` and outside git
- [ ] Private keys are `600` and not under the repo tree
- [ ] **No secrets** in unit files — only `EnvironmentFile=` to private paths
- [ ] **Kalshi** credentials are read-only; no trading API usage in this stack

## Alpha-Safety Checklist

- [ ] Public **systemd** units reference **generic** CLI flags only (coverage-oriented collection, not proprietary selection)
- [ ] No proprietary **thresholds**, **signals**, or **category-edge** filters in committed units
- [ ] **Reports** may contain sensitive operational context — treat as private
- [ ] Private strategy modules, if any, stay **out of this repo** and are not wired into default timers

## Troubleshooting

- **`deployment_smoke_check` fails `database_error`:** verify `DATABASE_URL`, TLS options, firewall rules, and database uptime — stderr from drivers is **not** echoed by design; inspect DB connectivity with `postgresql-client` tools using your local secret file
- **Timers never fire:** check `systemctl status` on `.timer` units, server clock, and whether `.service` units are **enabled**
- **Collector HTTP errors:** transient Kalshi outages; ensure **timeouts** in settings; consider lowering `--limit` or increasing timer spacing for courtesy
- **Report writes fail:** verify `reports/` permissions for the service user and disk space

## Version History

- **v0.14:** Initial **`docs/DEPLOYMENT_DIGITALOCEAN.md`**, `deploy/digitalocean/` templates, `scripts/deployment_smoke_check.py`, `scripts/render_systemd_units.py`; emphasizes read-only scope and placeholder-only docs.
