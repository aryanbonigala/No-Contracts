"""Lightweight static checks for deployment templates and deployment docs."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "digitalocean"
DEPLOY_DOC = ROOT / "docs" / "DEPLOYMENT_DIGITALOCEAN.md"

FORBIDDEN_DOC_TOKENS = (
    "edge_score",
    "alpha_score",
    "signal_weight",
    "profit_filter",
    "private_strategy",
    "secret_strategy",
    "kelly",
    "sharpe_target",
    "category_edge",
)

FORBIDDEN_SYSTEMD_SUBSTR = (
    "--run-backtest",
    "place_order",
    "create_order",
    "submit_order",
    "portfolio",
    "execution",
)


def _paths_to_scan_for_doc_tokens() -> list[Path]:
    paths = [DEPLOY_DOC]
    for p in sorted(DEPLOY.iterdir()):
        if p.suffix in (".service", ".timer") or p.name.endswith(".env.example"):
            paths.append(p)
    return paths


def test_deployment_files_avoid_leakage_tokens() -> None:
    for path in _paths_to_scan_for_doc_tokens():
        text = path.read_text(encoding="utf-8").lower()
        for tok in FORBIDDEN_DOC_TOKENS:
            assert tok not in text, f"{tok} found in {path.relative_to(ROOT)}"


def test_systemd_templates_avoid_trading_substrings() -> None:
    for path in sorted(DEPLOY.glob("*.service")) + sorted(DEPLOY.glob("*.timer")):
        text = path.read_text(encoding="utf-8").lower()
        for tok in FORBIDDEN_SYSTEMD_SUBSTR:
            assert tok not in text, f"{tok} found in {path.relative_to(ROOT)}"
