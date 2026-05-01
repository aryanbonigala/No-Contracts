"""Chronological train / validation / test splits by event cluster (no peeking)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class EventCluster:
    """
    Minimal description of one split unit.

    ``reference_time_utc`` must be a timestamp that **does not use future information**
    relative to the research decision being modeled (e.g. first time the cluster is tradeable
    under your definitions — to be pinned down when features are implemented).
    """

    cluster_id: str
    reference_time_utc: datetime


def split_event_clusters_chronologically(
    clusters: Sequence[EventCluster],
    *,
    train_pct: int = 60,
    val_pct: int = 20,
    test_pct: int = 20,
) -> tuple[list[str], list[str], list[str]]:
    """
    Split unique event clusters into train/validation/test sets by time.

    Allocation uses integer percentages of ``n`` (deterministic, no randomness):
    ``n_train = n * train_pct // 100``, ``n_val = n * val_pct // 100``,
    ``n_test = n - n_train - n_val`` (remainder lands in test). For small ``n``,
    ``train`` or ``val`` may be empty even when percentages are non-zero.

    Clusters are ordered by ``(reference_time_utc, cluster_id)`` ascending.

    :param clusters: Sequence of clusters; duplicate ``cluster_id`` values raise.
    :param train_pct: Train proportion as integer percent (default 60).
    :param val_pct: Validation proportion (default 20).
    :param test_pct: Test proportion (default 20).
    :return: Three lists of cluster ids: train, validation, test.
    """
    if train_pct < 0 or val_pct < 0 or test_pct < 0:
        raise ValueError("percentages must be non-negative")
    if train_pct + val_pct + test_pct != 100:
        raise ValueError("train_pct + val_pct + test_pct must equal 100")
    cluster_list = list(clusters)
    ids_seen: set[str] = set()
    for c in cluster_list:
        if c.cluster_id in ids_seen:
            raise ValueError(f"duplicate cluster_id: {c.cluster_id!r}")
        ids_seen.add(c.cluster_id)

    ordered = sorted(cluster_list, key=lambda c: (c.reference_time_utc, c.cluster_id))
    n = len(ordered)
    n_train = (n * train_pct) // 100
    n_val = (n * val_pct) // 100
    n_test = n - n_train - n_val
    if n_test < 0:
        raise RuntimeError("internal split sizing error")

    ids = [c.cluster_id for c in ordered]
    return (
        ids[:n_train],
        ids[n_train : n_train + n_val],
        ids[n_train + n_val : n_train + n_val + n_test],
    )
