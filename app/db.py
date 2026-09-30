"""Database engine, session factory, and FastAPI session dependency."""
from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

log = logging.getLogger("beckham_share.db")

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they do not exist (simple bootstrap; no migrations yet)."""
    from . import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Add columns the models declare and the existing tables lack.

    ``create_all`` creates missing tables and never touches ones that already
    exist, so adding a column to a live table does nothing at all. The column
    is then absent while the mappers include it in every INSERT, and the whole
    statement fails. That happened: a new column on ``download_events`` left
    downloads working and silently stopped recording any of them, because the
    recording path deliberately swallows its own errors.

    There are still no migrations here, on purpose. This closes the one gap
    bootstrap cannot: additive columns. Anything it cannot do safely, such as a
    dropped column, a changed type, or a NOT NULL column with no default, is
    logged loudly and left for an operator rather than guessed at.
    """
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            continue  # create_all just made it, so it matches
        present = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue

            column_type = column.type.compile(engine.dialect)
            default = getattr(column.default, "arg", None)
            has_scalar_default = default is not None and not callable(default)

            if column.nullable:
                clause = f"{column_type}"
            elif has_scalar_default:
                # A NOT NULL column can only join a populated table if existing
                # rows get a value, so borrow the model's own default.
                clause = f"{column_type} DEFAULT {default!r} NOT NULL"
            else:
                log.error(
                    "column %s.%s is missing and cannot be added safely "
                    "(NOT NULL with no usable default); add it by hand",
                    table.name, column.name,
                )
                continue

            statement = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {clause}'
            try:
                with engine.begin() as conn:
                    conn.execute(text(statement))
                log.info("added missing column %s.%s (%s)", table.name, column.name, column_type)
            except Exception as exc:  # noqa: BLE001
                log.error("could not add column %s.%s: %s", table.name, column.name, exc)
