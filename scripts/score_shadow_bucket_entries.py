#!/usr/bin/env python3
"""Score shadow bucket entries after settlement (read-only DB updates)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Score unscored shadow_bucket_entries rows.")
    p.add_argument("--shadow-version", required=True)
    p.add_argument("--label-version", default=None)
    p.add_argument("--experiment-name", default=None)
    p.add_argument("--limit", type=int, default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(_ROOT / "src"))
    args = _parse_args(argv)
    from kalshi_no_carry.config import get_settings
    from kalshi_no_carry.database import create_engine_from_database_url
    from kalshi_no_carry.research.score_shadow_buckets import score_shadow_bucket_entries
    from sqlalchemy.orm import sessionmaker

    settings = get_settings()
    if not settings.database_url:
        print("error: DATABASE_URL is required", file=sys.stderr)
        return 1

    engine = create_engine_from_database_url(str(settings.database_url))
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    try:
        with Session() as session:
            summary = score_shadow_bucket_entries(
                session,
                args.shadow_version,
                label_version=args.label_version,
                experiment_name=args.experiment_name,
                limit=args.limit,
            )
            session.commit()
    finally:
        engine.dispose()

    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
