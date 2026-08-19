from __future__ import annotations

import json
import uuid

import pytest


def _auth(client, user):
    from src.auth.tokens import issue_token

    return {"Authorization": f"Bearer {issue_token(user.id, user.email)}"}


def _golden_line(case_id: str, query: str, doc_id: str) -> str:
    return json.dumps(
        {
            "id": case_id,
            "query": query,
            "expected_document_ids": [doc_id],
            "tags": ["test"],
        }
    )


@pytest.mark.asyncio
async def test_eval_config_crud_and_viewer_forbidden(client, create_user, create_kb, tmp_path, monkeypatch):
    from src.storage.database import get_session_factory
    from src.kb.models import KBMember

    monkeypatch.setattr("src.kb.eval_service.EVAL_RUNS_BASE", tmp_path / "eval_runs")

    owner = await create_user("eval-owner@example.test")
    viewer = await create_user("eval-viewer@example.test")
    kb = await create_kb(owner.id, name="Eval KB")
    factory = get_session_factory()
    async with factory() as session:
        session.add(KBMember(kb_id=kb.id, user_id=viewer.id, role="viewer"))
        await session.commit()

    golden = _golden_line("case-a", "hello", "doc-a") + "\n"
    gate = json.dumps({"k": 3, "minimums": {"recall_at_k": 0.5, "mrr": 0.5, "ndcg_at_k": 0.5}})
    put = await client.put(
        f"/api/kbs/{kb.id}/eval/config",
        headers=_auth(client, owner),
        json={"golden_set_jsonl": golden, "gate_json": gate},
    )
    assert put.status_code == 200, put.text
    assert put.json()["configured"] is True
    assert put.json()["case_count"] == 1
    assert put.json()["k"] == 3

    forbidden = await client.put(
        f"/api/kbs/{kb.id}/eval/config",
        headers=_auth(client, viewer),
        json={"golden_set_jsonl": golden},
    )
    assert forbidden.status_code == 403

    got = await client.get(f"/api/kbs/{kb.id}/eval/config", headers=_auth(client, owner))
    assert got.status_code == 200
    assert got.json()["cases"][0]["id"] == "case-a"

    viewer_get = await client.get(f"/api/kbs/{kb.id}/eval/config", headers=_auth(client, viewer))
    assert viewer_get.status_code == 403


@pytest.mark.asyncio
async def test_eval_regression_replay_and_missing_cases(client, create_user, create_kb, monkeypatch, tmp_path):
    from src.tools.base import ToolResult
    from src.tools.kb_search import KBSearchTool

    monkeypatch.setattr("src.kb.eval_service.EVAL_RUNS_BASE", tmp_path / "eval_runs")

    owner = await create_user("eval-run-owner@example.test")
    kb = await create_kb(owner.id, name="Eval Run KB")
    headers = _auth(client, owner)
    golden = "\n".join(
        [
            _golden_line("keep", "keep query", "document-1"),
            _golden_line("need-two", "second query", "document-2"),
        ]
    ) + "\n"
    await client.put(
        f"/api/kbs/{kb.id}/eval/config",
        headers=headers,
        json={
            "golden_set_jsonl": golden,
            "gate_json": json.dumps({"k": 3, "minimums": {"recall_at_k": 0.9}}),
        },
    )

    async def fake_execute(self, query: str, limit: int = 3):  # noqa: ARG001
        doc_id = "document-1" if "keep" in query else "document-x"
        return ToolResult(
            text="private",
            latency_ms=1,
            raw={
                "hits": 1,
                "kb_id": kb.id,
                "results": [{"doc_id": doc_id, "filename": "a.md", "score": 0.9}],
            },
        )

    monkeypatch.setattr(KBSearchTool, "execute", fake_execute)
    run = await client.post(f"/api/kbs/{kb.id}/eval/run", headers=headers)
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["run_type"] == "regression"
    assert body["gate_passed"] is False
    assert body["report"]["metrics"]["recall_at_k"] == pytest.approx(0.5)
    run_id = body["id"]

    listed = await client.get(f"/api/kbs/{kb.id}/eval/runs", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    replay = await client.post(f"/api/kbs/{kb.id}/eval/replay?run_id={run_id}", headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.json()["run_type"] == "replay"
    assert replay.json()["report"]["metrics"]["recall_at_k"] == pytest.approx(0.5)

    upload = await client.post(
        f"/api/kbs/{kb.id}/eval/replay",
        headers=headers,
        files={
            "retrieval_jsonl": (
                "retrieval.jsonl",
                json.dumps({"id": "keep", "retrieved": [{"document_id": "document-1"}]}) + "\n",
                "application/jsonl",
            )
        },
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["report"]["missing_prediction_ids"] == ["need-two"]


@pytest.mark.asyncio
async def test_eval_roogoo_template_import(client, create_user, create_kb):
    owner = await create_user("eval-template@example.test")
    kb = await create_kb(owner.id, name="Template KB")
    templates = await client.get(f"/api/kbs/{kb.id}/eval/templates", headers=_auth(client, owner))
    assert templates.status_code == 200
    ids = {item["id"] for item in templates.json()["templates"]}
    assert "roogoo" in ids

    imported = await client.put(
        f"/api/kbs/{kb.id}/eval/config",
        headers=_auth(client, owner),
        json={"template": "roogoo"},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["case_count"] >= 1
    assert imported.json()["configured"] is True


@pytest.mark.asyncio
async def test_eval_monitor_filters_by_kb_id(client, create_user, create_kb, db):
    from datetime import datetime, timezone

    from src.storage.database import get_session_factory
    from src.observability.models import Observation, Trace

    owner = await create_user("eval-monitor@example.test")
    kb = await create_kb(owner.id, name="Monitor KB")
    other = await create_kb(owner.id, name="Other KB")
    now = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        mine, theirs = uuid.uuid4().hex, uuid.uuid4().hex
        session.add_all([Trace(id=mine, name="chat", started_at=now), Trace(id=theirs, name="chat", started_at=now)])
        session.add_all(
            [
                Observation(
                    id=uuid.uuid4().hex,
                    trace_id=mine,
                    name="search_kb",
                    type="tool",
                    started_at=now,
                    duration_ms=40,
                    status="ok",
                    metadata_json=json.dumps({"rag": {"kb_id": kb.id, "result_count": 2, "max_score": 0.8}}),
                ),
                Observation(
                    id=uuid.uuid4().hex,
                    trace_id=theirs,
                    name="search_kb",
                    type="tool",
                    started_at=now,
                    duration_ms=900,
                    status="error",
                    metadata_json=json.dumps({"rag": {"kb_id": other.id, "result_count": 0, "max_score": 0.1}}),
                ),
            ]
        )
        await session.commit()

    snapshot = await client.get(
        f"/api/kbs/{kb.id}/eval/monitor?hours=24",
        headers=_auth(client, owner),
    )
    assert snapshot.status_code == 200, snapshot.text
    metrics = snapshot.json()["metrics"]
    assert metrics["retrieval_calls"] == 1
    assert metrics["error_rate"] == pytest.approx(0.0)
    assert metrics["empty_rate"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_eval_run_requires_config(client, create_user, create_kb):
    owner = await create_user("eval-empty@example.test")
    kb = await create_kb(owner.id, name="Empty Eval KB")
    response = await client.post(f"/api/kbs/{kb.id}/eval/run", headers=_auth(client, owner))
    assert response.status_code == 400
    assert "golden set" in response.json()["detail"]
