"""Build ``event_clusters`` from raw tables and assign chronological ``strategy_splits``."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from kalshi_no_carry.db.repositories import (
    count_strategy_splits,
    delete_strategy_splits_for_version,
    list_event_clusters,
    list_raw_events_for_clustering,
    list_raw_markets_for_clustering,
    upsert_event_cluster,
    upsert_strategy_split,
)
from kalshi_no_carry.research.event_clustering import (
    draft_to_upsert_kwargs,
    merge_raw_into_cluster_drafts,
)
from kalshi_no_carry.research.splits import chronological_partition_sizes

_DEFAULT_SPLIT_VERSION = "v0.5_chronological_60_20_20"
_FRACTION_TOLERANCE = 1e-6


class SplitVersionExistsError(Exception):
    """Raised when ``strategy_splits`` already contains rows for a ``split_version``."""

    def __init__(self, split_version: str) -> None:
        self.split_version = split_version
        super().__init__(
            f"strategy_splits already has rows for split_version={split_version!r}; "
            "pass overwrite=True for a controlled rebuild"
        )


def _session_factory(engine: Engine):
    return sessionmaker(engine, expire_on_commit=False, future=True)


def build_event_clusters_from_raw_data(
    engine: Engine,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Read ``raw_events`` / ``raw_markets``, build deterministic clusters, upsert ``event_clusters``.

    ``now`` is reserved for future provenance fields; it does not affect clustering.
    """
    _ = now
    warnings: list[str] = []
    maker = _session_factory(engine)
    with maker() as session:
        with session.begin():
            events = list_raw_events_for_clustering(session)
            markets = list_raw_markets_for_clustering(session)
            if not events:
                warnings.append("raw_events is empty")
            if not markets:
                warnings.append("raw_markets is empty")
            drafts = merge_raw_into_cluster_drafts(events, markets)
            ordered = sorted(
                drafts.values(),
                key=lambda d: draft_to_upsert_kwargs(d)["cluster_id"],
            )
            for draft in ordered:
                upsert_event_cluster(session, **draft_to_upsert_kwargs(draft))

    return {
        "raw_events_seen": len(events),
        "raw_markets_seen": len(markets),
        "clusters_built": len(drafts),
        "clusters_written": len(drafts),
        "warnings": warnings,
        "success": True,
    }


def assign_chronological_splits(
    engine: Engine,
    split_version: str,
    *,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    test_fraction: float = 0.20,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Assign whole clusters to train / validation / test by ``close_time``, then ``cluster_id``.

    Requires explicit ``split_version``. When rows already exist for that version and
    ``overwrite`` is false, raises ``SplitVersionExistsError`` without writes.
    """
    warnings: list[str] = []
    total = train_fraction + validation_fraction + test_fraction
    if abs(total - 1.0) > _FRACTION_TOLERANCE:
        raise ValueError(
            f"train_fraction + validation_fraction + test_fraction must sum to 1.0 "
            f"(±{_FRACTION_TOLERANCE}); got {total}"
        )
    sv = (split_version or "").strip()
    if not sv:
        raise ValueError("split_version is required and must be non-empty")

    maker = _session_factory(engine)
    overwritten = False
    with maker() as session:
        with session.begin():
            existing = count_strategy_splits(session, split_version=sv)
            if existing > 0 and not overwrite:
                raise SplitVersionExistsError(sv)
            if overwrite and existing > 0:
                delete_strategy_splits_for_version(session, sv)
                overwritten = True

            clusters = list_event_clusters(session)
            n = len(clusters)
            if n == 0:
                warnings.append("event_clusters is empty; no strategy_splits rows written")
                return _assign_summary(
                    split_version=sv,
                    total_clusters=0,
                    train_count=0,
                    validation_count=0,
                    test_count=0,
                    overwritten=overwritten,
                    warnings=warnings,
                    success=True,
                )

            n_train, n_val, n_test = chronological_partition_sizes(
                n, train_fraction, validation_fraction
            )
            if n_train + n_val + n_test != n:
                raise RuntimeError("internal split sizing error")

            ids = [c.cluster_id for c in clusters]
            train_ids = ids[:n_train]
            val_ids = ids[n_train : n_train + n_val]
            test_ids = ids[n_train + n_val :]

            now = datetime.now(timezone.utc)
            for cid in train_ids:
                upsert_strategy_split(
                    session, cluster_id=cid, split_name="train", split_version=sv, assigned_at=now
                )
            for cid in val_ids:
                upsert_strategy_split(
                    session,
                    cluster_id=cid,
                    split_name="validation",
                    split_version=sv,
                    assigned_at=now,
                )
            for cid in test_ids:
                upsert_strategy_split(
                    session, cluster_id=cid, split_name="test", split_version=sv, assigned_at=now
                )

    return _assign_summary(
        split_version=sv,
        total_clusters=n,
        train_count=len(train_ids),
        validation_count=len(val_ids),
        test_count=len(test_ids),
        overwritten=overwritten,
        warnings=warnings,
        success=True,
    )


def _assign_summary(
    *,
    split_version: str,
    total_clusters: int,
    train_count: int,
    validation_count: int,
    test_count: int,
    overwritten: bool,
    warnings: list[str],
    success: bool,
) -> dict[str, Any]:
    return {
        "split_version": split_version,
        "total_clusters": total_clusters,
        "train_count": train_count,
        "validation_count": validation_count,
        "test_count": test_count,
        "overwritten": overwritten,
        "warnings": warnings,
        "success": success,
    }


__all__ = [
    "_DEFAULT_SPLIT_VERSION",
    "SplitVersionExistsError",
    "assign_chronological_splits",
    "build_event_clusters_from_raw_data",
]
