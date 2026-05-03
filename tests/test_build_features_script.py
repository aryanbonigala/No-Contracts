"""CLI tests for scripts/build_features.py."""

from __future__ import annotations

import importlib.util
import json
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def test_build_features_exits_without_database_url() -> None:
    spec = importlib.util.spec_from_file_location("build_features_cli", ROOT / "scripts" / "build_features.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    with patch("kalshi_no_carry.config.get_settings", return_value=MagicMock(database_url=None)):
        spec.loader.exec_module(mod)
        out = StringIO()
        with patch("sys.stdout", out):
            rc = mod.main([])
    assert rc == 2
    payload = json.loads(out.getvalue())
    assert payload["success"] is False


def test_build_features_dry_run_does_not_print_database_url() -> None:
    secret = "NEVERLEAKTHIS459"
    url = f"sqlite+pysqlite:///{secret}_path/mem.db"
    settings = MagicMock(database_url=url)
    spec = importlib.util.spec_from_file_location("build_features_cli", ROOT / "scripts" / "build_features.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    with patch("kalshi_no_carry.config.get_settings", return_value=settings):
        spec.loader.exec_module(mod)

    engine = MagicMock()
    engine.dispose = MagicMock()

    session = MagicMock()

    @contextmanager
    def _begin():
        yield None

    session.begin = MagicMock(side_effect=_begin)

    @contextmanager
    def _sess():
        yield session

    def fake_sessionmaker(*args: object, **kwargs: object):
        return lambda: _sess()

    with patch("kalshi_no_carry.database.create_engine_from_database_url", return_value=engine):
        with patch("kalshi_no_carry.logging_setup.configure_logging", MagicMock()):
            with patch("sqlalchemy.orm.sessionmaker", side_effect=fake_sessionmaker):
                with patch(
                    "kalshi_no_carry.db.repositories.list_orderbook_snapshots_for_feature_building",
                    return_value=[],
                ):
                    buf = StringIO()
                    with patch("sys.stdout", buf):
                        rc = mod.main(["--dry-run"])

    assert rc == 0
    text = buf.getvalue()
    assert secret not in text
    assert url not in text
    payload = json.loads(text)
    assert payload["success"] is True
