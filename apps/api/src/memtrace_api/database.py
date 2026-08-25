"""Database engine creation, sessionmaker, and SQLite PRAGMA configuration."""

from __future__ import annotations

import logging
import unicodedata
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


def create_db_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine configured for SQLite WAL and foreign keys."""
    # Ensure directory exists for sqlite files
    if database_url.startswith("sqlite:///"):
        db_path = Path(database_url[len("sqlite:///") :])
        if not str(db_path).startswith(":memory:"):
            db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
        def _nfkc_casefold(value: str | None) -> str:
            if value is None:
                return ""
            return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

        dbapi_connection.create_function("memtrace_nfkc_cf", 1, _nfkc_casefold, deterministic=True)
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
