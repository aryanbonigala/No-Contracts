"""Offline tests for Kalshi connectivity diagnostics (mocked HTTP only)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from kalshi_no_carry.config import Settings, get_settings, reset_settings_cache
from kalshi_no_carry.diagnostics import kalshi_connectivity as kc
from kalshi_no_carry.diagnostics.kalshi_connectivity import (
    classify_request_exception,
    run_kalshi_connectivity_diagnostics,
)
from kalshi_no_carry.kalshi_client import KalshiClient

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://api.elections.kalshi.com/trade-api/v2"


def _load_script_module(script_name: str):
    path = ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(script_name.replace(".py", ""), path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _success_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if u.rstrip("/").endswith("/exchange/status"):
            return httpx.Response(200, json={"exchange_active": True, "trading_active": True})
        if "/events" in u and "limit=1" in u:
            return httpx.Response(200, json={"events": [{"event_ticker": "E1"}], "cursor": None})
        if "/markets" in u and "tickers=" in u:
            return httpx.Response(
                200,
                json={"markets": [{"ticker": "AAA"}, {"ticker": "BBB"}], "cursor": None},
            )
        if "/markets" in u and "limit=1" in u and "tickers=" not in u:
            return httpx.Response(200, json={"markets": [{"ticker": "Z"}], "cursor": "c1"})
        if "/markets/AAA" in u and "orderbook" not in u:
            return httpx.Response(200, json={"market": {"ticker": "AAA"}})
        if "/markets/SINGLE" in u and "orderbook" not in u:
            return httpx.Response(200, json={"market": {"ticker": "SINGLE"}})
        return httpx.Response(404, text=f"unmatched:{u}")

    return httpx.MockTransport(handler)


def _fake_raw_ok(*_a: object, **_k: object) -> dict[str, object]:
    return {
        "name": "raw_http_exchange_status",
        "success": True,
        "http_status_code": 200,
        "exchange_active": True,
        "trading_active": True,
        "url_host_only": {"scheme": "https", "host": "api.elections.kalshi.com"},
    }


def test_config_reports_booleans_and_no_database_url_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@127.0.0.1:5432/mydb")
    monkeypatch.setenv("KALSHI_API_KEY_ID", "kid_test_123")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", "/tmp/secret-key.pem")
    reset_settings_cache()
    settings = get_settings()

    def _client_factory(s: Settings, timeout_seconds: float | None) -> KalshiClient:
        _ = (s, timeout_seconds)
        return KalshiClient(
            BASE,
            api_key_id="kid",
            http_client=httpx.Client(transport=_success_transport()),
        )

    with patch.object(kc, "_run_raw_exchange_status", side_effect=_fake_raw_ok):
        with patch.object(kc, "_make_client", side_effect=_client_factory):
            out = run_kalshi_connectivity_diagnostics(
                settings=settings,
                include_auth_check=False,
            )
    cfg = out["config"]
    assert cfg["kalshi_api_key_id_configured"] is True
    assert cfg["kalshi_private_key_path_configured"] is True
    assert cfg["database_url_configured"] is True
    dumped = json.dumps(out)
    assert "postgresql://" not in dumped
    assert "secret-key.pem" not in dumped
    assert "kid_test_123" not in dumped


def test_successful_core_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_settings_cache()
    settings = Settings(
        kalshi_no_carry_env="development",
        kalshi_env="prod",
        kalshi_base_url=BASE,
        kalshi_api_key_id=None,
        kalshi_private_key_path=None,
    )

    def _client_factory(s: Settings, timeout_seconds: float | None) -> KalshiClient:
        _ = (s, timeout_seconds)
        return KalshiClient(BASE, http_client=httpx.Client(transport=_success_transport()))

    with patch.object(kc, "_run_raw_exchange_status", side_effect=_fake_raw_ok):
        with patch.object(kc, "_make_client", side_effect=_client_factory):
            out = run_kalshi_connectivity_diagnostics(
                settings=settings,
                include_auth_check=False,
            )
    assert out["success"] is True
    assert out["checks"]["kalshi_client_exchange_status"]["success"] is True
    assert out["checks"]["kalshi_client_markets_limit_1"]["markets_returned_count"] == 1
    assert out["checks"]["kalshi_client_markets_limit_1"]["cursor_present"] is True


def test_batch_ticker_check(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_settings_cache()
    settings = Settings(
        kalshi_no_carry_env="development",
        kalshi_env="prod",
        kalshi_base_url=BASE,
    )

    def _client_factory(s: Settings, timeout_seconds: float | None) -> KalshiClient:
        _ = (s, timeout_seconds)
        return KalshiClient(BASE, http_client=httpx.Client(transport=_success_transport()))

    with patch.object(kc, "_run_raw_exchange_status", side_effect=_fake_raw_ok):
        with patch.object(kc, "_make_client", side_effect=_client_factory):
            out = run_kalshi_connectivity_diagnostics(
                settings=settings,
                tickers=["AAA", "BBB"],
                include_auth_check=False,
                include_ticker_sample=True,
            )
    bt = out["checks"]["batch_tickers"]
    assert bt["skipped"] is False
    assert bt["success"] is True
    assert bt["returned_markets_count"] == 2
    assert bt["missing_tickers_count"] == 0
    assert bt.get("ticker_sample") == ["AAA", "BBB"]


def test_connect_error_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_settings_cache()
    settings = Settings(kalshi_base_url=BASE)

    def _client_factory(s: Settings, timeout_seconds: float | None) -> KalshiClient:
        _ = (s, timeout_seconds)

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("nope", request=request)

        return KalshiClient(BASE, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    with patch.object(kc, "_run_raw_exchange_status", side_effect=_fake_raw_ok):
        with patch.object(kc, "_make_client", side_effect=_client_factory):
            out = run_kalshi_connectivity_diagnostics(settings=settings, include_auth_check=False)
    assert out["success"] is False
    assert any(e.get("error_class") == "connect_error" for e in out["errors"])
    assert kc._REMEDIATION["connect_error"] in out["remediation_hints"]


def test_timeout_exception_classified() -> None:
    err = httpx.PoolTimeout("boom")
    label, key = classify_request_exception(err)
    assert label == "timeout"
    assert key == "timeout_generic"


def test_http_status_auth_vs_not_found() -> None:
    req = httpx.Request("GET", "https://example.test/x")
    resp401 = httpx.Response(401, request=req)
    exc401 = httpx.HTTPStatusError("401", request=req, response=resp401)
    assert classify_request_exception(exc401)[0] == "http_auth"

    resp403 = httpx.Response(403, request=req)
    exc403 = httpx.HTTPStatusError("403", request=req, response=resp403)
    assert classify_request_exception(exc403)[0] == "http_auth"

    resp404 = httpx.Response(404, request=req)
    exc404 = httpx.HTTPStatusError("404", request=req, response=resp404)
    assert classify_request_exception(exc404)[0] == "http_not_found"


def test_read_timeout_classified() -> None:
    err = httpx.ReadTimeout("slow")
    assert classify_request_exception(err) == ("read_timeout", "read_timeout")


def test_cli_prints_safe_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(ROOT)
    reset_settings_cache()

    fake = {
        "diagnostic_version": "test",
        "success": True,
        "config": {"settings_loaded": True},
        "checks": {},
        "errors": [],
        "warnings": [],
        "remediation_hints": [],
        "started_at": "t0",
        "finished_at": "t1",
    }

    cli_mod = _load_script_module("check_kalshi_connectivity.py")

    with patch.object(cli_mod, "run_kalshi_connectivity_diagnostics", return_value=fake):
        rc = cli_mod.main([])

    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["success"] is True


def test_cli_fails_on_simulated_connect_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(ROOT)
    cli_mod = _load_script_module("check_kalshi_connectivity.py")

    fake = {
        "diagnostic_version": "test",
        "success": False,
        "config": {},
        "checks": {},
        "errors": [{"error_class": "connect_error"}],
        "warnings": [],
        "remediation_hints": [],
        "started_at": "t0",
        "finished_at": "t1",
    }
    with patch.object(cli_mod, "run_kalshi_connectivity_diagnostics", return_value=fake):
        rc = cli_mod.main([])

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False


def test_cli_does_not_require_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_settings_cache()
    cli_mod = _load_script_module("check_kalshi_connectivity.py")

    def _capture(**kwargs: object) -> dict[str, object]:
        _ = kwargs
        return {
            "diagnostic_version": "test",
            "success": True,
            "config": {},
            "checks": {},
            "errors": [],
            "warnings": [],
            "remediation_hints": [],
            "started_at": "t0",
            "finished_at": "t1",
        }

    with patch.object(cli_mod, "run_kalshi_connectivity_diagnostics", side_effect=_capture):
        assert cli_mod.main([]) == 0
    assert get_settings().database_url is None


def test_cli_output_redacts_secrets(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:ultra_secret_pw@db.example:5432/db")
    monkeypatch.setenv("KALSHI_API_KEY_ID", "PUBLIC_SHOULD_NOT_LEAK")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", "/Users/me/super_secret.pem")
    reset_settings_cache()

    cli_mod = _load_script_module("check_kalshi_connectivity.py")

    def _client_factory(s: Settings, timeout_seconds: float | None) -> KalshiClient:
        _ = (s, timeout_seconds)
        return KalshiClient(BASE, http_client=httpx.Client(transport=_success_transport()))

    with patch.object(kc, "_run_raw_exchange_status", side_effect=_fake_raw_ok):
        with patch.object(kc, "_make_client", side_effect=_client_factory):
            rc = cli_mod.main(["--skip-auth-check"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "ultra_secret_pw" not in out
    assert "postgresql://" not in out
    assert "PUBLIC_SHOULD_NOT_LEAK" not in out
    assert "super_secret.pem" not in out


def test_cli_writes_output_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    reset_settings_cache()
    cli_mod = _load_script_module("check_kalshi_connectivity.py")

    def _client_factory(s: Settings, timeout_seconds: float | None) -> KalshiClient:
        _ = (s, timeout_seconds)
        return KalshiClient(BASE, http_client=httpx.Client(transport=_success_transport()))

    out_path = tmp_path / "out.json"
    with patch.object(kc, "_run_raw_exchange_status", side_effect=_fake_raw_ok):
        with patch.object(kc, "_make_client", side_effect=_client_factory):
            assert cli_mod.main(["--skip-auth-check", "--output-json", str(out_path)]) == 0

    assert out_path.is_file()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert "checks" in data


def test_connectivity_module_skips_trading_endpoints() -> None:
    text = (ROOT / "src" / "kalshi_no_carry" / "diagnostics" / "kalshi_connectivity.py").read_text(encoding="utf-8")
    banned_substrings = (
        "create_order",
        "place_order",
        "submit_order",
        "/portfolio",
        "/fills",
    )
    lowered = text.lower()
    for tok in banned_substrings:
        assert tok not in lowered


def test_single_ticker_fallback_invoked_when_one_ticker() -> None:
    settings = Settings(kalshi_base_url=BASE)

    def _client_factory(s: Settings, timeout_seconds: float | None) -> KalshiClient:
        _ = (s, timeout_seconds)
        return KalshiClient(BASE, http_client=httpx.Client(transport=_success_transport()))

    with patch.object(kc, "_run_raw_exchange_status", side_effect=_fake_raw_ok):
        with patch.object(kc, "_make_client", side_effect=_client_factory):
            out = run_kalshi_connectivity_diagnostics(
                settings=settings,
                tickers=["SINGLE"],
                include_auth_check=False,
            )
    st = out["checks"]["single_ticker_fallback"]
    assert st["skipped"] is False
    assert st["success"] is True


def test_http_status_error_surfaces_on_markets_smoke() -> None:
    settings = Settings(kalshi_base_url=BASE)

    def _client_factory(s: Settings, timeout_seconds: float | None) -> KalshiClient:
        _ = (s, timeout_seconds)

        def handler(request: httpx.Request) -> httpx.Response:
            u = str(request.url)
            if u.rstrip("/").endswith("/exchange/status"):
                return httpx.Response(200, json={"exchange_active": True})
            if "/markets" in u and "limit=1" in u and "tickers=" not in u:
                return httpx.Response(401, json={"msg": "no"})
            return httpx.Response(404, text="no")

        return KalshiClient(BASE, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    with patch.object(kc, "_run_raw_exchange_status", side_effect=_fake_raw_ok):
        with patch.object(kc, "_make_client", side_effect=_client_factory):
            out = run_kalshi_connectivity_diagnostics(settings=settings, include_auth_check=False)
    assert out["success"] is False
    mk = out["checks"]["kalshi_client_markets_limit_1"]
    assert mk.get("error_class") == "http_auth"
