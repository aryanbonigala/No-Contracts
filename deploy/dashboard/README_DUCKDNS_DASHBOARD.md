# DuckDNS + Caddy HTTPS for shadow dashboards

Public-safe dashboards must include **HTTPS** and **strong access controls**. DuckDNS only solves hostname → IP coupling; DNS is **not authentication**.

## What DuckDNS provides

| Provides | Does *not* provide |
|----------|---------------------|
| Free dynamic DNS hostname (`*.duckdns.org`) | Confidentiality unless you terminate TLS elsewhere |
| Simple HTTP updater API tokens | Credential safety if you accidentally publish tokens |
| | Protection against credential stuffing or XSS on your dashboards |

Assume any static HTML you publish remains safe at the content layer: **never** bake API keys, private keys, account balances, or live trading URLs into dashboards.

## 1. Create a DuckDNS subdomain

1. Sign in at [duckdns.org](https://www.duckdns.org).
2. Create a subdomain; note **token** and **domain slug** separately.
3. The slug you pass to the updater (`DUCKDNS_DOMAIN`) is the bare name (often `volt`, **not** `volt.duckdns.org` unless your token format requires both—follow DuckDNS’ field labels).

## 2. Provision secrets on the server

Create `/etc/kalshi-no-carry/duckdns.env`:

```bash
sudo install -d -m 0750 -o root -g root /etc/kalshi-no-carry
sudo touch /etc/kalshi-no-carry/duckdns.env
sudo chmod 0640 /etc/kalshi-no-carry/duckdns.env
sudo chown root:root /etc/kalshi-no-carry/duckdns.env
sudo nano /etc/kalshi-no-carry/duckdns.env
```

Example contents (**placeholders only**):

```dotenv
DUCKDNS_DOMAIN=your-subdomain
DUCKDNS_TOKEN=your-token-here
```

## 3. Install the updater script + timer

Copy `duckdns_update.sh` to `/usr/local/bin/kalshi-duckdns-update.sh`, then:

```bash
sudo chmod +x /usr/local/bin/kalshi-duckdns-update.sh
sudo cp deploy/dashboard/duckdns-update.service /etc/systemd/system/
sudo cp deploy/dashboard/duckdns-update.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now duckdns-update.timer
sudo systemctl start duckdns-update.service   # sanity check once
journalctl -u duckdns-update.service -n 20 --no-pager
```

Adjust `duckdns-update.service` `ExecStart=` if your install path differs.

## 4. Install Caddy (reverse proxy / static host)

Follow [Caddy install docs](https://caddyserver.com/docs/install); on Debian/Ubuntu:

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

## 5. Configure Basic Authentication

Never commit real credentials—only placeholders.

Generate a bcrypt hash offline:

```bash
caddy hash-password
```

Copy `deploy/dashboard/Caddyfile.example`, update:

- hostname block (`your-subdomain.duckdns.org`)
- `root *` pointing at wherever `reports/shadow_dashboard/latest` is copied/synced **without** leaking `.env`/keys (read-only subtree)
- `basic_auth` hash line from `caddy hash-password`

Drop the finalized file (sanitized paths) under `/etc/caddy/Caddyfile` or `/etc/caddy/sites-enabled/` per distro guidance.

Reload:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## 6. Point Caddy at generated dashboard artifacts

Runs (from project root):

```bash
PYTHONPATH=src python scripts/run_shadow_bucket_dashboard.py \
  --shadow-version v0.18_all_market_bucket_dashboard \
  --experiment-name all_market_bucket_dashboard_v0 \
  --output-dir reports/shadow_dashboard/latest \
  --overwrite
```

Copy/sync that directory to your droplet (`rsync`, object storage artifact pull, CI publish, …). Prefer a dedicated read-only POSIX ACL so Caddy cannot traverse parent repos.

## Firewall posture recommendations

Prefer **narrow exposure**:

- Minimal surface: inbound `22/tcp` (prefer key-only SSH), `80/tcp`, `443/tcp` only if exposing Caddy publicly.
- **Better**: Tailscale-only binding, Tailscale HTTPS, WireGuard bastion, or Cloudflare Tunnel / Zero Trust Access in front instead of-world-reachable dashboards.
- Rotate DuckDNS tokens if leaked; revoke Basic Auth credential pairs periodically.

## Security checklist

| Risk | Mitigation |
|------|------------|
| `.env`/private keys synced with HTML | Exclude via rsync `--exclude`; never symlink repo root |
| Weak Basic Auth passphrase | Password manager + bcrypt cost default |
| Public scrapers | Firewall + Tailscale/ZTNA preferable |
| Log leakage | Prefer `stdout`/`journald` on hardened host |
| Replay of stale dashboard | Version JSON `generated_at` + signed artifact pipeline if needed |
