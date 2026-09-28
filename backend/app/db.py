"""Database engine and session management."""

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _make_engine(url: str) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def init_db(url: str | None = None) -> Engine:
    """(Re)initialise the engine and create tables. Safe to call more than once."""
    global _engine, _SessionLocal
    settings = get_settings()
    url = url or settings.sqlalchemy_url
    if url.startswith("sqlite:///"):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
    _engine = _make_engine(url)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    from . import models  # noqa: F401  - register tables

    Base.metadata.create_all(_engine)
    return _engine


def new_session() -> Session:
    if _SessionLocal is None:
        init_db()
    assert _SessionLocal is not None
    return _SessionLocal()


def get_db() -> Iterator[Session]:
    db = new_session()
    try:
        yield db
    finally:
        db.close()
