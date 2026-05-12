"""Tests for deployment_smoke_check.py and render_systemd_units.py (offline, no root)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kalshi_no_carry.config import reset_settings_cache
from kalshi_no_carry.database import create_all_tables, create_engine_from_database_url

ROOT = Path(__file__).resolve().parents[1]


def _load_script_module(script_name: str):
    path = ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(script_name.replace(".py", ""), path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def isolated_env_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_settings_cache()


def test_deployment_smoke_check_sqlite_success(isolated_env_tmp, monkeypatch):
    dbf = Path.cwd() / "smoke.db"
    url = f"sqlite+pysqlite:///{dbf}"
    monkeypatch.setenv("DATABASE_URL", url)
    reset_settings_cache()
    eng = create_engine_from_database_url(url)
    try:
        create_all_tables(eng)
    finally:
        eng.dispose()
    reset_settings_cache()

    mod = _load_script_module("deployment_smoke_check.py")
    payload = mod.run(check_tables=True, create_tables=False, reports_dir=None)
    assert payload["success"] is True
    assert payload["database_dialect"] == "sqlite"
    assert payload["database_connection_ok"] is True
    assert not payload["missing_tables"]


def test_deployment_smoke_check_missing_database_url(isolated_env_tmp):
    reset_settings_cache()
    mod = _load_script_module("deployment_smoke_check.py")
    payload = mod.run(check_tables=False, create_tables=False, reports_dir=None)
    assert payload["success"] is False
    assert payload["error_type"] == "MissingDatabaseUrl"


def test_deployment_smoke_check_missing_tables_reported(isolated_env_tmp, monkeypatch):
    dbf = Path.cwd() / "empty.db"
    url = f"sqlite+pysqlite:///{dbf}"
    monkeypatch.setenv("DATABASE_URL", url)
    reset_settings_cache()

    mod = _load_script_module("deployment_smoke_check.py")
    payload = mod.run(check_tables=True, create_tables=False, reports_dir=None)
    assert payload["success"] is True
    assert payload["tables_checked"] is True
    assert payload["missing_tables"]


def test_deployment_smoke_check_subprocess_no_password_leak(isolated_env_tmp, monkeypatch):
    secret = "X_TEST_SECRET_PASSWORD_XYZZY_999"
    monkeypatch.setenv(
        "DATABASE_URL",
        f"postgresql+psycopg://demo:{secret}@127.0.0.1:59999/nocarry",
    )
    reset_settings_cache()
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "deployment_smoke_check.py")],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": f"postgresql+psycopg://demo:{secret}@127.0.0.1:59999/nocarry"},
        timeout=60,
    )
    assert secret not in proc.stdout
    assert secret not in proc.stderr
    assert proc.returncode != 0
    data = json.loads(proc.stdout)
    assert data.get("database_dialect") == "postgresql"
    assert data.get("database_url_set") is True


def test_deployment_smoke_reports_dir_probe(isolated_env_tmp, monkeypatch):
    dbf = Path.cwd() / "smoke2.db"
    url = f"sqlite+pysqlite:///{dbf}"
    monkeypatch.setenv("DATABASE_URL", url)
    reset_settings_cache()
    eng = create_engine_from_database_url(url)
    try:
        create_all_tables(eng)
    finally:
        eng.dispose()
    reset_settings_cache()

    rep = Path.cwd() / "reports_probe"
    mod = _load_script_module("deployment_smoke_check.py")
    payload = mod.run(check_tables=False, create_tables=False, reports_dir=rep)
    assert payload["success"] is True
    assert payload["reports_dir_writable"] is True


def test_render_systemd_units_replaces_placeholders(tmp_path):
    out = tmp_path / "systemd_out"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "render_systemd_units.py"),
            "--template-dir",
            str(ROOT / "deploy" / "digitalocean"),
            "--output-dir",
            str(out),
            "--user",
            "svc_kalshi_test",
            "--working-directory",
            "/tmp/knc_placeholder",
            "--environment-file",
            "/tmp/knc_placeholder/deploy/.env",
            "--python-path",
            "/tmp/knc_placeholder/.venv/bin/python",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)
    assert summary["success"] is True
    assert len(summary["files_rendered"]) >= 4

    rendered = (out / "kalshi-no-carry-collector.service").read_text(encoding="utf-8")
    assert "__USER__" not in rendered
    assert "svc_kalshi_test" in rendered
    assert "/tmp/knc_placeholder/.venv/bin/python" in rendered

    for tok in ("--run-backtest", "place_order", "portfolio"):
        assert tok not in rendered.lower()

    assert not any(p.name.endswith(".timer") and "__USER__" in p.read_text(encoding="utf-8") for p in out.glob("*.timer"))


def test_render_systemd_refuses_values_that_look_like_secrets(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "render_systemd_units.py"),
            "--template-dir",
            str(ROOT / "deploy" / "digitalocean"),
            "--output-dir",
            str(tmp_path / "out"),
            "--user",
            "u",
            "--working-directory",
            "password=not_ok",
            "--environment-file",
            "/e",
            "--python-path",
            "/p",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["success"] is False


def test_gitignore_ignores_deploy_env_and_build():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "deploy/**/*.env" in gi
    assert "!deploy/**/*.env.example" in gi
    assert "build/" in gi
    assert "reports/" in gi
    assert "logs/" in gi
