#!/usr/bin/env python3
"""Run ``alembic upgrade head`` using ``DATABASE_URL`` from the environment / Settings."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    from alembic import command
    from alembic.config import Config

    from kalshi_no_carry.config import get_settings

    settings = get_settings()
    if not settings.database_url:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        return 1

    os.environ["DATABASE_URL"] = str(settings.database_url)

    ini = _ROOT / "alembic.ini"
    if not ini.is_file():
        print("error: alembic.ini not found next to project root", file=sys.stderr)
        return 1

    cfg = Config(str(ini))
    try:
        command.upgrade(cfg, "head")
    except Exception as exc:
        print(f"error: alembic upgrade failed ({type(exc).__name__})", file=sys.stderr)
        return 1

    print("ok: alembic upgrade head completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
