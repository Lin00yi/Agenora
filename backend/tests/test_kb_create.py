"""Regression coverage for knowledge-base creation failures."""

from __future__ import annotations

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_create_kb_rolls_back_when_vector_store_initialization_fails(
    client, create_user, db, monkeypatch
):
    """A missing optional vector dependency must not leave a KB row behind."""
    from src.infra.database import get_session_factory
    from src.kb.models import KB
    import src.kb.routes as kb_routes

    user = await create_user("kb-create-failure@example.com")
    login = await client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "password123"},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    async def fixed_vector_size(_config=None):
        return 8

    def missing_milvus_dependency():
        raise ModuleNotFoundError("No module named 'pymilvus'")

    monkeypatch.setattr(kb_routes, "_resolve_vector_size", fixed_vector_size)
    monkeypatch.setattr(kb_routes, "get_store", missing_milvus_dependency)

    response = await client.post(
        "/api/kbs",
        headers=headers,
        json={"name": "Should roll back", "description": ""},
    )

    assert response.status_code == 503
    assert "向量库初始化失败" in response.json()["detail"]

    factory = get_session_factory()
    async with factory() as session:
        names = (await session.scalars(select(KB.name).where(KB.user_id == user.id))).all()
    assert names == []
