"""Tests for chronological event-cluster splits."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from kalshi_no_carry.research.splits import EventCluster, split_event_clusters_chronologically


def _dt(minutes: int) -> datetime:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return base + timedelta(minutes=minutes)


def test_split_60_20_20_counts() -> None:
    clusters = [
        EventCluster(cluster_id=f"c{i}", reference_time_utc=_dt(i)) for i in range(10)
    ]
    train, val, test = split_event_clusters_chronologically(clusters)
    assert len(train) == 6
    assert len(val) == 2
    assert len(test) == 2
    assert set(train) | set(val) | set(test) == {f"c{i}" for i in range(10)}


def test_split_respects_time_order() -> None:
    # n=5 => 60/20/20 integer allocation yields 3 / 1 / 1.
    clusters = [
        EventCluster("t4", _dt(400)),
        EventCluster("t0", _dt(0)),
        EventCluster("t2", _dt(200)),
        EventCluster("t1", _dt(100)),
        EventCluster("t3", _dt(300)),
    ]
    train, val, test = split_event_clusters_chronologically(clusters)
    assert train == ["t0", "t1", "t2"]
    assert val == ["t3"]
    assert test == ["t4"]


def test_duplicate_cluster_ids_rejected() -> None:
    clusters = [
        EventCluster("dup", _dt(1)),
        EventCluster("dup", _dt(2)),
    ]
    with pytest.raises(ValueError):
        split_event_clusters_chronologically(clusters)


def test_percentages_must_sum_to_100() -> None:
    with pytest.raises(ValueError):
        split_event_clusters_chronologically([], train_pct=50, val_pct=20, test_pct=20)


def test_stable_tiebreak_by_cluster_id() -> None:
    t = _dt(0)
    clusters = [
        EventCluster("b", t),
        EventCluster("a", t),
    ]
    train, val, test = split_event_clusters_chronologically(clusters)
    assert train == ["a"]
    assert val == []
    assert test == ["b"]
