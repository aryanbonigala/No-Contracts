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


def chronological_partition_sizes(
    n: int,
    train_fraction: float,
    validation_fraction: float,
) -> tuple[int, int, int]:
    """
    Deterministic integer sizes for a chronological 3-way split of *n* clusters.

    Uses ``int(n * train_fraction)`` and ``int(n * (train_fraction + validation_fraction))``
    boundaries; the remainder is **test** (same structure as integer-percent splits for 60/20/20).
    """
    if n < 0:
        raise ValueError("n must be non-negative")
    if train_fraction < 0 or validation_fraction < 0:
        raise ValueError("fractions must be non-negative")
    if n == 0:
        return (0, 0, 0)
    cut_train = int(n * train_fraction)
    cut_val_boundary = int(n * (train_fraction + validation_fraction))
    n_train = cut_train
    n_val = cut_val_boundary - cut_train
    n_test = n - cut_val_boundary
    if n_test < 0:
        raise RuntimeError("internal partition sizing error")
    return n_train, n_val, n_test


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
