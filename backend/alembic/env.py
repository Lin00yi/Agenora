"""Alembic async environment for Agenora.

Production schema ownership belongs to Alembic. Fresh databases are created by
the ``0000_schema_bootstrap`` revision; existing databases should be verified
and stamped before they receive later forward-only revisions:

    cd backend
    alembic revision --autogenerate -m "describe change"
    alembic upgrade head

For a database that already matches models, stamp instead of re-applying:

    alembic stamp head
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.storage.database import Base
from src.settings import get_settings

# Import models so Base.metadata is complete for autogenerate.
from src.auth import models as _auth_models  # noqa: F401
from src.conversations import models as _conv_models  # noqa: F401
from src.kb import models as _kb_models  # noqa: F401
from src.observability import models as _obs_models  # noqa: F401
from src.settings_user import models as _settings_user_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
