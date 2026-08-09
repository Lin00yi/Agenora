"""App database (SQLAlchemy async + SQLite).

Hosts user accounts, knowledge-base metadata, and other relational data that
isn't vectors. The vector data still lives in Qdrant (see vector_store.py).

DATABASE_URL examples:
    sqlite+aiosqlite:///./data/app.db   # local file (default)
    postgresql+asyncpg://user:pass@host/db   # future: hosted Postgres
"""
from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.settings import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy 2.x declarative base. All models inherit from this."""


_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


_LEGACY_DEEPSEEK_CHAT = "deepseek-chat"
_DEEPSEEK_V4_FLASH = "deepseek-v4-flash"
_STOPPED_GENERATION_MESSAGE = "用户已停止生成"


def get_engine():
    global _engine
    if _engine is None:
        s = get_settings()
        # Ensure parent dir exists for SQLite file paths
        if s.database_url.startswith("sqlite"):
            db_path = s.database_url.split("///")[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_async_engine(s.database_url, echo=False, future=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a per-request DB session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def init_db() -> None:
    """Create all tables. Called once on app startup.

    NOTE: For real schema evolution use Alembic. Auto-create is fine while we're
    pre-production with throw-away local data. We do one-shot ALTER TABLE
    fixups below for additive columns so existing dev DBs upgrade in place.
    """
    # Import models so they register with Base.metadata before create_all.
    from src.auth import models as _auth_models  # noqa: F401
    from src.conversations import models as _conv_models  # noqa: F401
    from src.kb import models as _kb_models  # noqa: F401
    from src.observability import models as _obs_models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_additive_columns)


def _migrate_additive_columns(sync_conn) -> None:
    """Add columns that were introduced after the initial table creation.

    Idempotent — each ALTER only runs if the column is missing. Keeps existing
    dev DBs working without needing to drop+recreate.
    """
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    tables = set(insp.get_table_names())

    # M4: kbs.is_system (bool, default 0)
    if "kbs" in tables:
        cols = {c["name"] for c in insp.get_columns("kbs")}
        if "is_system" not in cols:
            sync_conn.execute(
                text("ALTER TABLE kbs ADD COLUMN is_system BOOLEAN NOT NULL DEFAULT 0")
            )
        # v3-M3: kbs.grouping_enabled (bool, default 0) for Milvus group_by toggle
        if "grouping_enabled" not in cols:
            sync_conn.execute(
                text(
                    "ALTER TABLE kbs ADD COLUMN grouping_enabled "
                    "BOOLEAN NOT NULL DEFAULT 0"
                )
            )

        # v3-M7: per-KB embedding + reranker override columns.
        # 4 nullable embedding columns + 4 nullable reranker columns +
        # 1 NOT NULL reranker_enabled bool default 0.
        kb_new_cols = [
            ("embedding_provider",       "VARCHAR(32)"),
            ("embedding_base_url",       "VARCHAR(255)"),
            ("embedding_api_key_enc",    "VARCHAR(1024)"),
            ("embedding_model_override", "VARCHAR(128)"),
            ("reranker_provider",        "VARCHAR(32)"),
            ("reranker_base_url",        "VARCHAR(255)"),
            ("reranker_api_key_enc",     "VARCHAR(1024)"),
            ("reranker_model",           "VARCHAR(128)"),
        ]
        for col_name, col_type in kb_new_cols:
            if col_name not in cols:
                sync_conn.execute(
                    text(f"ALTER TABLE kbs ADD COLUMN {col_name} {col_type}")
                )
        if "reranker_enabled" not in cols:
            sync_conn.execute(
                text(
                    "ALTER TABLE kbs ADD COLUMN reranker_enabled "
                    "BOOLEAN NOT NULL DEFAULT 0"
                )
            )
        # v4: per-KB chunking defaults
        if "chunk_strategy" not in cols:
            sync_conn.execute(
                text(
                    "ALTER TABLE kbs ADD COLUMN chunk_strategy "
                    "VARCHAR(32) NOT NULL DEFAULT 'recursive'"
                )
            )
        if "chunk_target" not in cols:
            sync_conn.execute(
                text(
                    "ALTER TABLE kbs ADD COLUMN chunk_target "
                    "INTEGER NOT NULL DEFAULT 1500"
                )
            )
        if "chunk_max_size" not in cols:
            sync_conn.execute(
                text(
                    "ALTER TABLE kbs ADD COLUMN chunk_max_size "
                    "INTEGER NOT NULL DEFAULT 1800"
                )
            )
        if "chunk_overlap" not in cols:
            sync_conn.execute(
                text(
                    "ALTER TABLE kbs ADD COLUMN chunk_overlap "
                    "INTEGER NOT NULL DEFAULT 150"
                )
            )
        if "kg_enabled" not in cols:
            sync_conn.execute(
                text(
                    "ALTER TABLE kbs ADD COLUMN kg_enabled "
                    "BOOLEAN NOT NULL DEFAULT FALSE"
                )
            )

    # v4: documents parsed_text + chunk overrides
    if "documents" in tables:
        doc_cols = {c["name"] for c in insp.get_columns("documents")}
        if "parsed_text" not in doc_cols:
            sync_conn.execute(
                text("ALTER TABLE documents ADD COLUMN parsed_text TEXT NOT NULL DEFAULT ''")
            )
        for col_name, col_type in [
            ("chunk_strategy", "VARCHAR(32)"),
            ("chunk_target", "INTEGER"),
            ("chunk_max_size", "INTEGER"),
            ("chunk_overlap", "INTEGER"),
        ]:
            if col_name not in doc_cols:
                sync_conn.execute(
                    text(f"ALTER TABLE documents ADD COLUMN {col_name} {col_type}")
                )
        if "enabled" not in doc_cols:
            sync_conn.execute(
                text(
                    "ALTER TABLE documents ADD COLUMN enabled "
                    "BOOLEAN NOT NULL DEFAULT TRUE"
                )
            )
        for col_name, col_type, default in [
            ("kg_status", "VARCHAR(16)", "''"),
            ("kg_track_id", "VARCHAR(128)", "''"),
            ("kg_doc_id", "VARCHAR(128)", "''"),
            ("kg_error", "TEXT", "''"),
        ]:
            if col_name not in doc_cols:
                sync_conn.execute(
                    text(
                        f"ALTER TABLE documents ADD COLUMN {col_name} "
                        f"{col_type} NOT NULL DEFAULT {default}"
                    )
                )

    # v2-M1: users.{llm,embedding}_* (10 nullable columns; NULL = use env fallback)
    if "users" in tables:
        cols = {c["name"] for c in insp.get_columns("users")}
        new_cols = [
            ("llm_provider", "VARCHAR(32)"),
            ("llm_base_url", "VARCHAR(255)"),
            ("llm_api_key_enc", "VARCHAR(1024)"),
            ("llm_default_model", "VARCHAR(128)"),
            ("llm_complex_model", "VARCHAR(128)"),
            ("llm_context_window", "INTEGER"),
            ("embedding_provider", "VARCHAR(32)"),
            ("embedding_base_url", "VARCHAR(255)"),
            ("embedding_api_key_enc", "VARCHAR(1024)"),
            ("embedding_model", "VARCHAR(128)"),
            ("embedding_dim", "INTEGER"),
            # v3-M4: per-user cross-encoder reranker (opt-in, default off).
            ("reranker_provider", "VARCHAR(32)"),
            ("reranker_base_url", "VARCHAR(255)"),
            ("reranker_api_key_enc", "VARCHAR(1024)"),
            ("reranker_model", "VARCHAR(128)"),
        ]
        for col_name, col_type in new_cols:
            if col_name not in cols:
                sync_conn.execute(
                    text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
                )

        # v2-M6: users.kb_web_search_enabled (bool, default 0)
        if "kb_web_search_enabled" not in cols:
            sync_conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN kb_web_search_enabled "
                    "BOOLEAN NOT NULL DEFAULT 0"
                )
            )

        # v3-M4: users.reranker_enabled (bool, default 0) — gates whether the
        # configured reranker is actually consulted at chat time.
        if "reranker_enabled" not in cols:
            sync_conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN reranker_enabled "
                    "BOOLEAN NOT NULL DEFAULT 0"
                )
            )

        # 06-01 admin-dashboard: users.is_admin + users.is_active.
        # IMPORTANT — use DEFAULT FALSE / TRUE, NOT 0 / 1. Production runs
        # PostgreSQL (docker-compose: postgresql+asyncpg), whose BOOLEAN columns
        # reject an integer default ("column is boolean but default is integer").
        # The older `DEFAULT 0` ALTERs above only ever ran against SQLite dev DBs
        # — on prod those columns were born via create_all, so their ALTER branch
        # never executed on Postgres. These two are added to an ALREADY-EXISTING
        # prod users table, so their ALTER WILL run on Postgres and the DDL must
        # be portable. FALSE/TRUE work on both PostgreSQL and SQLite >= 3.23
        # (the SQLite bundled with supported Python is far newer).
        if "is_admin" not in cols:
            sync_conn.execute(
                text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE")
            )
        if "is_active" not in cols:
            sync_conn.execute(
                text("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE")
            )

    # v3-M6: conversations.llm_model (nullable VARCHAR) — per-conversation
    # LLM model override; NULL means fall back to the user's default model.
    if "conversations" in tables:
        conv_cols = {c["name"] for c in insp.get_columns("conversations")}
        if "llm_model" not in conv_cols:
            sync_conn.execute(
                text("ALTER TABLE conversations ADD COLUMN llm_model VARCHAR(128)")
            )
        if "finalized_at" not in conv_cols:
            sync_conn.execute(
                text("ALTER TABLE conversations ADD COLUMN finalized_at TIMESTAMP")
            )

    # Stop generation is a client-side cancellation state, not a model error
    # worth preserving on completed/partial assistant messages.
    if "messages" in tables:
        sync_conn.execute(
            text("UPDATE messages SET error = NULL WHERE error = :stopped"),
            {"stopped": _STOPPED_GENERATION_MESSAGE},
        )

    # 2026-07: DeepSeek retired `deepseek-chat`. Migrate all persisted model
    # selections on every startup so existing users and conversations do not
    # send the retired identifier. These UPDATEs are idempotent and portable
    # across the supported SQLite and PostgreSQL deployments.
    if "users" in tables:
        sync_conn.execute(
            text(
                "UPDATE users SET llm_default_model = :new_model "
                "WHERE llm_default_model = :old_model"
            ),
            {"new_model": _DEEPSEEK_V4_FLASH, "old_model": _LEGACY_DEEPSEEK_CHAT},
        )
        sync_conn.execute(
            text(
                "UPDATE users SET llm_complex_model = :new_model "
                "WHERE llm_complex_model = :old_model"
            ),
            {"new_model": _DEEPSEEK_V4_FLASH, "old_model": _LEGACY_DEEPSEEK_CHAT},
        )
    if "conversations" in tables:
        sync_conn.execute(
            text(
                "UPDATE conversations SET llm_model = :new_model "
                "WHERE llm_model = :old_model"
            ),
            {"new_model": _DEEPSEEK_V4_FLASH, "old_model": _LEGACY_DEEPSEEK_CHAT},
        )

    # v4: structured long-term memory. Existing explicit memories remain
    # readable; the nullable key/value fields are populated only by new writes.
    if "user_memories" in tables:
        memory_cols = {c["name"] for c in insp.get_columns("user_memories")}
        memory_new_cols = [
            ("scope_id", "VARCHAR(36)"),
            ("memory_key", "VARCHAR(128)"),
            ("memory_value", "TEXT"),
            ("source", "VARCHAR(32) NOT NULL DEFAULT 'explicit'"),
            ("importance", "FLOAT NOT NULL DEFAULT 0.5"),
            ("expires_at", "TIMESTAMP"),
            ("supersedes_memory_id", "VARCHAR(36)"),
            ("embedding_json", "TEXT"),
            ("embedding_fingerprint", "VARCHAR(64)"),
        ]
        for col_name, col_type in memory_new_cols:
            if col_name not in memory_cols:
                sync_conn.execute(
                    text(f"ALTER TABLE user_memories ADD COLUMN {col_name} {col_type}")
                )
        # ``create_all`` adds model indexes only for fresh databases. Ensure
        # existing installations also get the lookup indexes used by memory
        # retrieval and scope filtering.
        sync_conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_user_memories_retrieval "
                "ON user_memories (user_id, status, expires_at, updated_at)"
            )
        )
        sync_conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_user_memories_embedding_lookup "
                "ON user_memories (user_id, status, embedding_fingerprint)"
            )
        )
        sync_conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_user_memories_scope_lookup "
                "ON user_memories (scope, scope_id, memory_key)"
            )
        )
