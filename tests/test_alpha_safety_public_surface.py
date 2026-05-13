"""Lightweight checks that public CLIs/docs avoid obvious alpha-leakage tokens."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_PIPELINE_FLAGS = (
    "edge_score",
    "alpha_score",
    "signal_weight",
    "profit_filter",
    "category_edge",
    "private_strategy",
    "secret_strategy",
    "kelly",
    "sharpe_target",
)


def test_run_research_pipeline_cli_has_no_forbidden_flag_strings() -> None:
    text = (ROOT / "scripts" / "run_research_pipeline.py").read_text(encoding="utf-8")
    lowered = text.lower()
    for tok in FORBIDDEN_PIPELINE_FLAGS:
        assert tok not in lowered


def test_public_docs_do_not_reference_placeholder_private_alpha_module_name() -> None:
    """Guardrail string — adjust only if the repo intentionally documents a private plug-in name."""
    banned_phrases = ("private_strategy_alpha_v", "edge_threshold_module")
    for doc in ("README.md", "docs/ARCHITECTURE.md", "docs/RESEARCH_RULES.md"):
        p = ROOT / doc
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8").lower()
        for phrase in banned_phrases:
            assert phrase not in text


def test_refresh_lifecycle_cli_has_no_forbidden_flag_strings() -> None:
    text = (ROOT / "scripts" / "refresh_market_lifecycle.py").read_text(encoding="utf-8")
    lowered = text.lower()
    for tok in FORBIDDEN_PIPELINE_FLAGS:
        assert tok not in lowered


def test_check_kalshi_connectivity_cli_has_no_forbidden_flag_strings() -> None:
    text = (ROOT / "scripts" / "check_kalshi_connectivity.py").read_text(encoding="utf-8")
    lowered = text.lower()
    for tok in FORBIDDEN_PIPELINE_FLAGS:
        assert tok not in lowered


def test_connectivity_diagnostics_module_avoids_forbidden_tokens() -> None:
    path = ROOT / "src" / "kalshi_no_carry" / "diagnostics" / "kalshi_connectivity.py"
    text = path.read_text(encoding="utf-8").lower()
    for tok in FORBIDDEN_PIPELINE_FLAGS:
        assert tok not in text


def test_public_markdown_avoids_forbidden_alpha_tokens() -> None:
    paths = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    for doc_path in paths:
        if not doc_path.is_file():
            continue
        lowered = doc_path.read_text(encoding="utf-8").lower()
        for tok in FORBIDDEN_PIPELINE_FLAGS:
            assert tok not in lowered, doc_path
