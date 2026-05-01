"""
SQLAlchemy database engine helpers and high-level persistence entrypoints.

v0.3 defines the schema under ``kalshi_no_carry.db.schema`` and repositories under
``kalshi_no_carry.db.repositories``. No Kalshi HTTP calls happen from this module.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from kalshi_no_carry.config import Settings
from kalshi_no_carry.db.schema import Base


def redact_database_url(url: str) -> str:
    """
    Return a display-safe form of *url* suitable for logs and ``check_env``.

    Passwords (``user:password@``) and ``password`` query params are masked.
    """
    parts = urlsplit(url)
    netloc = parts.netloc
    if "@" in netloc:
        userinfo, _, hostinfo = netloc.rpartition("@")
        username = userinfo.split(":", 1)[0] if userinfo else ""
        netloc = f"{username + ':' if username else ''}***@{hostinfo}"
    if parts.query:
        q = [
            (
                k,
                "***"
                if "secret" in k.lower() or "password" in k.lower() or k.lower() == "pwd"
                else v,
            )
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
        ]
        query = urlencode(q, doseq=True, safe="*")
    else:
        query = ""
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def create_engine_from_database_url(url: str, *, echo: bool = False) -> Engine:
    """
    Build a SQLAlchemy engine suitable for Postgres or SQLite.

    In-memory SQLite uses ``StaticPool`` so multiple connections share one DB.
    """
    kwargs: dict = {"echo": echo}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool

    engine = create_engine(url, future=True, **kwargs)
    if url.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _sqlite_fk(dbapi_connection, connection_record) -> None:
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def create_all_tables(engine: Engine) -> None:
    """Create all tables defined on ``Base.metadata`` (idempotent if tables exist)."""
    Base.metadata.create_all(engine)


def drop_all_tables(engine: Engine) -> None:
    """
    Drop every table in ``Base.metadata``.

    **Destructive:** intended for tests and disposable dev databases only. Do not call
    against production or shared research databases.
    """
    Base.metadata.drop_all(engine)


def healthcheck(engine: Engine) -> None:
    """Raise if the database does not respond to ``SELECT 1``."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def describe_intended_usage(settings: Settings) -> str:
    """
    Return a short description string for debugging/documentation.

    When ``DATABASE_URL`` is set, SQLAlchemy can open connections via
    ``create_engine_from_database_url``.
    """
    if settings.database_url is None:
        return "DATABASE_URL is not set; persistence is disabled in this process."
    return "DATABASE_URL is set; use create_engine_from_database_url + create_all_tables to initialize."
