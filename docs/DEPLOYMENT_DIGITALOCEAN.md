# DigitalOcean read-only collector deployment

Run **generic, read-only** Kalshi research collection and reporting on a Linux host (for example a **DigitalOcean Droplet**). This runbook does **not** cover live trading, order placement, or proprietary strategy logic.

> [!WARNING]
> Keep real credentials, database URLs, hostnames, and filesystem paths in **private** server configuration only—never in this public repository.

## Table of Contents

- [Purpose](#purpose)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Secrets and environment variables](#secrets-and-environment-variables)
- [Database options](#database-options)
- [Droplet setup](#droplet-setup)
- [Repository setup](#repository-setup)
- [Environment file setup](#environment-file-setup)
- [Database migration and smoke checks](#database-migration-and-smoke-checks)
- [Manual collector run](#manual-collector-run)
- [Optional manual lifecycle refresh (v0.15)](#optional-manual-lifecycle-refresh-v015)
- [Manual report run](#manual-report-run)
- [Kalshi connectivity diagnostics](#kalshi-connectivity-diagnostics)
- [systemd service and timer setup](#systemd-service-and-timer-setup)
- [Logs and monitoring](#logs-and-monitoring)
- [Updating the deployment](#updating-the-deployment)
- [Rollback](#rollback)
- [Security checklist](#security-checklist)
- [Alpha-safety checklist](#alpha-safety-checklist)
- [Troubleshooting](#troubleshooting)
- [Version history](#version-history)


## Purpose

Longitudinal datasets benefit from:

- Periodic **market** and **orderbook** snapshots while contracts are **open**
- Later refresh after markets **resolve**, using the same read-only collectors (including optional v0.15 ticker-level `raw_markets` refresh via `scripts/refresh_market_lifecycle.py` or `run_research_pipeline.py` flags—**generic** selection only in public templates)
- A host that runs on a **schedule** when your laptop is off

Scheduled jobs use **systemd timers** to call the same public CLIs you use locally: `scripts/run_research_pipeline.py` (optional network to Kalshi) and `scripts/run_research_report.py` (database only). Default templates do **not** place orders or execute trades.


## Architecture

```text
DigitalOcean Droplet
  → systemd timers (collector + report)
  → read-only Python CLIs (pipeline + report)
  → PostgreSQL (managed or local)
  → local/private reports/ and journal logs (not committed)
```

- **Timers** start **oneshot** services that load environment variables from a private `EnvironmentFile` (for example `deploy/.env` on the server).
- The **database** holds `raw_*` rows, research tables, and optional backtest metadata from this repo’s schema.
- **Artifacts** under `reports/` are local and private unless you sanitize them for sharing.
- **Cloud firewall** rules (SSH, Postgres exposure) live in the DigitalOcean control plane or **doctl**, not in this doc.


## Prerequisites

- A **Droplet** (or Linux VM) with SSH access
- **PostgreSQL** reachable from that host (see [Database options](#database-options))
- **Python 3.10+**, **git**, and (for managed Postgres over TLS) OS CA certificates
- **Kalshi** read credentials **only if** you enable authenticated read paths; some public market paths may work without a key depending on API policy
- Basic familiarity with **systemd** (`systemctl`, `journalctl`)

Placeholders such as `YOUR_NON_ROOT_USER`, `YOUR_DROPLET_IP`, and `/opt/kalshi-no-carry` appear below—replace them with real values on the server.


## Secrets and environment variables

- Commit **only** templates like `deploy/digitalocean/collector.env.example`.
- On the server, copy to a **private** path (for example `/opt/kalshi-no-carry/deploy/.env`) and run `chmod 600`.
- Store PEM and private keys **outside** the git tree; `chmod 600` key files.
- Point `EnvironmentFile=` in rendered systemd units at that private file.
- Never paste secrets into issues, chats, or public CI logs.

`DATABASE_URL` is required for collectors and reports. Other variables follow `kalshi_no_carry.config.Settings` (see the root `.env.example` for the full list).


## Database options

### Option A: DigitalOcean managed PostgreSQL (preferred)

Managed Postgres reduces operational overhead (backups, patching, HA options). Typical steps:

- Create a **private** database cluster in the same region as the Droplet.
- Use **private networking** or **trusted sources** so the database is not needlessly exposed to the public internet.
- Use `sslmode=require` (or stricter) in `DATABASE_URL` when TLS is required on the connection path.
- Run `python scripts/db_migrate.py` (Alembic) for versioned schema upgrades on databases you care about.

### Option B: PostgreSQL on the Droplet

Works for **low-cost** or **experimental** setups. You own backups, upgrades, and disk sizing. Lock down listen addresses and firewalls appropriately.


## Droplet setup

Sketch with placeholders only:

```bash
ssh YOUR_NON_ROOT_USER@YOUR_DROPLET_IP

sudo apt update
sudo apt install -y git python3 python3-venv python3-pip postgresql-client
```


## Repository setup

```bash
git clone git@github.com:aryanbonigala/No-Contracts.git /opt/kalshi-no-carry
cd /opt/kalshi-no-carry
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```


## Environment file setup

```bash
sudo mkdir -p /opt/kalshi-no-carry/deploy
sudo nano /opt/kalshi-no-carry/deploy/.env
sudo chmod 600 /opt/kalshi-no-carry/deploy/.env
```

Populate the private file using `deploy/digitalocean/collector.env.example` as a non-secret reference.


## Database migration and smoke checks

After `DATABASE_URL` is set (or loaded from your private env file for interactive commands):

Prefer **Alembic** for production-like databases:

```bash
source .venv/bin/activate
python scripts/db_migrate.py
```

Use `scripts/deployment_smoke_check.py` for a **safe JSON** summary (no raw URL, no passwords):

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


## Manual collector run

Read-only ingest example (requires network to Kalshi where applicable):

```bash
source .venv/bin/activate
python scripts/run_research_pipeline.py \
  --collect-markets \
  --collect-status-set active_and_resolved \
  --collect-orderbooks \
  --limit 200
```


### Optional manual lifecycle refresh (v0.15)

After you have **stored orderbook snapshots**, re-fetch the same tickers so `raw_markets` picks up later **settlement** and **result** fields before rebuilding labels or features. Traffic is read-only `GET /markets`—not order placement.

Prefer running this **manually** or from a **private** wrapper until cost and latency are acceptable; committed **systemd** timers stay on **generic** ingest and report commands.

```bash
source .venv/bin/activate
python scripts/refresh_market_lifecycle.py --limit 500
# Or use pipeline flags:
python scripts/run_research_pipeline.py --refresh-lifecycle-markets --refresh-limit 500
```


## Manual report run

Stored-data report (no Kalshi network; database only):

```bash
source .venv/bin/activate
python scripts/run_research_report.py \
  --report-name droplet-manual-smoke \
  --overwrite-splits \
  --delete-existing-labels \
  --delete-existing-features
```

The default **scheduled** report template uses a generic `--report-name scheduled-latest` and does **not** pass `--run-backtest`. Add backtests only with explicit, reviewed unit files—not in the committed default.


## Kalshi connectivity diagnostics

Run read-only JSON checks **before** installing timers when ingest depends on Kalshi HTTP. This command does **not** require `DATABASE_URL`, does **not** mutate Postgres, and does **not** call order or portfolio endpoints.

```bash
source .venv/bin/activate
python scripts/check_kalshi_connectivity.py
python scripts/check_kalshi_connectivity.py --ticker YOUR_PLACEHOLDER_TICKER
```

Use placeholders in documentation; keep real tickers and credentials off-repo.


## systemd service and timer setup

Templates live under `deploy/digitalocean/` with placeholders: `__USER__`, `__WORKING_DIRECTORY__`, `__ENVIRONMENT_FILE__`, `__PYTHON_PATH__`.

Render them locally or on the Droplet into `build/systemd/` (gitignored):

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
|:-----|:------------|:------------------|:--------|
| `kalshi-no-carry-collector.timer` | 5min | 15min | Periodic read-only ingest |
| `kalshi-no-carry-report.timer` | 10min | 60min | Less frequent stored-data report |

Tune intervals for **capacity**, **API courtesy**, and **operations**—not as a stand-in for proprietary scheduling logic (keep that outside this public repo).


## Logs and monitoring

```bash
systemctl list-timers | grep kalshi
journalctl -u kalshi-no-carry-collector.service -n 100 --no-pager
journalctl -u kalshi-no-carry-report.service -n 100 --no-pager
```

Prefer external **log aggregation** for retention and alerts. Do not commit raw logs.


## Updating the deployment

- Run `git pull` in the working tree.
- Refresh the virtual environment when dependencies change: `python -m pip install -e ".[dev]"`.
- Run `python scripts/db_migrate.py` when Alembic revisions ship.
- Re-render systemd units when templates or paths change, then `daemon-reload` and restart timers.


## Rollback

- Check out the previous **git** revision.
- Re-run `db_migrate.py` only with a **tested** downgrade strategy (Alembic downgrade is project-specific—coordinate with `alembic/` history).
- Restore the **database** from backups if schema or data migration fails—that is infrastructure responsibility, not automated here.


## Security checklist

- [ ] SSH keys and `sudo` access match your organization baseline.
- [ ] Managed DB uses private network or firewall rules that restrict clients.
- [ ] `deploy/.env` is mode `600` and outside git.
- [ ] Private keys are mode `600` and not under the repo tree.
- [ ] No secrets in unit files—only `EnvironmentFile=` pointing at private paths.
- [ ] Kalshi credentials are read-only; no trading API usage in this stack.


## Alpha-safety checklist

- [ ] Public **systemd** units use **generic** CLI flags only (coverage-oriented collection, not proprietary selection).
- [ ] No proprietary **thresholds**, **signals**, or **category-edge** filters in committed units.
- [ ] **Reports** may contain sensitive operational context—treat them as private.
- [ ] Private strategy modules, if any, stay **out of this repo** and are not wired into default timers.


## Troubleshooting

- **Kalshi `ConnectError` / timeouts from collectors:** Run `python scripts/check_kalshi_connectivity.py` from the activated venv to classify DNS/TLS/base-url/auth issues (read-only JSON).
- **`deployment_smoke_check` reports `database_error`:** Verify `DATABASE_URL`, TLS options, firewall rules, and database uptime. Stderr from drivers is not echoed by design; debug with `postgresql-client` tools using your local secret file.
- **Timers never fire:** Inspect `systemctl status` on `.timer` units, server clock, and whether `.service` units are enabled.
- **Collector HTTP errors:** Transient Kalshi outages; check timeouts in settings; consider lowering `--limit` or increasing timer spacing for courtesy.
- **Report writes fail:** Verify `reports/` permissions for the service user and disk space.


## Version history

- **v0.16:** Documents **`scripts/check_kalshi_connectivity.py`** as an optional **pre-timer** Kalshi HTTP connectivity check (**no** `DATABASE_URL`; read-only JSON).
- **v0.14:** Initial `docs/DEPLOYMENT_DIGITALOCEAN.md`, `deploy/digitalocean/` templates, `scripts/deployment_smoke_check.py`, `scripts/render_systemd_units.py`; emphasizes read-only scope and placeholder-only documentation.
