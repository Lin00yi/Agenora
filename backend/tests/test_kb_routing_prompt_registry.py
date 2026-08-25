"""Published knowledge-base routing prompts stay inside code-owned bounds."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.capabilities.knowledge.application import routing


@pytest.mark.asyncio
async def test_llm_router_receives_registered_prompt_but_only_selects_catalog_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeMessage:
        content = '{"needs_retrieval":true,"selected_kb_ids":["kb-1","outside"],"confidence":"high","reason":"internal_docs"}'

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

    monkeypatch.setattr(
        "src.settings.get_settings",
        lambda: SimpleNamespace(kb_auto_route_mode="always_llm"),
    )
    monkeypatch.setattr(routing, "get_client", lambda _cfg: FakeClient())
    monkeypatch.setattr(routing, "pick_model", lambda *_args, **_kwargs: "test-model")

    route = await routing.resolve_auto_kb_route_from_candidates(
        messages=[{"role": "user", "content": "查内部项目方案"}],
        candidates=[SimpleNamespace(id="kb-1", name="项目资料", description="trusted candidate")],
        llm_cfg=SimpleNamespace(provider="openai-compat"),
        system_prompt="CUSTOM ROUTER POLICY\n",
        prompt_metadata={"key": "knowledge_base_routing", "version": 4, "digest": "abc", "source": "registry"},
    )

    messages = captured["messages"]
    assert isinstance(messages, list)
    system = messages[0]["content"]
    assert system.startswith("CUSTOM ROUTER POLICY")
    assert '<kb_catalog untrusted="true">' in system
    assert route.selected_kb_ids == ["kb-1"]
    assert route.prompt_registry == {
        "key": "knowledge_base_routing",
        "version": 4,
        "digest": "abc",
        "source": "registry",
    }
