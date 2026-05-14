"""End-to-end shadow bucket flow on SQLite (offline)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url, drop_all_tables
from kalshi_no_carry.db.schema import RawMarket, ShadowBucketEntry
from kalshi_no_carry.research.shadow_bucket_config import BucketShadowConfig
from kalshi_no_carry.research.shadow_bucket_experiment import run_bucket_shadow_scan_persisted
from kalshi_no_carry.research.score_shadow_buckets import score_shadow_bucket_entries
from kalshi_no_carry.research.shadow_bucket_reporting import build_shadow_bucket_report


class FakeE2EClient:
    def __init__(self) -> None:
        self.tickers_orderbooks = [
            ("M60", {"yes": [[40, 500]], "no": [[30, 100]]}),
            ("M85", {"yes": [[15, 500]], "no": [[10, 100]]}),
            ("M90", {"yes": [[10, 500]], "no": [[5, 100]]}),
            ("MNONE", {"yes": [], "no": []}),
        ]

    def iter_markets(self, **kwargs):
        close = datetime.now(timezone.utc) + timedelta(days=1)
        if kwargs.get("status") != "open":
            return iter(())
        for tid, _ in self.tickers_orderbooks:
            yield {
                "ticker": tid,
                "event_ticker": "E",
                "series_ticker": "S",
                "status": "open",
                "close_time": close.isoformat(),
            }

    def get_orderbook(self, ticker: str):
        for tid, book in self.tickers_orderbooks:
            if tid == ticker:
                return book
        raise RuntimeError("missing")


def test_e2e_scan_score_report(tmp_path) -> None:
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    cfg = BucketShadowConfig(
        shadow_version="v0.17a_no_bucket_shadow_experiment",
        experiment_name="no_bucket_shadow_experiment_v0",
        bucket_prices_cents=(60, 85, 90),
        stake_cents_per_trade=6000,
        entry_tolerance_cents=2,
    )
    try:
        now = datetime.now(timezone.utc)
        with Session() as s:
            run_bucket_shadow_scan_persisted(s, FakeE2EClient(), cfg, observed_at=now)
            s.commit()
            rows = list(s.scalars(select(ShadowBucketEntry)).all())
            assert len(rows) >= 3
            for mt, result in [
                ("M60", "yes"),
                ("M90", "no"),
            ]:
                s.add(
                    RawMarket(
                        market_ticker=mt,
                        raw_json={"ticker": mt, "status": "finalized", "result": result},
                        first_seen_at=now,
                        last_seen_at=now,
                        fetched_at=now,
                    )
                )
            s.commit()
            score_shadow_bucket_entries(s, cfg.shadow_version)
            s.commit()
            rows2 = list(s.scalars(select(ShadowBucketEntry)).all())
            scored = [r for r in rows2 if r.scored]
            assert any(r.market_ticker == "M90" for r in scored)
            assert any(r.market_ticker == "M85" and not r.scored for r in rows2)
        with Session() as s:
            rep = build_shadow_bucket_report(
                s,
                shadow_version=cfg.shadow_version,
                experiment_name=cfg.experiment_name,
                report_name="e2e",
                output_dir=tmp_path / "e2e",
                min_scored_sample=1,
            )
        assert rep["overall"]["total_entries"] >= 3
        js = (tmp_path / "e2e" / "shadow_bucket_report.json").read_text(encoding="utf-8")
        assert "60" in js and "95" in js
    finally:
        drop_all_tables(engine)
        engine.dispose()
