from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker, close_all_sessions

from mai.core.config import get_settings

_engine: Engine | None = None
_SessionFactory: sessionmaker | None = None


def get_engine() -> Engine:
    from sqlalchemy import create_engine

    global _engine
    if _engine is None:
        settings = get_settings()
        conn_str = f"sqlite:///{settings.db_path}"
        _engine = create_engine(conn_str, connect_args={"check_same_thread": False})

        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):  # type: ignore[override]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return _SessionFactory


def get_session() -> Session:
    return get_session_factory()()


@contextmanager
def session_scope() -> Session:
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Dispose cached engine/session so tests can swap DB paths."""
    global _engine, _SessionFactory
    close_all_sessions()
    _SessionFactory = None
    if _engine is not None:
        _engine.dispose()
        _engine = None
