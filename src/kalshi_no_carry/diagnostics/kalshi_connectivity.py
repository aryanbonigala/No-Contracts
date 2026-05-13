"""
Read-only Kalshi Trade API v2 connectivity diagnostics (no orders, no portfolio).

Used to debug ConnectError, timeouts, base URL mistakes, and authenticated read wiring.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from kalshi_no_carry.config import Settings, get_settings
from kalshi_no_carry.kalshi_client import KalshiAuthError, KalshiClient

DIAGNOSTIC_VERSION = "0.16.0"

_REMEDIATION: dict[str, str] = {
    "connect_error": (
        "Network path to Kalshi failed before TLS/HTTP completed (firewall, DNS, offline VPN, "
        "or wrong host). Verify outbound HTTPS from this host and DNS resolution; run "
        "`python scripts/check_kalshi_connectivity.py` after fixing routing."
    ),
    "connect_timeout": (
        "Outbound TCP/TLS to Kalshi timed out. Increase KALSHI_REQUEST_TIMEOUT_SECONDS if the "
        "link is very slow, or check corporate proxies and firewall egress rules."
    ),
    "read_timeout": (
        "Kalshi accepted the connection but the response body did not arrive in time. Check "
        "latency, packet loss, or raise KALSHI_REQUEST_TIMEOUT_SECONDS for slow links."
    ),
    "timeout_generic": (
        "A request-level timeout fired. Confirm host reachability and consider adjusting "
        "KALSHI_REQUEST_TIMEOUT_SECONDS for diagnostics only."
    ),
    "http_auth": (
        "HTTP 401/403 usually means missing/wrong KALSHI_API_KEY_ID, wrong private key, "
        "clock skew, or demo vs prod host mismatch (KALSHI_ENV / base URLs)."
    ),
    "http_not_found": (
        "HTTP 404 often means the path is wrong relative to the configured base URL. "
        "KALSHI_BASE_URL must include `/trade-api/v2` (no trailing slash required)."
    ),
    "http_other": (
        "Kalshi returned an unexpected HTTP error. Confirm maintenance windows and that "
        "the demo vs prod host matches your credentials."
    ),
    "request_error": (
        "httpx reported a transport/request error that was not a timeout or connection "
        "refusal. Inspect local TLS trust store, HTTP proxies, and URL composition."
    ),
    "unexpected": (
        "An unexpected exception occurred during diagnostics. Re-run with the same CLI and "
        "inspect stderr; consider upgrading dependencies if parsing errors mention JSON."
    ),
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redacted_base(settings: Settings) -> dict[str, Any]:
    url = settings.resolved_kalshi_base_url()
    parsed = urlparse(url)
    return {
        "scheme": parsed.scheme or None,
        "host": parsed.hostname,
        "base_url_includes_trade_api_v2": "/trade-api/v2" in url,
    }


def _config_block(settings: Settings) -> dict[str, Any]:
    return {
        "settings_loaded": True,
        "kalshi_no_carry_env": settings.kalshi_no_carry_env,
        "kalshi_env": settings.kalshi_env,
        "kalshi_request_timeout_seconds": settings.kalshi_request_timeout_seconds,
        "resolved_base_url_redacted": _redacted_base(settings),
        "kalshi_api_key_id_configured": settings.kalshi_api_key_id is not None
        and str(settings.kalshi_api_key_id).strip() != "",
        "kalshi_private_key_path_configured": settings.kalshi_private_key_path is not None,
        "database_url_configured": settings.database_url is not None,
    }


def classify_request_exception(exc: BaseException) -> tuple[str, str]:
    """
    Map an exception to a stable class label and remediation hint.

    Returns (error_class, remediation_key) where remediation_key indexes _REMEDIATION.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return "http_auth", "http_auth"
        if code == 404:
            return "http_not_found", "http_not_found"
        return "http_error", "http_other"
    if isinstance(exc, httpx.ConnectError):
        return "connect_error", "connect_error"
    if isinstance(exc, httpx.ConnectTimeout):
        return "connect_timeout", "connect_timeout"
    if isinstance(exc, httpx.ReadTimeout):
        return "read_timeout", "read_timeout"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", "timeout_generic"
    if isinstance(exc, httpx.RequestError):
        return "request_error", "request_error"
    return "unexpected", "unexpected"


