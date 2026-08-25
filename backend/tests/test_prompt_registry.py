"""Prompt Registry persistence and runtime-resolution coverage."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.harness.prompts.registry import (
    fallback_resolution,
    get_template_detail,
    list_templates,
    publish_version,
    resolve_published_prompts,
    rollback_to_version,
    save_draft,
    validate_prompt_content,
)
from src.harness.prompts.system import PROMPT_KEY_GENERAL, PROMPT_KEY_KNOWLEDGE_BASE
from src.platform.persistence.database import Base


def test_prompt_validation_accepts_only_declared_variables() -> None:
    assert validate_prompt_content(PROMPT_KEY_KNOWLEDGE_BASE, "库：{{ kb_name }}") == "库：{{ kb_name }}"
    with pytest.raises(ValueError, match="不支持的变量"):
        validate_prompt_content(PROMPT_KEY_GENERAL, "{{kb_name}}")


@pytest.mark.asyncio
async def test_registry_publish_and_rollback_drive_runtime_resolution() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with factory() as session:
        templates = await list_templates(session)
        assert {item["key"] for item in templates} == {PROMPT_KEY_GENERAL, PROMPT_KEY_KNOWLEDGE_BASE}
        assert all(item["source"] == "code" for item in templates)

        first = await save_draft(
            session,
            key=PROMPT_KEY_GENERAL,
            content="你是第一个已发布版本。",
            admin_id="admin-1",
        )
        await publish_version(session, key=PROMPT_KEY_GENERAL, version=first["version"])
        second = await save_draft(
            session,
            key=PROMPT_KEY_GENERAL,
            content="你是第二个已发布版本。",
            admin_id="admin-1",
        )
        await publish_version(session, key=PROMPT_KEY_GENERAL, version=second["version"])

        current = await resolve_published_prompts(session)
        assert current[PROMPT_KEY_GENERAL].content == "你是第二个已发布版本。"
        assert current[PROMPT_KEY_GENERAL].version == 2
        assert current[PROMPT_KEY_GENERAL].source == "registry"

        rolled_back = await rollback_to_version(
            session,
            key=PROMPT_KEY_GENERAL,
            version=1,
            admin_id="admin-2",
        )
        assert rolled_back["version"] == 3
        assert rolled_back["status"] == "published"
        current = await resolve_published_prompts(session)
        assert current[PROMPT_KEY_GENERAL].content == "你是第一个已发布版本。"
        assert current[PROMPT_KEY_GENERAL].version == 3

        detail = await get_template_detail(session, PROMPT_KEY_GENERAL)
        assert detail["published_version"] == 3
        assert [item["status"] for item in detail["versions"]] == ["published", "archived", "archived"]

    assert fallback_resolution(PROMPT_KEY_GENERAL).source == "code"
    await engine.dispose()
