"""Tests for document + chunk management (v4)."""

from __future__ import annotations

import uuid

import pytest

from src.kb.chunk_service import chunk_document_text, resolve_chunk_params
from src.kb.models import Chunk, Document, KB


def test_resolve_chunk_params_kb_defaults():
    kb = KB(
        id="kb1",
        user_id="u1",
        name="t",
        chunk_target=1200,
        chunk_max_size=1500,
        chunk_overlap=100,
    )
    target, max_size, overlap = resolve_chunk_params(kb)
    assert (target, max_size, overlap) == (1200, 1500, 100)


def test_resolve_chunk_params_document_override():
    kb = KB(id="kb1", user_id="u1", name="t")
    doc = Document(
        id="d1",
        kb_id="kb1",
        filename="a.md",
        chunk_target=800,
        chunk_max_size=1000,
        chunk_overlap=50,
    )
    target, max_size, overlap = resolve_chunk_params(kb, doc)
    assert (target, max_size, overlap) == (800, 1000, 50)


def test_chunk_document_text_respects_target():
    kb = KB(id="kb1", user_id="u1", name="t", chunk_target=50, chunk_max_size=80, chunk_overlap=10)
    doc = Document(id="d1", kb_id="kb1", filename="a.md")
    text = "段落一内容足够长以便触发分块。" * 3 + "\n\n" + "段落二内容也足够长以便触发分块。" * 3 + "\n\n" + "段落三。"
    chunks = chunk_document_text(kb, doc, text)
    assert len(chunks) >= 2
    assert all(len(c) <= 80 for c in chunks)


