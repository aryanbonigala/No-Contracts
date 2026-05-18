#!/usr/bin/env bash
# Update DuckDNS IPv4 pointer. Tokens never hit stdout intentionally.
#
# Env:
#   DUCKDNS_DOMAIN — bare subdomain token DuckDNS assigns (often `myvolt`, comma-separated OK)
#   DUCKDNS_TOKEN    — DuckDNS dashboard token string
#
set -euo pipefail

: "${DUCKDNS_DOMAIN:?DUCKDNS_DOMAIN is required (bare subdomain slug, see DuckDNS FAQ)}"
: "${DUCKDNS_TOKEN:?DUCKDNS_TOKEN is required}"

TEMP_ERR="$(mktemp)"
cleanup() { rm -f "$TEMP_ERR" || true; }
trap cleanup EXIT

if ! RESP="$(curl --silent --show-error \
  --connect-timeout 10 --max-time 30 \
  "https://www.duckdns.org/update?domains=${DUCKDNS_DOMAIN}&token=${DUCKDNS_TOKEN}&ip=" \
  2>"$TEMP_ERR")"; then
  echo "duckdns: curl transport failure" >&2
  exit 1
fi

if [[ -s "$TEMP_ERR" ]]; then
  cat "$TEMP_ERR" >&2
  exit 1
fi

RESP="${RESP//$'\r'/}"
RESP="${RESP//$'\n'/}"

# DuckDNS echoes short status codes (often `good`/`nochg`); never includes the secret token on success paths.
case "$RESP" in
  good|OK|nochg) printf '%s\n' "$RESP" ;;
  *) echo "duckdns: unexpected reply: ${RESP}" >&2 ; exit 1 ;;
esac
