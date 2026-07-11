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
    text = "段落一。\n\n段落二内容稍长一些。\n\n段落三。"
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