@pytest.mark.asyncio
async def test_get_document_and_list_chunks(client, create_user, create_kb, db):
    owner = await create_user("docmgr@x.com")
    kb = await create_kb(owner.id, name="DocMgr KB")

    from src.infra.database import get_session_factory

    doc_id = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as session:
        doc = Document(
            id=doc_id,
            kb_id=kb.id,
            filename="note.md",
            mime="text/markdown",
            size_bytes=100,
            source_type="file",
            status="done",
            chunks_count=2,
            parsed_text="hello world chunk test",
        )
        session.add(doc)
        session.add(
            Chunk(
                id=str(uuid.uuid4()),
                doc_id=doc_id,
                kb_id=kb.id,
                chunk_idx=0,
                text="hello",
                char_count=5,
            )
        )
        session.add(
            Chunk(
                id=str(uuid.uuid4()),
                doc_id=doc_id,
                kb_id=kb.id,
                chunk_idx=1,
                text="world",
                char_count=5,
            )
        )
        await session.commit()

    login = await client.post(
        "/api/auth/login",
        json={"email": "docmgr@x.com", "password": "password123"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r_doc = await client.get(f"/api/kbs/{kb.id}/documents/{doc_id}", headers=headers)
    assert r_doc.status_code == 200
    body = r_doc.json()
    assert body["filename"] == "note.md"
    assert body["parsed_text_length"] == len("hello world chunk test")

    r_chunks = await client.get(
        f"/api/kbs/{kb.id}/documents/{doc_id}/chunks?page=1&page_size=10",
        headers=headers,
    )
    assert r_chunks.status_code == 200
    data = r_chunks.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["chunk_idx"] == 0


@pytest.mark.asyncio
async def test_list_chunks_search_and_filter(client, create_user, create_kb, db):
    owner = await create_user("search@x.com")
    kb = await create_kb(owner.id, name="Search KB")

    from src.infra.database import get_session_factory

    doc_id = str(uuid.uuid4())
    c1 = str(uuid.uuid4())
    c2 = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Document(
                id=doc_id,
                kb_id=kb.id,
                filename="search.md",
                status="done",
                chunks_count=2,
            )
        )
        session.add(
            Chunk(
                id=c1,
                doc_id=doc_id,
                kb_id=kb.id,
                chunk_idx=0,
                text="alpha content",
                char_count=13,
                enabled=True,
            )
        )
        session.add(
            Chunk(
                id=c2,
                doc_id=doc_id,
                kb_id=kb.id,
                chunk_idx=1,
                text="beta disabled",
                char_count=13,
                enabled=False,
            )
        )
        await session.commit()

    login = await client.post(
        "/api/auth/login",
        json={"email": "search@x.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    base = f"/api/kbs/{kb.id}/documents/{doc_id}/chunks"

    r_q = await client.get(f"{base}?q=alpha", headers=headers)
    assert r_q.status_code == 200
    assert r_q.json()["total"] == 1
    assert "alpha" in r_q.json()["items"][0]["text"]

    r_disabled = await client.get(f"{base}?enabled=false", headers=headers)
    assert r_disabled.status_code == 200
    assert r_disabled.json()["total"] == 1
    assert r_disabled.json()["items"][0]["enabled"] is False


@pytest.mark.asyncio
async def test_batch_patch_chunks_enabled(client, create_user, create_kb, db):
    owner = await create_user("batch@x.com")
    kb = await create_kb(owner.id)

    from src.infra.database import get_session_factory

    doc_id = str(uuid.uuid4())
    c1 = str(uuid.uuid4())
    c2 = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Document(
                id=doc_id,
                kb_id=kb.id,
                filename="batch.md",
                status="done",
                chunks_count=2,
            )
        )
        session.add(
            Chunk(
                id=c1,
                doc_id=doc_id,
                kb_id=kb.id,
                chunk_idx=0,
                text="one",
                char_count=3,
                enabled=True,
            )
        )
        session.add(
            Chunk(
                id=c2,
                doc_id=doc_id,
                kb_id=kb.id,
                chunk_idx=1,
                text="two",
                char_count=3,
                enabled=True,
            )
        )
        await session.commit()

    login = await client.post(
        "/api/auth/login",
        json={"email": "batch@x.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    r = await client.patch(
        f"/api/kbs/{kb.id}/documents/{doc_id}/chunks/batch",
        headers=headers,
        json={"chunk_ids": [c1, c2], "enabled": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["updated"] == 2
    assert all(not item["enabled"] for item in body["items"])


@pytest.mark.asyncio
async def test_merge_chunks_requires_adjacency(client, create_user, create_kb):
    owner = await create_user("merge@x.com")
    kb = await create_kb(owner.id)

    from src.infra.database import get_session_factory

    doc_id = str(uuid.uuid4())
    c1 = str(uuid.uuid4())
    c2 = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Document(
                id=doc_id,
                kb_id=kb.id,
                filename="a.md",
                status="done",
                chunks_count=2,
            )
        )
        session.add(
            Chunk(
                id=c1,
                doc_id=doc_id,
                kb_id=kb.id,
                chunk_idx=0,
                text="aaa",
                char_count=3,
            )
        )
        session.add(
            Chunk(
                id=c2,
                doc_id=doc_id,
                kb_id=kb.id,
                chunk_idx=2,
                text="bbb",
                char_count=3,
            )
        )
        await session.commit()

    login = await client.post(
        "/api/auth/login",
        json={"email": "merge@x.com", "password": "password123"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post(
        f"/api/kbs/{kb.id}/documents/{doc_id}/chunks/merge",
        headers=headers,
        json={"chunk_ids": [c1, c2]},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_patch_document_enabled_without_embedding(client, create_user, create_kb, db):
    """Toggling doc.enabled should work in SQL even with 0 chunks / no embed cfg."""
    owner = await create_user("docen@x.com")
    kb = await create_kb(owner.id, name="DocEnable KB")

    from src.infra.database import get_session_factory

    doc_id = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Document(
                id=doc_id,
                kb_id=kb.id,
                filename="empty.md",
                status="done",
                chunks_count=0,
                enabled=True,
            )
        )
        await session.commit()

    login = await client.post(
        "/api/auth/login",
        json={"email": "docen@x.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    r = await client.patch(
        f"/api/kbs/{kb.id}/documents/{doc_id}",
        headers=headers,
        json={"enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False
