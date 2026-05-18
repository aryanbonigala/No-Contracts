"""Safety grep for shadow bucket artifacts (no trading API strings)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN = (
    "create_order",
    "place_order",
    "submit_order",
    "cancel_order",
    "/portfolio",
    "/orders",
)


def test_shadow_bucket_scripts_avoid_trading_api_tokens() -> None:
    for name in (
        "run_shadow_bucket_scan.py",
        "score_shadow_bucket_entries.py",
        "run_shadow_bucket_report.py",
        "run_shadow_bucket_dashboard.py",
    ):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8").lower()
        for tok in FORBIDDEN:
            assert tok not in text, f"{tok} leaked into {name}"
