from __future__ import annotations

from types import SimpleNamespace
import uuid

import pytest

from src.kb.models import KB
from src.settings_user.models import UserLLMConfig


def _llm_cfg() -> UserLLMConfig:
    return UserLLMConfig(
        provider="openai-compat",
        base_url="http://llm.test/v1",
        api_key="test",
        default_model="deepseek-v4-flash",
        complex_model="deepseek-v4-pro",
        context_window=1_000_000,
    )


def _kb(kb_id: str, name: str) -> KB:
    return KB(
        id=kb_id,
        user_id="user-1",
        name=name,
        description="内部资料",
        chunks_count=12,
    )


def _set_route_mode(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    from src.settings import get_settings

    monkeypatch.setenv("KB_AUTO_ROUTE_MODE", value)
    get_settings.cache_clear()


def _candidate_loader(*candidates: KB):
    async def _load(*_args, **_kwargs) -> list[KB]:
        return list(candidates)

    return _load


@pytest.mark.asyncio
async def test_auto_route_skips_obvious_general_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.kb import auto_routing

    _set_route_mode(monkeypatch, "llm_fallback")
    monkeypatch.setattr(auto_routing, "list_readable_routable_kbs", _candidate_loader(_kb("kb-1", "员工手册")))
    monkeypatch.setattr(auto_routing, "get_client", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM must not run")))

    decision = await auto_routing.resolve_auto_kb_route(
        SimpleNamespace(),
        user_id="user-1",
        messages=[{"role": "user", "content": "你好"}],
        llm_cfg=_llm_cfg(),
    )

    assert decision.kb is None
    assert decision.needs_retrieval is False
    assert decision.reason == "obvious_general_intent"


@pytest.mark.asyncio
async def test_auto_route_uses_explicit_kb_name_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.kb import auto_routing

    handbook = _kb("kb-1", "员工手册")
    _set_route_mode(monkeypatch, "llm_fallback")
    monkeypatch.setattr(auto_routing, "list_readable_routable_kbs", _candidate_loader(handbook))
    monkeypatch.setattr(auto_routing, "get_client", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM must not run")))

    decision = await auto_routing.resolve_auto_kb_route(
        SimpleNamespace(),
        user_id="user-1",
        messages=[{"role": "user", "content": "员工手册里的年假规则是什么？"}],
        llm_cfg=_llm_cfg(),
    )

    assert decision.selected_kb_id == handbook.id
    assert decision.source == "rule"
    assert decision.reason == "kb_name_mentioned"


@pytest.mark.asyncio
async def test_auto_route_accepts_only_a_readable_llm_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.kb import auto_routing

    product = _kb("kb-product", "产品资料")
    policy = _kb("kb-policy", "员工制度")
    _set_route_mode(monkeypatch, "always_llm")
    monkeypatch.setattr(auto_routing, "list_readable_routable_kbs", _candidate_loader(product, policy))

    class FakeCompletions:
        async def create(self, **_kwargs):
            return SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"needs_retrieval":true,"selected_kb_id":"kb-policy","confidence":"high","reason":"policy_question"}'
                        )
                    )
                ],
            )

    monkeypatch.setattr(
        auto_routing,
        "get_client",
        lambda *_args, **_kwargs: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )
    decision = await auto_routing.resolve_auto_kb_route(
        SimpleNamespace(),
        user_id="user-1",
        messages=[{"role": "user", "content": "我的年假如何计算？"}],
        llm_cfg=_llm_cfg(),
    )

    assert decision.selected_kb_id == policy.id
    assert decision.needs_retrieval is True
    assert decision.source == "llm"


