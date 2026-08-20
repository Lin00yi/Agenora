"""Application-schema bootstrap owned by the composition layer."""
from __future__ import annotations

from src.platform.persistence.database import Base, _migrate_additive_columns, get_engine
from src.settings import get_settings


def _register_application_models() -> None:
    """Load product models before SQLAlchemy builds local development schemas."""
    from src.capabilities.conversations import models as _conversations_models  # noqa: F401
    from src.capabilities.identity import models as _identity_models  # noqa: F401
    from src.capabilities.knowledge.domain import models as _knowledge_models  # noqa: F401
    from src.capabilities.settings.domain import models as _settings_models  # noqa: F401
    from src.platform.observability import models as _observability_models  # noqa: F401


async def initialize_database() -> None:
    """Create disposable local/test schemas; production remains Alembic-owned."""
    settings = get_settings()
    if (
        not settings.schema_bootstrap
        or settings.app_env.strip().lower() in {"prod", "production"}
    ):
        return
    _register_application_models()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_additive_columns)
