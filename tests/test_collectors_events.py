"""Offline tests for event collector."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.collectors.events import collect_events
from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url, drop_all_tables
from kalshi_no_carry.db.schema import ApiFetchLog, RawEvent


class FakeEventsClient:
    def __init__(self) -> None:
        self.pages = [
            {
                "events": [
                    {"event_ticker": "E1", "title": "A", "series_ticker": "S", "status": "open"},
                    {"event_ticker": "E2", "title": "B", "series_ticker": "S"},
                ],
                "cursor": "n1",
            },
            {
                "events": [{"event_ticker": "E1", "title": "A-updated", "series_ticker": "S"}],
                "cursor": "",
            },
        ]
        self.calls = 0

    def get_events(self, **kwargs):
        if self.calls >= len(self.pages):
            return {"events": [], "cursor": ""}
        p = self.pages[self.calls]
        self.calls += 1
        return p


def test_collect_events_upserts_and_logs():
    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    Session = sessionmaker(engine, future=True)
    try:
        client = FakeEventsClient()
        summ = collect_events(client, engine, limit=10, max_pages=5, source="test")
        assert summ.success
        assert summ.fetched_pages == 2
        assert summ.records_seen == 3
        assert summ.records_written == 3
        assert set(summ.ids_collected) == {"E1", "E2"}

        with Session() as s:
            n_ev = s.scalar(select(func.count()).select_from(RawEvent))
            n_log = s.scalar(select(func.count()).select_from(ApiFetchLog))
            assert n_ev == 2
            assert n_log == 2
            e1 = s.get(RawEvent, "E1")
            assert e1 is not None
            assert e1.title == "A-updated"
    finally:
        drop_all_tables(engine)
        engine.dispose()


def test_collect_events_empty_ok():
    class Empty:
        def get_events(self, **kwargs):
            return {"events": [], "cursor": ""}

    engine = create_engine_from_database_url("sqlite+pysqlite:///:memory:")
    create_all_tables(engine)
    try:
        summ = collect_events(Empty(), engine, limit=10, max_pages=3, source="t")
        assert summ.success
        assert summ.records_seen == 0
        assert summ.fetched_pages == 1
    finally:
        drop_all_tables(engine)
        engine.dispose()
