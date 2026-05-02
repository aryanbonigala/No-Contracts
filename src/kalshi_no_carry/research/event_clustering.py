"""
Deterministic event/market clustering for leakage-safe research splits.

Clusters group ``raw_markets`` and ``raw_events`` so all markets under the same
``event_ticker`` share one cluster. Fallback grouping uses ``series_ticker`` +
normalized title prefix + close date when ``event_ticker`` is absent.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

_MAX_TITLE_PREFIX = 80
_MAX_CLUSTER_ID_LEN = 250


def normalize_title_for_clustering(title: str | None) -> str:
    """
    Conservative normalization: lowercase, trim, collapse whitespace, strip common punctuation edges.
    """
    if not title:
        return ""
    t = str(title).lower().strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[\t\n\r]+", " ", t)
    t = re.sub(r"^[,;:!?.]+|[,;:!?.]+$", "", t)
    return t.strip()


def title_prefix_for_fallback(title: str | None) -> str:
    n = normalize_title_for_clustering(title)
    if not n:
        return "notitle"
    p = n[:_MAX_TITLE_PREFIX]
    return re.sub(r"[^a-z0-9]+", "_", p).strip("_") or "notitle"


def reference_time_from_market_row(m: Mapping[str, Any]) -> datetime:
    """Resolve reference instant from denormalized market columns or ``raw_json``."""
    for key in ("close_time", "expiration_time", "settlement_time"):
        if m.get(key) is not None:
            return _ensure_utc(m[key])
    if isinstance(m.get("raw_json"), dict):
        rj = m["raw_json"]
        for path in (
            ("close_time",),
            ("latest_expiration_time",),
            ("expiration_time",),
            ("settlement_ts",),
        ):
            v = rj
            for p in path:
                v = v.get(p) if isinstance(v, dict) else None
            if v is not None:
                return _parse_any_dt(v)
    if m.get("fetched_at") is not None:
        return _ensure_utc(m["fetched_at"])
    if isinstance(m.get("raw_json"), dict) and m["raw_json"].get("fetched_at"):
        return _parse_any_dt(m["raw_json"]["fetched_at"])
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def reference_time_from_event_row(e: Mapping[str, Any]) -> datetime:
    for key in ("close_time", "expiration_time", "settlement_time"):
        if e.get(key) is not None:
            return _ensure_utc(e[key])
    if isinstance(e.get("raw_json"), dict):
        rj = e["raw_json"]
        for k in ("close_time", "latest_expiration_time", "settlement_ts", "expiration_time"):
            if rj.get(k) is not None:
                return _parse_any_dt(rj[k])
    if e.get("fetched_at") is not None:
        return _ensure_utc(e["fetched_at"])
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse_any_dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        return _ensure_utc(v)
    if isinstance(v, str):
        s = v.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _ensure_utc(dt: Any) -> datetime:
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def cluster_key_for_event_ticker(event_ticker: str) -> str:
    et = event_ticker.strip()
    return f"event_ticker:{et}"


def cluster_key_fallback(
    series_ticker: str | None,
    title: str | None,
    ref: datetime,
) -> str:
    st = (series_ticker or "noser").strip() or "noser"
    prefix = title_prefix_for_fallback(title)
    day = ref.date().isoformat()
    return f"fallback:{st}|{prefix}|{day}"


def deterministic_cluster_id_from_key(cluster_key: str) -> str:
    """Stable short id from arbitrary cluster_key (SHA-256 hex prefix)."""
    h = hashlib.sha256(cluster_key.encode("utf-8")).hexdigest()[:24]
    if cluster_key.startswith("event_ticker:"):
        raw = cluster_key.split(":", 1)[1]
        safe = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", raw).strip("_")
        base = f"evt:{safe}"[:_MAX_CLUSTER_ID_LEN]
        return base
    return f"cf:{h}"


@dataclass
class ClusterDraft:
    cluster_key: str
    event_ticker: str | None
    series_ticker: str | None
    category: str | None
    titles: list[str] = field(default_factory=list)
    reference_times: list[datetime] = field(default_factory=list)
    source_market_tickers: list[str] = field(default_factory=list)
    source_event_tickers: list[str] = field(default_factory=list)

    def add_market(self, row: Mapping[str, Any], market_ticker: str) -> None:
        self.source_market_tickers.append(market_ticker)
        t = row.get("title") or row.get("subtitle")
        if t:
            self.titles.append(str(t))
        rt = reference_time_from_market_row(row)
        self.reference_times.append(rt)
        self._merge_series_category(row)

    def add_event(self, row: Mapping[str, Any], event_ticker: str) -> None:
        self.source_event_tickers.append(event_ticker)
        for t in (row.get("title"), row.get("sub_title")):
            if t:
                self.titles.append(str(t))
        self.reference_times.append(reference_time_from_event_row(row))
        self._merge_series_category(row)

    def _merge_series_category(self, row: Mapping[str, Any]) -> None:
        st = row.get("series_ticker")
        if st and not self.series_ticker:
            self.series_ticker = str(st).strip() or None
        cat = row.get("category")
        if cat and not self.category:
            self.category = str(cat).strip() or None

    def to_cluster_close_time(self) -> datetime:
        """
        Cluster ordering time: earliest per-row reference instant across members.

        Each row's reference instant follows ``close_time`` → ``expiration_time`` →
        ``settlement_time`` → ``raw_json`` fallbacks → ``fetched_at`` (see
        ``reference_time_from_*``). Taking the minimum places the cluster on the
        timeline by its earliest such boundary (deterministic tie-breaks use cluster_id).
        """
        if not self.reference_times:
            return datetime(1970, 1, 1, tzinfo=timezone.utc)
        return min(self.reference_times)

    def representative_title(self) -> str | None:
        if not self.titles:
            return None
        return max(self.titles, key=len)

    def to_raw_json(self) -> dict[str, Any]:
        return {
            "cluster_key": self.cluster_key,
            "source_event_tickers": sorted(set(self.source_event_tickers)),
            "source_market_tickers": sorted(set(self.source_market_tickers)),
        }


def merge_raw_into_cluster_drafts(
    raw_events: list[Mapping[str, Any]],
    raw_markets: list[Mapping[str, Any]],
) -> dict[str, ClusterDraft]:
    """
    Build a mapping ``cluster_key -> ClusterDraft``.

    Key is ``cluster_key`` (event_ticker-based or fallback); merges
    rows that share the same logical group.
    """
    by_ck: dict[str, ClusterDraft] = {}

    for ev in raw_events:
        et = str(ev.get("event_ticker") or ev.get("ticker") or "").strip()
        if not et:
            continue
        ck = cluster_key_for_event_ticker(et)
        if ck not in by_ck:
            by_ck[ck] = ClusterDraft(
                cluster_key=ck,
                event_ticker=et,
                series_ticker=(
                    str(ev.get("series_ticker")).strip() if ev.get("series_ticker") else None
                ),
                category=(str(ev.get("category")).strip() if ev.get("category") else None),
            )
        by_ck[ck].add_event(ev, et)

    for mk in raw_markets:
        mt = str(mk.get("market_ticker") or mk.get("ticker") or "").strip()
        if not mt:
            continue
        et = str(mk.get("event_ticker") or "").strip() or None
        if et:
            ck = cluster_key_for_event_ticker(et)
        else:
            ref = reference_time_from_market_row(mk)
            ck = cluster_key_fallback(
                str(mk.get("series_ticker") or "").strip() or None,
                mk.get("title") or mk.get("subtitle"),
                ref,
            )
        if ck not in by_ck:
            by_ck[ck] = ClusterDraft(
                cluster_key=ck,
                event_ticker=et,
                series_ticker=(
                    str(mk.get("series_ticker")).strip() if mk.get("series_ticker") else None
                ),
                category=(str(mk.get("category")).strip() if mk.get("category") else None),
            )
        else:
            if et and not by_ck[ck].event_ticker:
                by_ck[ck].event_ticker = et
        by_ck[ck].add_market(mk, mt)

    return by_ck


def draft_to_upsert_kwargs(draft: ClusterDraft) -> dict[str, Any]:
    return {
        "cluster_id": deterministic_cluster_id_from_key(draft.cluster_key),
        "cluster_key": draft.cluster_key[:256],
        "event_ticker": draft.event_ticker,
        "series_ticker": draft.series_ticker,
        "category": draft.category,
        "representative_title": draft.representative_title(),
        "close_time": draft.to_cluster_close_time(),
        "raw_json": draft.to_raw_json(),
    }
