"""Alembic environment. REQ-PERSIST-004 — schema evolution without bricking user DBs.
Targets the SQLAlchemy models; DB URL from PSI_CRUX_DB_URL (default: local SQLite)."""
from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from psi_crux_core.db.models import Base

config = context.config
target_metadata = Base.metadata
_url = os.getenv("PSI_CRUX_DB_URL", "sqlite:///psi_crux.db")
config.set_main_option("sqlalchemy.url", _url)


def run_migrations_offline() -> None:
    context.configure(url=_url, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, render_as_batch=_url.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}),
                                     prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=_url.startswith("sqlite"))
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
