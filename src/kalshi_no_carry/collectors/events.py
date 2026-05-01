"""Read-only collector: Kalshi events → ``raw_events`` + ``api_fetch_log``."""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.collectors.common import CollectorSummary, safe_error_message, utc_now
from kalshi_no_carry.db.repositories import record_api_fetch, upsert_event


def collect_events(
    client: Any,
    engine: Engine,
    *,
    limit: int = 100,
    max_pages: int | None = None,
    status: str | None = None,
    series_ticker: str | None = None,
    source: str = "kalshi",
) -> CollectorSummary:
    """
    Paginate ``GET /events``, upsert each event, and log each page fetch.

    ``client`` must provide ``get_events(limit=..., cursor=..., status=..., series_ticker=...)``.
    """
    summary = CollectorSummary(name="collect_events", started_at=utc_now())
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    cursor: str | None = None
    pages = 0
    try:
        while True:
            if max_pages is not None and pages >= max_pages:
                break
            with Session() as session:
                try:
                    page = client.get_events(
                        limit=limit,
                        cursor=cursor,
                        status=status,
                        series_ticker=series_ticker,
                    )
                except Exception as exc:
                    summary.success = False
                    summary.errors.append(safe_error_message(exc))
                    record_api_fetch(
                        session,
                        endpoint="/events",
                        params_json={
                            "limit": limit,
                            "status": status,
                            "series_ticker": series_ticker,
                            "page": pages,
                        },
                        status_code=None,
                        success=False,
                        error_message=safe_error_message(exc),
                        row_count=0,
                        source=source,
                    )
                    session.commit()
                    break

                events = page.get("events") or []
                if not isinstance(events, list):
                    events = []

                seen = 0
                for ev in events:
                    if not isinstance(ev, dict):
                        continue
                    try:
                        upsert_event(session, ev)
                    except ValueError:
                        continue
                    seen += 1
                    tid = str(ev.get("event_ticker") or ev.get("ticker") or "").strip()
                    if tid:
                        summary.ids_collected.append(tid)

                summary.fetched_pages += 1
                summary.records_seen += len(events)
                summary.records_written += seen

                record_api_fetch(
                    session,
                    endpoint="/events",
                    params_json={
                        "limit": limit,
                        "status": status,
                        "series_ticker": series_ticker,
                        "page": pages,
                    },
                    status_code=200,
                    success=True,
                    row_count=len(events),
                    source=source,
                )
                session.commit()

                cursor = page.get("cursor")
                if not cursor:
                    break
                pages += 1
    finally:
        summary.finished_at = utc_now()
    return summary