@pytest.mark.asyncio
async def test_auto_route_rejects_llm_kb_outside_permission_scoped_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.kb import auto_routing

    _set_route_mode(monkeypatch, "always_llm")
    monkeypatch.setattr(auto_routing, "list_readable_routable_kbs", _candidate_loader(_kb("kb-safe", "允许访问")))

    class FakeCompletions:
        async def create(self, **_kwargs):
            return SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"needs_retrieval":true,"selected_kb_id":"kb-forbidden","confidence":"high","reason":"bad_id"}'
                        )
                    )
                ],
            )

    monkeypatch.setattr(
        auto_routing,
        "get_client",
        lambda *_args, **_kwargs: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )
    decision = await auto_routing.resolve_auto_kb_route(
        SimpleNamespace(),
        user_id="user-1",
        messages=[{"role": "user", "content": "内部规定是什么？"}],
        llm_cfg=_llm_cfg(),
    )

    assert decision.kb is None
    assert decision.needs_retrieval is False
    assert decision.reason == "no_confident_kb_match"


@pytest.mark.asyncio
async def test_routable_catalog_includes_only_readable_kbs(db, create_user) -> None:
    from src.kb.auto_routing import list_readable_routable_kbs
    from src.kb.models import KBMember
    from src.storage.database import get_session_factory

    owner = await create_user("route-owner@example.com")
    member = await create_user("route-member@example.com")
    outsider = await create_user("route-outsider@example.com")
    factory = get_session_factory()
    async with factory() as session:
        own = KB(
            id=str(uuid.uuid4()),
            user_id=member.id,
            name="我的资料",
            chunks_count=4,
        )
        shared = KB(
            id=str(uuid.uuid4()),
            user_id=owner.id,
            name="共享资料",
            chunks_count=4,
        )
        private = KB(
            id=str(uuid.uuid4()),
            user_id=outsider.id,
            name="不可见资料",
            chunks_count=4,
        )
        empty = KB(
            id=str(uuid.uuid4()),
            user_id=member.id,
            name="空知识库",
            chunks_count=0,
        )
        session.add_all([own, shared, private, empty])
        session.add(KBMember(kb_id=shared.id, user_id=member.id, role="viewer"))
        await session.commit()

        candidates = await list_readable_routable_kbs(session, user_id=member.id, limit=8)

    assert {kb.id for kb in candidates} == {own.id, shared.id}


@pytest.mark.asyncio
async def test_chat_prepares_acl_scoped_candidates_for_supervisor(db, create_user, monkeypatch) -> None:
    from src.api.routes import chat as chat_routes
    from src.api.schemas.chat import ChatRequest
    from src.conversations.models import Conversation
    from src.infra import generation_lock
    from src.storage.database import get_session_factory

    user = await create_user("auto-route-chat@example.com")
    kb = KB(
        id=str(uuid.uuid4()),
        user_id="00000000-0000-0000-0000-000000000000",
        name="系统知识库",
        is_system=True,
        chunks_count=2,
    )
    conv = Conversation(id=str(uuid.uuid4()), user_id=user.id, title="新对话")
    factory = get_session_factory()
    async with factory() as session:
        session.add_all([kb, conv])
        await session.commit()

        async def fake_candidates(*_args, **_kwargs) -> list[KB]:
            return [kb]

        async def fake_context(*_args, **_kwargs):
            return SimpleNamespace(messages=[{"role": "user", "content": "系统资料"}], memory_trace=None)

        captured: dict[str, object] = {}

        def fake_session_runner(*_args, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace()

        monkeypatch.setattr(chat_routes, "list_readable_routable_kbs", fake_candidates)
        monkeypatch.setattr(chat_routes, "build_context_for_conversation", fake_context)
        monkeypatch.setattr(chat_routes, "run_chat_session", fake_session_runner)

        await chat_routes.chat_post(ChatRequest(conversation_id=conv.id), user, session)
        await session.refresh(conv)
        await generation_lock.release(conv.id)

    assert conv.kb_id is None
    assert captured["kb"] is None
    assert [item.id for item in captured["kb_candidates"]] == [kb.id]
    assert callable(captured["on_kb_routed"])
