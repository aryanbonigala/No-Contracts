#!/usr/bin/env python3
"""Generate static HTML + JSON + CSV dashboards for shadow bucket scans."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build read-only dashboard artifacts from shadow_bucket tables.")
    p.add_argument("--shadow-version", required=True)
    p.add_argument("--experiment-name", default=None)
    p.add_argument("--output-dir", type=Path, default=Path("reports/shadow_dashboard/latest"))
    p.add_argument("--bucket-prices-cents", default=None, help="Comma-separated ints; default preset buckets")
    p.add_argument("--scan-run-id", default=None)
    p.add_argument("--include-unsettled", action="store_true", default=True)
    p.add_argument("--exclude-unsettled", action="store_true", default=False)
    p.add_argument("--min-settled-sample-warning", type=int, default=30)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(_ROOT / "src"))
    args = _parse_args(argv)

    if args.bucket_prices_cents:
        buckets = tuple(int(x.strip()) for x in str(args.bucket_prices_cents).split(",") if x.strip())
    else:
        buckets = (60, 70, 80, 85, 90, 95)
    inc_un = bool(args.include_unsettled) and not bool(args.exclude_unsettled)

    from kalshi_no_carry.config import get_settings
    from kalshi_no_carry.database import create_engine_from_database_url
    from kalshi_no_carry.research.shadow_bucket_dashboard import build_shadow_bucket_dashboard
    from sqlalchemy.orm import sessionmaker

    settings = get_settings()
    if not settings.database_url:
        print("error: DATABASE_URL is required", file=sys.stderr)
        return 1

    engine = create_engine_from_database_url(str(settings.database_url))
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    try:
        with Session() as session:
            summary = build_shadow_bucket_dashboard(
                session,
                shadow_version=args.shadow_version,
                experiment_name=args.experiment_name,
                buckets=buckets,
                output_dir=Path(args.output_dir),
                scan_run_id=args.scan_run_id,
                include_unsettled=inc_un,
                min_settled_sample_warning=int(args.min_settled_sample_warning),
                overwrite=bool(args.overwrite),
            )
            session.commit()
    finally:
        engine.dispose()

    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
