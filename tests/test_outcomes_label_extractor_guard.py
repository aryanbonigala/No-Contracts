"""Ensure outcome labeling does not read market titles as resolution evidence."""

from __future__ import annotations

from pathlib import Path


def test_outcomes_extractor_source_avoids_title_fields() -> None:
    root = Path(__file__).resolve().parents[1]
    src = (root / "src" / "kalshi_no_carry" / "research" / "outcomes.py").read_text(encoding="utf-8")
    assert '.get("title")' not in src
    assert '["title"]' not in src
