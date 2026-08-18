"""Regression coverage for account deletion across every owned data store."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select


def _bearer(user) -> dict[str, str]:
    from src.auth.tokens import issue_token

    return {"Authorization": f"Bearer {issue_token(user.id, user.email)}"}


@pytest.mark.asyncio
async def test_admin_user_delete_removes_owned_external_and_relational_data(
    client, create_user, create_kb, monkeypatch
):
    """A delete must not leave a vector collection, trace, memory, or BYOK key behind."""
    from src.conversations.models import Conversation, ConversationSummary, Message, UserMemory
    from src.infra.database import get_session_factory
    from src.kb.models import Document, IngestionJob, KBMember
    from src.observability.models import Observation, Trace
    from src.settings_user.models import LLMConnection, LLMModelProfile
    import src.kb.routes as kb_routes

    class RecordingStore:
        def __init__(self):
            self.deleted: list[str] = []

        async def delete_collection(self, collection_name: str) -> None:
            self.deleted.append(collection_name)

    store = RecordingStore()
    monkeypatch.setattr(kb_routes, "get_store", lambda: store)

    admin = await create_user("admin@purge.test", is_admin=True)
    target = await create_user("target@purge.test")
    other_owner = await create_user("owner@purge.test")
    owned_kb = await create_kb(target.id, "Owned KB")
    shared_kb = await create_kb(other_owner.id, "Shared KB")
    conversation_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())

    factory = get_session_factory()
    async with factory() as session:
        owned_doc = Document(
            id=str(uuid.uuid4()), kb_id=owned_kb.id, filename="waiting-for-ingest.md"
        )
        session.add_all(
            [
                owned_doc,
                Conversation(id=conversation_id, user_id=target.id, title="private"),
                Message(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    role="user",
                    content="private message",
                ),
                ConversationSummary(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    summary="private summary",
                ),
                UserMemory(
                    id=str(uuid.uuid4()), user_id=target.id, content="private memory"
                ),
                Trace(id=trace_id, user_id=target.id, name="chat", input_preview="secret"),
                Observation(
                    id=str(uuid.uuid4()), trace_id=trace_id, name="reason", type="generation"
                ),
                LLMConnection(
                    id=str(uuid.uuid4()),
                    user_id=target.id,
                    display_name="private connection",
                    provider="openai-compat",
                    base_url="https://api.example.com/v1",
                    api_key_enc="encrypted-key",
                ),
                LLMModelProfile(
                    id=str(uuid.uuid4()),
                    user_id=target.id,
                    display_name="private model",
                    model_id="example-model",
                ),
                KBMember(kb_id=shared_kb.id, user_id=target.id, role="viewer"),
            ]
        )
        # Explicit cleanup is still required even when a particular database
        # does not enforce foreign-key cascades (for example, SQLite without
        # PRAGMA foreign_keys=ON).
        session.add(
            IngestionJob(id=str(uuid.uuid4()), document_id=owned_doc.id, status="pending")
        )
        await session.commit()

    response = await client.delete(f"/api/admin/users/{target.id}", headers=_bearer(admin))
    assert response.status_code == 204
    assert store.deleted == [owned_kb.collection_name]

    async with factory() as session:
        tables = [
            Conversation,
            ConversationSummary,
            Message,
            UserMemory,
            Trace,
            Observation,
            LLMConnection,
            LLMModelProfile,
            IngestionJob,
        ]
        for model in tables:
            assert (await session.scalar(select(func.count()).select_from(model))) == 0
        assert (
            await session.scalar(
                select(func.count()).select_from(KBMember).where(KBMember.user_id == target.id)
            )
        ) == 0


@pytest.mark.asyncio
async def test_kb_purge_keeps_metadata_when_graph_cleanup_fails(db, create_user, create_kb, monkeypatch):
    """A strict external delete failure must leave identifiers available for retry."""
    from src.infra.database import get_session_factory
    from src.kb.models import Document, KB
    from src.kb.routes import purge_kb
    import src.kg.sync as kg_sync

    owner = await create_user("graph-owner@purge.test")
    kb = await create_kb(owner.id, "Graph KB")
    kb.kg_enabled = True
    doc_id = str(uuid.uuid4())

    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(KB, kb.id)
        assert row is not None
        row.kg_enabled = True
        session.add(
            Document(
                id=doc_id,
                kb_id=kb.id,
                filename="private.md",
                kg_doc_id="graph-document-id",
                kg_status="done",
            )
        )
        await session.commit()

        async def unavailable(**_kwargs):
            raise RuntimeError("LightRAG unavailable")

        monkeypatch.setattr(kg_sync, "delete_document_from_lightrag", unavailable)
        with pytest.raises(RuntimeError, match="LightRAG unavailable"):
            await purge_kb(session, row)

    async with factory() as session:
        retained_kb = await session.get(KB, kb.id)
        retained_doc = await session.get(Document, doc_id)
        assert retained_kb is not None
        assert retained_doc is not None
        assert retained_doc.kg_doc_id == "graph-document-id"
