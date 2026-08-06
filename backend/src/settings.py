"""Centralized settings via pydantic-settings.

Env file resolution is decoupled from CWD and keyed by APP_ENV:
  - development -> backend/.env.development
  - staging     -> backend/.env.staging
  - production  -> backend/.env.production

If the mapped file is missing, we fall back to `backend/.env` for backward
compatibility.

Default DB / vector / upload paths are also anchored to `backend/`, so the app
keeps finding its data files even when systemd / Docker launches it with an
unrelated WorkingDirectory.
"""
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/src/settings.py → backend/.env.<env>
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_NAME = os.getenv("APP_ENV", "development").strip().lower()
_ENV_NAME_MAP = {
    "dev": "development",
    "development": "development",
    "staging": "staging",
    "prod": "production",
    "production": "production",
}
_ENV_SUFFIX = _ENV_NAME_MAP.get(_ENV_NAME, "development")
_ENV_FILE = _BACKEND_DIR / f".env.{_ENV_SUFFIX}"
if not _ENV_FILE.exists():
    _ENV_FILE = _BACKEND_DIR / ".env"
_DATA_DIR = _BACKEND_DIR / "data"

# SQLAlchemy URLs use POSIX-style slashes; absolute path renders as
# `sqlite+aiosqlite:///C:/.../app.db` on Windows and
# `sqlite+aiosqlite:////.../app.db` on Linux (note the 4 leading slashes).
_DEFAULT_DB_URL = f"sqlite+aiosqlite:///{(_DATA_DIR / 'app.db').as_posix()}"
_DEFAULT_LOCAL_VECTOR_DB = str(_DATA_DIR / "local_vector.db")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ===== LLM =====
    llm_provider: str = "anthropic"  # anthropic | deepseek
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    llm_default_model: str = "claude-haiku-4-5-20251001"
    llm_complex_model: str = "claude-sonnet-4-6"

    # ===== KB query policy =====
    # always_direct: skip policy/rewrite, search the original user query.
    # rule_only: use deterministic rules only; uncertain cases fall back direct.
    # llm_fallback: deterministic rules first, LLM policy+rewrite for uncertain/complex cases.
    # always_llm: use LLM policy+rewrite for every non-empty KB-bound query.
    kb_query_policy_mode: str = "llm_fallback"
    kb_query_policy_max_queries: int = 3
    kb_query_policy_llm_model: str = ""

    # ===== Tools =====
    qweather_api_key: str = ""
    amap_api_key: str = ""
    web_search_provider: str = "duckduckgo"  # duckduckgo | brave | bing | tavily
    brave_search_api_key: str = ""
    bing_search_api_key: str = ""
    tavily_api_key: str = ""

    # ===== Vector store (decoupled: factory picks impl by VECTOR_STORE) =====
    vector_store: str = "qdrant"  # qdrant | milvus | local

    # Qdrant — same env vars cover local, self-hosted-server, and Qdrant Cloud
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "restaurants"

    # Milvus — Milvus Lite (本地 .db 文件，pure-Python embedded engine)
    # 或 Standalone / Zilliz Cloud (http://host:19530，需配 milvus_token)
    milvus_uri: str = str(_DATA_DIR / "milvus_local.db")
    milvus_token: str = ""

    # Local SQLite store (offline / no-network fallback) — absolute path anchored
    # to backend/ so it works under systemd / Docker / non-default CWD.
    local_vector_db_path: str = _DEFAULT_LOCAL_VECTOR_DB

    # ===== Embedding (OpenAI-compatible by default) =====
    # Provider preset: openai | siliconflow | ollama | hashmock
    # Preset only fills defaults — explicit URL/API_KEY/MODEL always wins.
    embedding_provider: str = "openai"

    # Explicit overrides (any of these wins over preset)
    embedding_base_url: str = ""      # e.g. https://api.siliconflow.cn/v1
    embedding_api_key: str = ""       # provider-specific key
    embedding_model: str = ""         # e.g. BAAI/bge-m3
    embedding_vector_size: int = 0    # 0 = look up from MODEL_DIMS table, then probe

    # Legacy / fallback fields
    openai_api_key: str = ""
    ollama_url: str = "http://localhost:11434"
    ollama_embed_model: str = "bge-m3"

    # ===== App database (users / KBs / etc., SQLite by default) =====
    # Absolute path anchored to backend/ — survives systemd / Docker WorkingDirectory.
    database_url: str = _DEFAULT_DB_URL

    # ===== Auth (M1) =====
    jwt_secret: str = "dev-only-change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days
    auth_enabled: bool = True  # set False to skip auth (dev/demo)

    # Admin allowlist (06-01 admin-dashboard): comma-separated emails promoted to
    # is_admin=True on startup (seed_admins). Lets the operator bootstrap the
    # first admin without a manual DB edit — add the email and restart. Only
    # marks already-registered users; unknown emails are re-checked next boot.
    admin_emails: str = ""

    # ===== BYOK gate (v2-M2, 2026-05-15) =====
    # When True, every user MUST configure their own LLM (and embedding for KB
    # operations) in /settings before chat / create_kb / upload work. Default
    # False keeps env fallback for dev / first-run convenience. Flip to True
    # for any public deployment to stop sharing the owner's API keys.
    byok_required: bool = False

    # ===== Observability (internal Trace DB + Langfuse) =====
    # Internal span trees persist to the app DB when True (default on).
    trace_enabled: bool = True
    # Store truncated input/output previews on traces/observations.
    trace_store_io: bool = True
    # External Langfuse export. Switch defaults on; without keys it no-ops.
    langfuse_enabled: bool = True
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_sample_rate: float = 1.0

    # ===== Server =====
    app_env: str = "dev"
    log_level: str = "INFO"
    rate_limit_per_hour: int = 20
    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
