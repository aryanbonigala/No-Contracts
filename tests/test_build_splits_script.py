"""Lightweight CLI checks for ``scripts/build_splits.py`` (no DATABASE_URL secrets in output)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SRC = str(ROOT / "src")


def _with_pythonpath(env: dict[str, str]) -> dict[str, str]:
    out = dict(env)
    pp = out.get("PYTHONPATH", "")
    out["PYTHONPATH"] = _SRC + (os.pathsep + pp if pp else "")
    return out


def test_build_splits_mutually_exclusive_flags_json_error(tmp_path) -> None:
    env = _with_pythonpath({**os.environ, "DATABASE_URL": "sqlite+pysqlite:///:memory:"})
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_splits.py"), "--clusters-only", "--splits-only"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 2
    payload = json.loads(r.stdout.strip())
    assert payload["success"] is False


def test_build_splits_requires_database_url(tmp_path) -> None:
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env.pop("DATABASE_URL", None)
    env = _with_pythonpath(env)
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_splits.py")],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 2
    payload = json.loads(r.stdout.strip())
    assert "DATABASE_URL" in payload.get("error", "")