def _append_error(
    errors: list[dict[str, Any]],
    *,
    check: str,
    exc: BaseException,
    error_class: str,
    remediation_key: str,
) -> None:
    hint = _REMEDIATION.get(remediation_key, _REMEDIATION["unexpected"])
    entry: dict[str, Any] = {
        "check": check,
        "error_type": type(exc).__name__,
        "error_class": error_class,
        "remediation_hint": hint,
    }
    if isinstance(exc, httpx.HTTPStatusError):
        entry["http_status_code"] = exc.response.status_code
    errors.append(entry)


def _run_raw_exchange_status(
    base_url: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Low-level GET {base}/exchange/status without Kalshi RSA headers (public)."""
    root = str(base_url).rstrip("/")
    url = f"{root}/exchange/status"
    out: dict[str, Any] = {
        "name": "raw_http_exchange_status",
        "success": False,
        "url_host_only": _redacted_base_from_url(root),
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout_seconds)) as client:
            response = client.get(url)
        out["http_status_code"] = response.status_code
        out["success"] = 200 <= response.status_code < 300
        if out["success"]:
            try:
                body = response.json()
            except Exception:
                body = None
            if isinstance(body, dict):
                out["exchange_active"] = body.get("exchange_active")
                out["trading_active"] = body.get("trading_active")
        else:
            response.raise_for_status()
    except Exception as exc:
        error_class, key = classify_request_exception(exc)
        out["error_type"] = type(exc).__name__
        out["error_class"] = error_class
        out["remediation_hint"] = _REMEDIATION.get(key, _REMEDIATION["unexpected"])
        if isinstance(exc, httpx.HTTPStatusError):
            out["http_status_code"] = exc.response.status_code
        out["success"] = False
    return out


def _redacted_base_from_url(base_url: str) -> dict[str, Any]:
    parsed = urlparse(base_url)
    return {"scheme": parsed.scheme or None, "host": parsed.hostname}


def _make_client(settings: Settings, timeout_seconds: float | None) -> KalshiClient:
    ts = settings.kalshi_request_timeout_seconds if timeout_seconds is None else float(timeout_seconds)
    key_path = settings.kalshi_private_key_path
    return KalshiClient(
        settings.resolved_kalshi_base_url(),
        api_key_id=settings.kalshi_api_key_id,
        private_key_path=str(key_path) if key_path is not None else None,
        timeout_seconds=ts,
    )


def run_kalshi_connectivity_diagnostics(
    *,
    settings: Settings | None = None,
    tickers: Sequence[str] = (),
    timeout_seconds: float | None = None,
    include_auth_check: bool = True,
    max_tickers: int = 25,
    include_ticker_sample: bool = False,
) -> dict[str, Any]:
    """
    Run read-only connectivity checks against Kalshi Trade API v2.

    Does not call order, portfolio, position, or fill endpoints.
    """
    started = _utc_iso()
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    hints: list[str] = []

    s = settings if settings is not None else get_settings()
    config = _config_block(s)
    effective_timeout = (
        s.kalshi_request_timeout_seconds if timeout_seconds is None else float(timeout_seconds)
    )

    checks: dict[str, Any] = {
        "raw_http_exchange_status": None,
        "kalshi_client_exchange_status": None,
        "kalshi_client_markets_limit_1": None,
        "authenticated_read_smoke": None,
        "batch_tickers": None,
        "single_ticker_fallback": None,
    }

    base = s.resolved_kalshi_base_url()
    checks["raw_http_exchange_status"] = _run_raw_exchange_status(base, effective_timeout)
    if not checks["raw_http_exchange_status"].get("success"):
        et = checks["raw_http_exchange_status"].get("error_type")
        if et:
            warnings.append(f"raw_http_exchange_status_failed:{et}")
        rh = checks["raw_http_exchange_status"].get("remediation_hint")
        if isinstance(rh, str):
            hints.append(rh)

    client = _make_client(s, timeout_seconds)
    try:
        # Client exchange status
        ex_check: dict[str, Any] = {"name": "kalshi_client_exchange_status", "success": False}
        try:
            body = client.get_exchange_status()
            ex_check["success"] = True
            if isinstance(body, dict):
                ex_check["exchange_active"] = body.get("exchange_active")
                ex_check["trading_active"] = body.get("trading_active")
        except Exception as exc:
            ec, key = classify_request_exception(exc)
            ex_check["error_type"] = type(exc).__name__
            ex_check["error_class"] = ec
            ex_check["remediation_hint"] = _REMEDIATION.get(key, _REMEDIATION["unexpected"])
            _append_error(errors, check="kalshi_client_exchange_status", exc=exc, error_class=ec, remediation_key=key)
            if isinstance(ex_check["remediation_hint"], str):
                hints.append(ex_check["remediation_hint"])
        checks["kalshi_client_exchange_status"] = ex_check

        # Markets smoke
        mk_check: dict[str, Any] = {
            "name": "kalshi_client_markets_limit_1",
            "success": False,
            "markets_returned_count": None,
            "cursor_present": None,
        }
        try:
            page = client.get_markets(limit=1)
            markets = page.get("markets") if isinstance(page, dict) else None
            if isinstance(markets, list):
                mk_check["markets_returned_count"] = len(markets)
            else:
                mk_check["markets_returned_count"] = None
            mk_check["cursor_present"] = bool(isinstance(page, dict) and page.get("cursor"))
            mk_check["success"] = True
        except Exception as exc:
            ec, key = classify_request_exception(exc)
            mk_check["error_type"] = type(exc).__name__
            mk_check["error_class"] = ec
            mk_check["remediation_hint"] = _REMEDIATION.get(key, _REMEDIATION["unexpected"])
            _append_error(errors, check="kalshi_client_markets_limit_1", exc=exc, error_class=ec, remediation_key=key)
            if isinstance(mk_check["remediation_hint"], str):
                hints.append(mk_check["remediation_hint"])
        checks["kalshi_client_markets_limit_1"] = mk_check

        # Authenticated read (optional): one GET /events?limit=1 with signing headers — read-only listing
        auth_check: dict[str, Any] = {"name": "authenticated_read_smoke", "skipped": True, "success": True}
        want_auth = bool(include_auth_check)
        has_id = config["kalshi_api_key_id_configured"]
        has_path = config["kalshi_private_key_path_configured"]
        if not want_auth:
            auth_check["note"] = "skipped_by_flag"
        elif not has_id or not has_path:
            auth_check["skipped"] = True
            auth_check["success"] = True
            auth_check["note"] = "skipped_no_credentials_configured"
            warnings.append("authenticated_read_skipped: missing API key id or private key path configuration")
        else:
            auth_check["skipped"] = False
            auth_check["success"] = False
            try:
                _ = client.get_events(limit=1, authenticated=True)
                auth_check["success"] = True
            except KalshiAuthError as exc:
                auth_check["error_type"] = type(exc).__name__
                auth_check["error_class"] = "config_auth"
                auth_check["remediation_hint"] = (
                    "KalshiAuthError: verify KALSHI_API_KEY_ID and a readable RSA PEM private key "
                    "for the configured key path (file permissions and format)."
                )
                _append_error(
                    errors,
                    check="authenticated_read_smoke",
                    exc=exc,
                    error_class="config_auth",
                    remediation_key="http_auth",
                )
                hints.append(auth_check["remediation_hint"])
            except Exception as exc:
                ec, key = classify_request_exception(exc)
                auth_check["error_type"] = type(exc).__name__
                auth_check["error_class"] = ec
                auth_check["remediation_hint"] = _REMEDIATION.get(key, _REMEDIATION["unexpected"])
                _append_error(
                    errors,
                    check="authenticated_read_smoke",
                    exc=exc,
                    error_class=ec,
                    remediation_key=key,
                )
                if isinstance(auth_check["remediation_hint"], str):
                    hints.append(auth_check["remediation_hint"])
        checks["authenticated_read_smoke"] = auth_check

        # Ticker batch + optional single-ticker probe
        raw_ticker_list = list(tickers)
        requested_tickers_count = len(raw_ticker_list)
        dedup_seen: set[str] = set()
        uniq_full: list[str] = []
        for raw in raw_ticker_list:
            t = str(raw).strip()
            if not t or t in dedup_seen:
                continue
            dedup_seen.add(t)
            uniq_full.append(t)
        unique_tickers_count = len(uniq_full)

        truncated = False
        uniq = uniq_full
        if len(uniq) > int(max_tickers):
            truncated = True
            uniq = uniq[: int(max_tickers)]
            warnings.append(f"ticker_list_truncated_to_max_tickers={max_tickers}")

        if not uniq:
            checks["batch_tickers"] = {
                "name": "batch_tickers",
                "skipped": True,
                "success": True,
                "note": "no_tickers_requested",
            }
            checks["single_ticker_fallback"] = {
                "name": "single_ticker_fallback",
                "skipped": True,
                "success": True,
                "note": "no_tickers_requested",
            }
        else:
            bt: dict[str, Any] = {
                "name": "batch_tickers",
                "skipped": False,
                "success": False,
                "requested_tickers_count": requested_tickers_count,
                "unique_tickers_count": unique_tickers_count,
                "queried_tickers_count": len(uniq),
                "truncated": truncated,
                "returned_markets_count": None,
                "missing_tickers_count": None,
            }
            if include_ticker_sample:
                bt["ticker_sample"] = uniq[: min(5, len(uniq))]
            try:
                page = client.get_markets_by_tickers(uniq)
                mlist = page.get("markets") if isinstance(page, dict) else None
                rows = [m for m in (mlist or []) if isinstance(m, dict)]
                by_ticker = {
                    str(m.get("ticker") or "").strip(): m for m in rows if str(m.get("ticker") or "").strip()
                }
                bt["returned_markets_count"] = len(rows)
                missing = [t for t in uniq if t not in by_ticker]
                bt["missing_tickers_count"] = len(missing)
                bt["success"] = True
                if bt["missing_tickers_count"]:
                    warnings.append(
                        "batch_tickers_missing_some_tickers: counts_only; use --show-sample-tickers for a small list"
                    )
            except Exception as exc:
                ec, key = classify_request_exception(exc)
                bt["error_type"] = type(exc).__name__
                bt["error_class"] = ec
                bt["remediation_hint"] = _REMEDIATION.get(key, _REMEDIATION["unexpected"])
                _append_error(errors, check="batch_tickers", exc=exc, error_class=ec, remediation_key=key)
                if isinstance(bt["remediation_hint"], str):
                    hints.append(bt["remediation_hint"])
            checks["batch_tickers"] = bt

            st: dict[str, Any] = {
                "name": "single_ticker_fallback",
                "skipped": unique_tickers_count != 1,
                "success": True,
            }
            if unique_tickers_count == 1:
                st["success"] = False
                only = uniq_full[0]
                try:
                    page_one = client.get_market(only)
                    st["success"] = isinstance(page_one, dict)
                except Exception as exc:
                    ec, key = classify_request_exception(exc)
                    st["error_type"] = type(exc).__name__
                    st["error_class"] = ec
                    st["remediation_hint"] = _REMEDIATION.get(key, _REMEDIATION["unexpected"])
                    _append_error(errors, check="single_ticker_fallback", exc=exc, error_class=ec, remediation_key=key)
                    if isinstance(st["remediation_hint"], str):
                        hints.append(st["remediation_hint"])
            else:
                st["note"] = "skipped_not_exactly_one_unique_ticker"
            checks["single_ticker_fallback"] = st
    finally:
        client.close()

    remediation_hints = sorted(set(hints))

    def _required_ok() -> bool:
        raw = checks["raw_http_exchange_status"] or {}
        if not raw.get("success"):
            return False
        ex = checks["kalshi_client_exchange_status"] or {}
        if not ex.get("success"):
            return False
        mk = checks["kalshi_client_markets_limit_1"] or {}
        if not mk.get("success"):
            return False
        auth = checks["authenticated_read_smoke"] or {}
        if include_auth_check and not auth.get("skipped") and not auth.get("success"):
            return False
        bt = checks["batch_tickers"] or {}
        if not bt.get("skipped") and not bt.get("success"):
            return False
        st = checks["single_ticker_fallback"] or {}
        if not st.get("skipped") and not st.get("success"):
            return False
        return True

    success = _required_ok()

    return {
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "success": success,
        "config": config,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "remediation_hints": remediation_hints,
        "started_at": started,
        "finished_at": _utc_iso(),
    }


__all__ = [
    "DIAGNOSTIC_VERSION",
    "classify_request_exception",
    "run_kalshi_connectivity_diagnostics",
]
