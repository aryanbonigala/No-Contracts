"""Market lifecycle refresh (v0.15; SQLite + fakes only)."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine, func, select

from kalshi_no_carry.collectors.market_lifecycle import (
    BATCH_REFRESH_FALLBACK_WARN,
    find_lifecycle_refresh_candidates,
    refresh_markets_by_ticker,
)
from kalshi_no_carry.database import create_all_tables, drop_all_tables
from kalshi_no_carry.db.repositories import insert_orderbook_snapshot, upsert_market
from kalshi_no_carry.db.schema import ApiFetchLog, ResearchMarketLabel
from kalshi_no_carry.research.outcomes import LABEL_NO, DEFAULT_LABEL_VERSION


def _label_row(
    *,
    ticker: str,
    version: str = DEFAULT_LABEL_VERSION,
    result: str = "unknown",
    resolved: bool = False,
    void: bool = False,
) -> ResearchMarketLabel:
    now = datetime.now(timezone.utc)
    return ResearchMarketLabel(
        market_ticker=ticker,
        label_version=version,
        label_market_result=result,
        label_no_won=None,
        label_yes_won=None,
        label_is_resolved=resolved,
        label_is_void=void,
        label_confidence="low",
        label_source_field=None,
        label_source_value=None,
        label_reason=None,
        extracted_at=now,
        raw_json=None,
        created_at=now,
    )


@pytest.fixture
def mem():
    e = create_engine("sqlite+pysqlite:///:memory:", future=True)
    create_all_tables(e)
    yield e
    drop_all_tables(e)
    e.dispose()


def test_find_candidates_orderbook_unknown_label(mem):
    maker = __import__("sqlalchemy.orm", fromlist=["sessionmaker"]).sessionmaker(
        mem, expire_on_commit=False, future=True
    )
    day = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with maker() as s:
        upsert_market(
            s,
            {"ticker": "M1", "event_ticker": "E1", "status": "open"},
            fetched_at=day,
        )
        insert_orderbook_snapshot(
            s,
            "M1",
            {"orderbook_fp": {"yes_dollars": [["0.40", "1"]], "no_dollars": []}},
        )
        s.add(_label_row(ticker="M1", result="unknown", resolved=False))
        s.commit()

    out = find_lifecycle_refresh_candidates(mem, label_version=DEFAULT_LABEL_VERSION)
    assert "M1" in out


def test_find_candidates_excludes_resolved_yes_no_by_default(mem):
    maker = __import__("sqlalchemy.orm", fromlist=["sessionmaker"]).sessionmaker(
        mem, expire_on_commit=False, future=True
    )
    day = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with maker() as s:
        upsert_market(s, {"ticker": "R1", "status": "settled", "result": "yes"}, fetched_at=day)
        insert_orderbook_snapshot(s, "R1", {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}})
        s.add(_label_row(ticker="R1", result=LABEL_NO, resolved=True, void=False))
        s.commit()

    out = find_lifecycle_refresh_candidates(mem)
    assert "R1" not in out


def test_find_candidates_include_already_labeled(mem):
    maker = __import__("sqlalchemy.orm", fromlist=["sessionmaker"]).sessionmaker(
        mem, expire_on_commit=False, future=True
    )
    day = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with maker() as s:
        upsert_market(s, {"ticker": "R2", "status": "settled"}, fetched_at=day)
        insert_orderbook_snapshot(s, "R2", {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}})
        s.add(_label_row(ticker="R2", result=LABEL_NO, resolved=True))
        s.commit()

    out = find_lifecycle_refresh_candidates(mem, include_already_labeled=True)
    assert "R2" in out


def test_refresh_dedupes_preserves_order(mem):
    calls: list[str] = []

    class _C:
        def get_market(self, t: str):
            calls.append(t)
            return {"market": {"ticker": t, "status": "open", "event_ticker": "E"}}

    summ = refresh_markets_by_ticker(mem, _C(), ["A", "A", "B", "A"], batch_size=2)
    assert summ["unique_tickers_count"] == 2
    assert calls == ["A", "B"]
    assert summ["fallback_ticker_refresh_used"] is True
    assert summ["batch_refresh_used"] is False


def test_refresh_batches(mem):
    class _C:
        def __init__(self) -> None:
            self.batch_calls = 0

        def get_markets(self, **kwargs):
            self.batch_calls += 1
            tickers_raw = str(kwargs.get("tickers") or "")
            parts = [t.strip() for t in tickers_raw.split(",") if t.strip()]
            return {"markets": [{"ticker": t, "status": "open"} for t in parts]}

    tickers = [f"T{i}" for i in range(5)]
    client = _C()
    summ = refresh_markets_by_ticker(mem, client, tickers, batch_size=2)
    assert summ["batches_attempted"] == 3
    assert summ["markets_written"] == 5
    assert client.batch_calls == 3
    assert summ["batch_refresh_used"] is True
    assert summ["fallback_ticker_refresh_used"] is False


def test_refresh_missing_ticker(mem):
    class _C:
        def get_market(self, t: str):
            req = httpx.Request("GET", f"https://x/markets/{t}")
            resp = httpx.Response(404, request=req)
            raise httpx.HTTPStatusError("nope", request=req, response=resp)

    summ = refresh_markets_by_ticker(mem, _C(), ["GHOST"], batch_size=10)
    assert summ["missing_tickers_count"] >= 1
    assert summ["markets_seen"] == 0
    assert summ["fallback_ticker_refresh_used"] is True


def test_refresh_batch_missing_not_in_response(mem):
    class _C:
        def get_markets(self, **kwargs):
            return {"markets": [{"ticker": "ONLY", "status": "open"}]}

    summ = refresh_markets_by_ticker(mem, _C(), ["ONLY", "MISSING"], batch_size=10)
    assert summ["batch_refresh_used"] is True
    assert summ["missing_tickers_count"] >= 1
    assert "not_in_batch_response" in "".join(summ["errors"])


def test_refresh_fallback_on_batch_typeerror(mem):
    class _C:
        def get_markets(self, limit, cursor=None):  # noqa: ARG002 — no tickers kw
            raise TypeError("unexpected")

        def get_market(self, t: str):
            return {"market": {"ticker": t, "status": "open"}}

    summ = refresh_markets_by_ticker(mem, _C(), ["X", "Y"], batch_size=10)
    assert summ["markets_written"] == 2
    assert summ["fallback_ticker_refresh_used"] is True
    assert any(BATCH_REFRESH_FALLBACK_WARN in w for w in summ["warnings"])


def test_refresh_prefers_get_markets_by_tickers(mem):
    seen: dict = {}

    class _C:
        def get_markets_by_tickers(self, tickers):
            seen["tickers"] = list(tickers)
            return {"markets": [{"ticker": t, "status": "open"} for t in tickers]}

        def get_markets(self, **kwargs):  # should not be used
            raise RuntimeError("should not call get_markets")

    summ = refresh_markets_by_ticker(mem, _C(), ["P", "Q"], batch_size=10)
    assert seen["tickers"] == ["P", "Q"]
    assert summ["batch_refresh_used"] is True
    assert summ["fallback_ticker_refresh_used"] is False


def test_refresh_summary_fields_include_batch_flags(mem):
    class _C:
        def get_markets(self, **kwargs):
            t = (kwargs.get("tickers") or "").split(",")[0].strip()
            return {"markets": [{"ticker": t, "status": "open"}]}

    summ = refresh_markets_by_ticker(mem, _C(), ["Z"], batch_size=1)
    assert "batch_refresh_used" in summ
    assert "fallback_ticker_refresh_used" in summ


def test_refresh_dry_run_batch_no_db_writes(mem):
    from sqlalchemy.orm import sessionmaker

    from kalshi_no_carry.db.schema import RawMarket

    maker = sessionmaker(mem, expire_on_commit=False, future=True)

    class _C:
        def get_markets(self, **kwargs):
            tickers_raw = str(kwargs.get("tickers") or "")
            parts = [t.strip() for t in tickers_raw.split(",") if t.strip()]
            return {"markets": [{"ticker": t, "status": "open"} for t in parts]}

    with maker() as s:
        before_m = int(s.scalar(select(func.count()).select_from(RawMarket)) or 0)
        before_l = int(s.scalar(select(func.count()).select_from(ApiFetchLog)) or 0)

    summ = refresh_markets_by_ticker(mem, _C(), ["A1", "B1"], batch_size=10, dry_run=True)
    assert summ["dry_run"] is True
    assert summ["batch_refresh_used"] is True

    with maker() as s:
        after_m = int(s.scalar(select(func.count()).select_from(RawMarket)) or 0)
        after_l = int(s.scalar(select(func.count()).select_from(ApiFetchLog)) or 0)
    assert after_m == before_m
    assert after_l == before_l


def test_refresh_summary_no_secrets(mem):
    secret = "KALSHI_SECRET_XYZ"

    class _C:
        def get_market(self, t: str):
            _ = secret  # noqa: F841 — ensure not echoed
            return {"market": {"ticker": t, "status": "open"}}

    summ = refresh_markets_by_ticker(mem, _C(), ["Q1"], batch_size=1)
    text = json.dumps(summ)
    assert secret not in text


def test_refresh_dry_run_no_db_writes_clean(mem):
    from sqlalchemy.orm import sessionmaker

    from kalshi_no_carry.db.schema import RawMarket

    maker = sessionmaker(mem, expire_on_commit=False, future=True)

    class _C:
        def get_market(self, t: str):
            return {"market": {"ticker": t, "status": "open", "event_ticker": "E"}}

    with maker() as s:
        before_m = int(s.scalar(select(func.count()).select_from(RawMarket)) or 0)
        before_l = int(s.scalar(select(func.count()).select_from(ApiFetchLog)) or 0)

    summ = refresh_markets_by_ticker(mem, _C(), ["Z9"], dry_run=True)
    assert summ["dry_run"] is True

    with maker() as s:
        after_m = int(s.scalar(select(func.count()).select_from(RawMarket)) or 0)
        after_l = int(s.scalar(select(func.count()).select_from(ApiFetchLog)) or 0)
    assert after_m == before_m
    assert after_l == before_l


def test_pipeline_refresh_before_labels(mem):
    from kalshi_no_carry.research.pipeline_runner import ResearchPipelineConfig, run_research_pipeline

    order: list[str] = []

    class _Stub:
        def get_market(self, t: str):
            return {"market": {"ticker": t, "status": "open"}}

    def _track_refresh(*_a, **_k):
        order.append("refresh")
        return {
            "requested_tickers_count": 1,
            "unique_tickers_count": 1,
            "batches_attempted": 1,
            "batches_succeeded": 1,
            "batch_refresh_used": True,
            "fallback_ticker_refresh_used": False,
            "markets_seen": 1,
            "markets_written": 1,
            "missing_tickers_count": 0,
            "errors": [],
            "warnings": [],
            "dry_run": False,
            "success": True,
            "started_at": "",
            "finished_at": "",
        }

    def _track_labels(*_a, **_k):
        order.append("labels")
        return {"success": True, "warnings": [], "markets_seen": 0, "labels_written": 0}

    cfg = ResearchPipelineConfig(
        refresh_lifecycle_markets=True,
        refresh_tickers=("RK",),
        refresh_batch_size=10,
        build_splits=False,
        build_features=False,
        run_audit=False,
    )
    with patch(
        "kalshi_no_carry.collectors.market_lifecycle.refresh_markets_by_ticker",
        side_effect=_track_refresh,
    ):
        with patch(
            "kalshi_no_carry.research.pipeline_runner.build_market_outcome_labels_from_raw_markets",
            side_effect=_track_labels,
        ):
            out = run_research_pipeline(mem, cfg, kalshi_client=_Stub())

    assert order == ["refresh", "labels"]
    assert out["stages"]["lifecycle_refresh"]["enabled"] is True
    assert "refresh_summary" in out["stages"]["lifecycle_refresh"]


def test_pipeline_explicit_refresh_tickers(mem):
    from kalshi_no_carry.research.pipeline_runner import ResearchPipelineConfig, run_research_pipeline

    seen: dict = {}

    class _Stub:
        pass

    def _capture(engine, client, tickers, **kwargs):
        seen["tickers"] = list(tickers)
        return {
            "requested_tickers_count": len(tickers),
            "unique_tickers_count": len(tickers),
            "batches_attempted": 1,
            "batches_succeeded": 1,
            "batch_refresh_used": True,
            "fallback_ticker_refresh_used": False,
            "markets_seen": len(tickers),
            "markets_written": len(tickers),
            "missing_tickers_count": 0,
            "errors": [],
            "warnings": [],
            "dry_run": False,
            "success": True,
            "started_at": "",
            "finished_at": "",
        }

    cfg = ResearchPipelineConfig(
        refresh_tickers=("FIRST", "SECOND"),
        build_splits=False,
        build_labels=False,
        build_features=False,
        run_audit=False,
    )
    with patch(
        "kalshi_no_carry.collectors.market_lifecycle.refresh_markets_by_ticker",
        side_effect=_capture,
    ) as m:
        out = run_research_pipeline(mem, cfg, kalshi_client=_Stub())
    m.assert_called_once()
    assert seen["tickers"] == ["FIRST", "SECOND"]
    assert out["stages"]["lifecycle_refresh"]["used_explicit_tickers"] is True


def test_pipeline_json_includes_lifecycle_stage(mem):
    from kalshi_no_carry.research.pipeline_runner import ResearchPipelineConfig, run_research_pipeline

    class _Stub:
        def get_markets(self, **kwargs):
            return {"markets": [{"ticker": "X1", "status": "open"}]}

    cfg = ResearchPipelineConfig(
        refresh_tickers=("X1",),
        build_splits=False,
        build_labels=False,
        build_features=False,
        run_audit=False,
    )
    out = run_research_pipeline(mem, cfg, kalshi_client=_Stub())
    blob = json.dumps(out, default=str)
    assert "lifecycle_refresh" in blob


ROOT = Path(__file__).resolve().parents[1]


def test_refresh_script_requires_database_url() -> None:
    spec = importlib.util.spec_from_file_location(
        "refresh_lifecycle_cli", ROOT / "scripts" / "refresh_market_lifecycle.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url=None)):
        spec.loader.exec_module(mod)
        out = StringIO()
        with patch("sys.stdout", out):
            rc = mod.main([])
    assert rc == 2
    assert json.loads(out.getvalue())["success"] is False


def test_refresh_script_safe_json_mock_client() -> None:
    spec = importlib.util.spec_from_file_location(
        "refresh_lifecycle_cli", ROOT / "scripts" / "refresh_market_lifecycle.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    engine = MagicMock()
    engine.dispose = MagicMock()

    class _FClient:
        def get_market(self, t: str):
            return {"market": {"ticker": t, "status": "open"}}

        def close(self):
            pass

    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url="sqlite:///x")):
        spec.loader.exec_module(mod)
        with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
            with patch("kalshi_no_carry.kalshi_client.KalshiClient.from_settings", return_value=_FClient()):
                with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
                    with patch(
                        "kalshi_no_carry.collectors.market_lifecycle.find_lifecycle_refresh_candidates",
                        return_value=["A"],
                    ):
                        with patch(
                            "kalshi_no_carry.collectors.market_lifecycle.refresh_markets_by_ticker",
                            return_value={"success": True, "errors": [], "warnings": []},
                        ):
                            log = StringIO()
                            with patch("sys.stdout", log):
                                rc = mod.main(["--limit", "1"])
    assert rc == 0
    body = json.loads(log.getvalue())
    assert body["success"] is True
