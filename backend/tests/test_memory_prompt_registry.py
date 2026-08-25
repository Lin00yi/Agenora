"""Memory extraction Prompt guidance never replaces persistence safeguards."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.capabilities.conversations.models import Conversation, Message
from src.capabilities.memory.application import lifecycle
from src.capabilities.memory.domain import extraction
from src.harness.prompts.registry import PromptResolution
from src.harness.prompts.system import PROMPT_KEY_MEMORY_EXTRACTION
from src.platform.persistence.database import Base


@pytest.mark.asyncio
async def test_memory_extractor_appends_fixed_privacy_guard_to_registered_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeMessage:
        content = (
            '[{"type":"preference","key":"response_language","value":"zh-CN",'
            '"content":"User prefers Chinese responses.","confidence":0.9,'
            '"importance":0.9,"scope":"personal","evidence_message_ids":["m-1"]}]'
        )

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]
        usage = None

    class FakeCompletions:
        async def create(self, **kwargs: object) -> FakeResponse:
            captured.update(kwargs)
            return FakeResponse()

    class FakeClient:
        chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("src.platform.llm.gateway.get_client", lambda _cfg: FakeClient())
    monkeypatch.setattr("src.platform.llm.gateway.pick_model", lambda *_args, **_kwargs: "test-model")

    candidates = await extraction.extract_conversation_memory_candidates_with_llm(
        [SimpleNamespace(id="m-1", role="user", content="以后请用中文回复")],
        llm_cfg=SimpleNamespace(provider="openai-compat"),
        system_prompt_template="CUSTOM MEMORY GUIDANCE",
        extractor_version="memory-v3:registry:v6",
    )

    messages = captured["messages"]
    assert isinstance(messages, list)
    system = messages[0]["content"]
    assert "Do not store passwords" in system
    assert system.endswith("CUSTOM MEMORY GUIDANCE")
    assert len(candidates) == 1
    assert candidates[0].extractor_version == "memory-v3:registry:v6"


@pytest.mark.asyncio
async def test_memory_lifecycle_passes_the_published_template_to_llm_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    captured: dict[str, object] = {}

    async def published_prompts(_session: object) -> dict[str, PromptResolution]:
        return {
            PROMPT_KEY_MEMORY_EXTRACTION: PromptResolution(
                content="PUBLISHED MEMORY GUIDANCE",
                key=PROMPT_KEY_MEMORY_EXTRACTION,
                version=6,
                digest="digest-6",
                source="registry",
            )
        }

    async def fake_extract(_messages: object, **kwargs: object) -> list[object]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(lifecycle, "resolve_published_prompts", published_prompts)
    monkeypatch.setattr(lifecycle, "extract_conversation_memory_candidates_with_llm", fake_extract)

    async with factory() as session:
        session.add_all(
            (
                Conversation(id="c-1", user_id="u-1"),
                Message(id="m-1", conversation_id="c-1", role="user", content="我们继续讨论项目"),
            )
        )
        await session.commit()
        result = await lifecycle.extract_conversation_memories(
            session,
            conversation_id="c-1",
            user_id="u-1",
        )

    assert result["llm_candidates"] == 0
    assert captured["system_prompt_template"] == "PUBLISHED MEMORY GUIDANCE"
    assert captured["extractor_version"] == "memory-v3:registry:v6"
    await engine.dispose()
