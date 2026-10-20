import logging
import time
from collections.abc import Callable

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings

log = logging.getLogger(__name__)


def _make_engine(url: str):
    if url.startswith("sqlite"):
        memory = url in ("sqlite://", "sqlite:///:memory:")
        return create_engine(url, connect_args={"check_same_thread": False},
                             **({"poolclass": StaticPool} if memory else {}))
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def use_engine(url: str) -> None:
    """Point the core at another database (tests)."""
    global engine
    engine = _make_engine(url)
    SessionLocal.configure(bind=engine)


def init_db(seed: Callable[[Session], None] | None = None, retries: int = 30) -> None:
    """Create tables (core + every model the bot has imported) and run the bot's seed function.
    Safe to call from the web and bot containers at the same time. No migrations: add columns as nullable or
    with defaults and use `add_columns` below until Alembic is introduced."""
    from . import models  # noqa: F401  (register core tables)

    for attempt in range(retries):
        try:
            with engine.begin() as conn:
                if conn.dialect.name == "postgresql":
                    conn.execute(text("SELECT pg_advisory_xact_lock(7311)"))
                Base.metadata.create_all(conn)
            break
        except Exception as exc:  # database still starting
            if attempt == retries - 1:
                raise
            log.warning("database not ready (%s); retrying", exc.__class__.__name__)
            time.sleep(2)
    if seed:
        with SessionLocal() as s:
            seed(s)
            s.commit()


def add_columns(table: str, columns: dict[str, str]) -> None:
    """Tiny forward-only migration helper: `add_columns("guilds", {"locale": "VARCHAR(16)"})`."""
    with engine.begin() as conn:
        for name, ddl in columns.items():
            if conn.dialect.name == "postgresql":
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "{name}" {ddl}'))
            else:
                cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
                if name not in cols:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN "{name}" {ddl}'))
