#!/usr/bin/env python3
"""Generate JSON + Markdown reports for NO bucket shadow experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Write shadow bucket experiment reports under reports/<report-name>/")
    p.add_argument("--shadow-version", required=True)
    p.add_argument("--experiment-name", default=None)
    p.add_argument("--report-name", default="shadow_bucket_report")
    p.add_argument("--output-dir", default=None, help="Override directory (default reports/<report-name>)")
    p.add_argument("--include-unscored", action="store_true", default=True)
    p.add_argument("--min-scored-sample", type=int, default=30)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(_ROOT / "src"))
    args = _parse_args(argv)
    from kalshi_no_carry.config import get_settings
    from kalshi_no_carry.database import create_engine_from_database_url
    from kalshi_no_carry.research.shadow_bucket_reporting import build_shadow_bucket_report
    from sqlalchemy.orm import sessionmaker

    settings = get_settings()
    if not settings.database_url:
        print("error: DATABASE_URL is required", file=sys.stderr)
        return 1

    out = Path(args.output_dir) if args.output_dir else None
    engine = create_engine_from_database_url(str(settings.database_url))
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    try:
        with Session() as session:
            summary = build_shadow_bucket_report(
                session,
                shadow_version=args.shadow_version,
                experiment_name=args.experiment_name,
                report_name=args.report_name,
                output_dir=out,
                include_unscored=args.include_unscored,
                min_scored_sample=args.min_scored_sample,
            )
    finally:
        engine.dispose()

    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
