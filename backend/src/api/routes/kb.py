"""KB + Document HTTP routes.

Authorization model:
  - All routes require a Bearer JWT (via CurrentUser).
  - v2-M9: per-KB role model. Each call resolves the caller's effective role
    via KB.role_for(session, user_id) which returns one of:
      - "owner": kbs.user_id == caller (full control)
      - "editor": (kb_id, caller) ∈ kb_members WHERE role="editor"
                  (read + upload/delete docs; CAN'T delete KB or manage members)
      - "viewer": system KB (anyone), or (kb_id, caller) ∈ kb_members WHERE role="viewer"
                  (read only)
      - None: no access → 404 (don't leak existence)

Lifecycle of an upload:
  POST /api/kbs/{id}/documents
    → 201 + Document(status="pending")
    → durable IngestionJob enqueued (BackgroundTask is only immediate handoff)
    → worker parses/chunks/embeds/upserts with bounded retry
    → Client polls GET /api/kbs/{id} (or /documents) for status transitions
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field, HttpUrl
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.capabilities.identity.middleware import CurrentUser
from src.capabilities.identity.models import User
from src.platform.persistence import get_session
from src.capabilities.knowledge.application import (
    configured_vector_size as get_vector_size,
    default_embedding_model,
    get_vector_store as get_store,
    probe_vector_dimension as probe_vector_size,
    enqueue_documents,
    chunks,
    documents,
    evaluation,
    handoff_ingestion,
    members,
)
from src.capabilities.knowledge.application.lifecycle import purge_kb
from src.capabilities.knowledge.domain.models import (
    KB,
    Chunk,
    ChunkStrategy,
    Document,
    IngestionJob,
    KBMember,
    KbEvalRun,
)
from src.platform.files.parsers import SUPPORTED_EXTS
from src.capabilities.settings.application.gate import require_user_embedding
from src.capabilities.settings.domain.models import resolve_user_embedding
from src.capabilities.knowledge.application.configuration import resolve_kb_embedding

router = APIRouter(prefix="/api/kbs", tags=["kbs"])


# Max single-upload size: 50 MB. Bigger files should be split or moved to a
# dedicated worker (out of scope for v1).
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class CreateKBRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)

    # v3-M7: optional per-KB embedding override. When provided, the KB persists
    # these creds and ingest / search use them; NULL on all = fall back to
    # user-level cfg.
    embedding_provider: Optional[Literal["openai-compat", "ollama"]] = None
    embedding_base_url: Optional[str] = Field(default=None, max_length=255)
    embedding_api_key: str = Field(default="", max_length=512)
    embedding_model: Optional[str] = Field(default=None, max_length=128)
    # Optional dim hint when caller already probed it; server still validates.
    embedding_dim: Optional[int] = Field(default=None, ge=1, le=8192)

    # v3-M7: optional per-KB reranker override. opt-in (default off). When
    # reranker_enabled=True AND the four cfg fields populated, KBSearchTool
    # reranks search hits for this KB.
    reranker_provider: Optional[Literal["siliconflow", "cohere", "openai-compat"]] = None
    reranker_base_url: Optional[str] = Field(default=None, max_length=255)
    reranker_api_key: str = Field(default="", max_length=512)
    reranker_model: Optional[str] = Field(default=None, max_length=128)
    reranker_enabled: bool = False
    chunk_strategy: ChunkStrategy = "recursive"


class PatchKBRequest(BaseModel):
    """Owner-only PATCH for retrieval toggles and chunk defaults."""

    grouping_enabled: Optional[bool] = None
    kg_enabled: Optional[bool] = None
    chunk_strategy: Optional[ChunkStrategy] = None
    chunk_target: Optional[int] = Field(default=None, ge=200, le=8000)
    chunk_max_size: Optional[int] = Field(default=None, ge=200, le=10000)
    chunk_overlap: Optional[int] = Field(default=None, ge=0, le=2000)


class PatchDocumentRequest(BaseModel):
    filename: Optional[str] = Field(default=None, min_length=1, max_length=255)
    chunk_strategy: Optional[ChunkStrategy] = None
    chunk_target: Optional[int] = Field(default=None, ge=200, le=8000)
    chunk_max_size: Optional[int] = Field(default=None, ge=200, le=10000)
    chunk_overlap: Optional[int] = Field(default=None, ge=0, le=2000)
    enabled: Optional[bool] = None


class PatchChunkRequest(BaseModel):
    text: Optional[str] = Field(default=None, min_length=1, max_length=65535)
    enabled: Optional[bool] = None


class SplitChunkRequest(BaseModel):
    offset: int = Field(ge=1)


class MergeChunksRequest(BaseModel):
    chunk_ids: list[str] = Field(min_length=2, max_length=2)


class BatchPatchChunksRequest(BaseModel):
    chunk_ids: list[str] = Field(min_length=1, max_length=100)
    enabled: bool


class BatchAllChunksRequest(BaseModel):
    enabled: bool


class CreateURLDocRequest(BaseModel):
    url: HttpUrl
    filename: str = Field(default="", max_length=255)  # optional display label


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(editor|viewer)$")


class PatchMemberRequest(BaseModel):
    role: str = Field(pattern="^(editor|viewer)$")


class PutEvalConfigRequest(BaseModel):
    golden_set_jsonl: Optional[str] = Field(default=None, max_length=2_000_000)
    gate_json: Optional[str] = Field(default=None, max_length=100_000)
    template: Optional[Literal["roogoo"]] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _resolve_role(
    session: AsyncSession, kb_id: str, user_id: str
) -> tuple[KB, str]:
    """Load KB + compute caller's effective role. Returns (kb, role).

    Raises 404 if KB doesn't exist OR caller has no access (don't leak existence).
    """
    kb = await session.get(KB, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="kb not found")
    role = await kb.role_for(session, user_id)
    if role is None:
        raise HTTPException(status_code=404, detail="kb not found")
    return kb, role


async def _load_readable_kb(session: AsyncSession, kb_id: str, user_id: str) -> KB:
    """For read paths: any role (owner / editor / viewer)."""
    kb, _ = await _resolve_role(session, kb_id, user_id)
    return kb


async def _load_writable_kb(session: AsyncSession, kb_id: str, user_id: str) -> KB:
    """For doc write paths (upload, delete doc): owner or editor; system KB 403."""
    kb, role = await _resolve_role(session, kb_id, user_id)
    if kb.is_system:
        raise HTTPException(status_code=403, detail="system kb is read-only")
    if role not in ("owner", "editor"):
        raise HTTPException(status_code=403, detail="editor or owner role required")
    return kb


async def _load_owner_kb(session: AsyncSession, kb_id: str, user_id: str) -> KB:
    """For owner-only paths (delete KB, manage members)."""
    kb, role = await _resolve_role(session, kb_id, user_id)
    if role != "owner":
        raise HTTPException(status_code=403, detail="owner role required")
    return kb


async def _email_map(session: AsyncSession, user_ids: list[str]) -> dict[str, dict[str, str]]:
    """Compatibility helper for the admin read model.

    Membership presentation now lives in ``capabilities.knowledge``; the
    admin route still uses this small projection until its own read model is
    migrated.
    """
    rows = (
        await session.execute(select(User.id, User.email).where(User.id.in_(user_ids)))
    ).all()
    return {row.id: {"email": row.email} for row in rows}


def _eval_http_error(exc: Exception) -> HTTPException:
    from src.harness.evaluation.metrics import EvaluationGateError

    if isinstance(exc, EvaluationGateError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


async def _load_document(
    session: AsyncSession, kb_id: str, doc_id: str
) -> Document:
    doc = await session.get(Document, doc_id)
    if doc is None or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="document not found")
    return doc


async def _resolve_doc_embedding_cfg(session: AsyncSession, kb: KB, user: User):
    from src.capabilities.knowledge.application.configuration import resolve_kb_embedding

    ecfg = resolve_kb_embedding(kb, user)
    if ecfg is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "embedding_not_configured",
                "message": "知识库未配置 embedding",
                "settings_url": "/settings",
            },
        )
    return ecfg


async def _optional_doc_embedding_cfg(session: AsyncSession, kb: KB, user: User):
    from src.capabilities.knowledge.application.configuration import resolve_kb_embedding

    return resolve_kb_embedding(kb, user)


# Backwards-compat alias for any callers expecting the pre-v2-M9 name.
_load_owned_kb = _load_writable_kb


async def _resolve_vector_size(user_embedding_cfg=None) -> int:
    """Vector size for new KB collections.

    User cfg.dim (if configured) wins. Otherwise: env override → known model
    table → live probe. Probing costs one embed call, but only on first use of
    an unknown model.
    """
    if user_embedding_cfg is not None and user_embedding_cfg.dim:
        return user_embedding_cfg.dim
    try:
        return get_vector_size()
    except RuntimeError:
        return await probe_vector_size()


# v3-M7: KB-level cfg helper — used by create_kb to derive a cfg dataclass
# from the request body (after Fernet-encrypting api_key for DB storage).
# v3-M8: when body.api_key is empty AND provider/base_url match the user's
# stored cfg, transparently reuse the user-level decrypted key. This is the
# "暗中记忆" mechanism that lets the KB creation form prefill prior creds
# without re-prompting for the api_key on every new KB.
async def _kb_embedding_cfg_from_body(
    req: "CreateKBRequest",
    session: AsyncSession,
    user_id: str,
):
    """Return (UserEmbeddingConfig | None) for vector-size probing if body
    carries a full KB-level embedding override; else None."""
    from src.capabilities.settings.domain.models import UserEmbeddingConfig
    from src.platform.security.crypto import decrypt
    if not (req.embedding_provider and req.embedding_base_url and req.embedding_model):
        return None
    api_key = req.embedding_api_key or ""
    if not api_key:
        u = await session.get(User, user_id)
        if (
            u is not None
            and u.embedding_api_key_enc
            and u.embedding_provider == req.embedding_provider
            and (u.embedding_base_url or "").rstrip("/") == req.embedding_base_url.rstrip("/")
        ):
            api_key = decrypt(u.embedding_api_key_enc)
            # Mutate body so the persisted KB row also gets the resolved key
            req.embedding_api_key = api_key
    return UserEmbeddingConfig(
        provider=req.embedding_provider,
        base_url=req.embedding_base_url.rstrip("/"),
        api_key=api_key,
        model=req.embedding_model,
        dim=int(req.embedding_dim or 0),
    )


# ---------------------------------------------------------------------------
# KB CRUD
# ---------------------------------------------------------------------------
@router.post("", status_code=status.HTTP_201_CREATED)
async def create_kb(
    req: CreateKBRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    # v3-M7: KB-level embedding cfg takes precedence over the user-level gate.
    # If the body carries a full embedding override, we accept it even if the
    # user hasn't configured `/settings` yet — this is the whole point of
    # per-KB cfg (a user can have multiple KBs each with different providers).
    kb_ecfg = await _kb_embedding_cfg_from_body(req, session, user.id)
    if kb_ecfg is None:
        require_user_embedding(user)
        ecfg = resolve_user_embedding(user)
    else:
        ecfg = kb_ecfg

    if ecfg is not None:
        embedding_model = ecfg.model
    else:
        embedding_model = default_embedding_model()

    # v3-M8.2: actually probe the embedding before persisting the KB row. The
    # frontend can already test the connection on its end (via /api/settings/
    # probe/embedding), but a defense-in-depth probe here closes the race
    # where the user clicks "save" before retesting after editing the key /
    # url. Without this, a wrong api_key results in a perfectly-created KB
    # row that 403s on first upload — confusing and hard to recover from.
    if ecfg is not None:
        try:
            actual_dim = await probe_vector_size(ecfg)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"embedding 连接测试失败（{exc.response.status_code}）："
                    f"请检查 base_url 与 api_key 是否正确。"
                ),
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502,
                detail=f"embedding 连接测试失败：{exc}",
            ) from exc
        # Probe authoritative — overrides any client-supplied dim hint.
        vector_size = actual_dim
    else:
        # No user/KB cfg → use env-resolved size (legacy path, e.g. tests).
        vector_size = await _resolve_vector_size(ecfg)

    # v3-M8: same fall-back logic for reranker — empty api_key + matching
    # provider/base_url reuses the user-level decrypted key.
    if req.reranker_provider and not req.reranker_api_key:
        u = await session.get(User, user.id)
        if (
            u is not None
            and u.reranker_api_key_enc
            and u.reranker_provider == req.reranker_provider
            and (u.reranker_base_url or "").rstrip("/") == (req.reranker_base_url or "").rstrip("/")
        ):
            from src.platform.security.crypto import decrypt as _dec
            req.reranker_api_key = _dec(u.reranker_api_key_enc)

    # v3-M7: encrypt KB-level api_keys before persistence.
    from src.platform.security.crypto import encrypt
    enc_embedding_key = (
        encrypt(req.embedding_api_key)
        if (kb_ecfg is not None and req.embedding_api_key)
        else None
    )
    enc_reranker_key = (
        encrypt(req.reranker_api_key)
        if (req.reranker_provider and req.reranker_api_key)
        else None
    )

    kb = KB(
        id=str(uuid.uuid4()),
        user_id=user.id,
        name=req.name.strip(),
        description=req.description.strip(),
        embedding_model=embedding_model,
        vector_size=vector_size,
        # v3-M7: persist KB-level embedding override (only when caller opted in)
        embedding_provider=req.embedding_provider if kb_ecfg is not None else None,
        embedding_base_url=(req.embedding_base_url.rstrip("/") if kb_ecfg is not None and req.embedding_base_url else None),
        embedding_api_key_enc=enc_embedding_key,
        embedding_model_override=req.embedding_model if kb_ecfg is not None else None,
        # v3-M7: persist KB-level reranker override (opt-in)
        reranker_provider=req.reranker_provider,
        reranker_base_url=(req.reranker_base_url.rstrip("/") if req.reranker_base_url else None),
        reranker_api_key_enc=enc_reranker_key,
        reranker_model=req.reranker_model,
        reranker_enabled=bool(req.reranker_enabled and req.reranker_provider),
        chunk_strategy=req.chunk_strategy,
    )
    session.add(kb)
    await session.commit()
    await session.refresh(kb)

    # Create the vector collection. Any initialization or collection failure
    # must remove the already-committed row so users never see a half-created
    # KB (for example, when the optional Milvus dependency is missing).
    try:
        store = get_store()
    except Exception as exc:  # noqa: BLE001
        await session.delete(kb)
        await session.commit()
        raise HTTPException(
            status_code=503,
            detail=f"向量库初始化失败：{exc}",
        ) from exc

    if not hasattr(store, "create_collection"):
        await session.delete(kb)
        await session.commit()
        raise HTTPException(
            status_code=500,
            detail="KB requires VECTOR_STORE=qdrant or milvus; current backend doesn't support multi-collection",
        )
    try:
        await store.create_collection(kb.collection_name, vector_size)
    except Exception as exc:  # noqa: BLE001
        await session.delete(kb)
        await session.commit()
        raise HTTPException(status_code=502, detail=f"qdrant create failed: {exc}") from exc

    return kb.to_public_dict(my_role="owner")


@router.get("")
async def list_kbs(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """List the user's own KBs + all system (read-only) KBs + member-of KBs.

    System KBs are pinned to the top; user KBs follow by created_at desc.
    Each KB carries `my_role` so the UI knows what controls to show.
    """
    own_or_sys = select(KB).where(or_(KB.user_id == user.id, KB.is_system.is_(True)))
    member_of = (
        select(KB)
        .join(KBMember, KBMember.kb_id == KB.id)
        .where(KBMember.user_id == user.id)
    )
    stmt = own_or_sys.union(member_of).order_by(
        KB.is_system.desc(), KB.created_at.desc()
    )
    # `union` returns rows shaped like KB columns; rehydrate via id lookup so
    # SQLAlchemy gives us full ORM instances (with relationship lazy-load).
    rows = (await session.execute(stmt)).all()
    ids = [r[0] for r in rows]
    kbs = (await session.execute(select(KB).where(KB.id.in_(ids)))).scalars().all()
    # Preserve union ordering by id.
    by_id = {k.id: k for k in kbs}
    ordered = [by_id[i] for i in ids if i in by_id]

    out: list[dict] = []
    for kb in ordered:
        role = await kb.role_for(session, user.id)
        out.append(kb.to_public_dict(my_role=role))
    return out


@router.get("/{kb_id}")
async def get_kb(
    kb_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    kb, role = await _resolve_role(session, kb_id, user.id)
    docs_sorted = sorted(kb.documents, key=lambda d: d.created_at)
    return {
        **kb.to_public_dict(my_role=role),
        "documents": [d.to_public_dict(kb=kb) for d in docs_sorted],
    }


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_kb(
    kb_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> None:
    kb = await _load_owner_kb(session, kb_id, user.id)
    await purge_kb(session, kb)


# ---------------------------------------------------------------------------
# v3-M3: KB settings PATCH + rebuild
# ---------------------------------------------------------------------------
@router.patch("/{kb_id}")
async def patch_kb(
    kb_id: str,
    body: PatchKBRequest,
    user: CurrentUser,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Owner-only. Toggles grouping / knowledge-graph and chunk defaults.
    System KBs are rejected — owner sentinel can't be hit via auth anyway,
    but we belt-and-braces here for clarity."""
    kb = await _load_owner_kb(session, kb_id, user.id)
    if kb.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System KBs cannot be modified",
        )
    enable_kg = False
    if body.grouping_enabled is not None:
        kb.grouping_enabled = body.grouping_enabled
    if body.kg_enabled is not None:
        was_on = bool(kb.kg_enabled)
        kb.kg_enabled = body.kg_enabled
        enable_kg = bool(body.kg_enabled) and not was_on
    if body.chunk_strategy is not None:
        kb.chunk_strategy = body.chunk_strategy
    if body.chunk_target is not None:
        kb.chunk_target = body.chunk_target
    if body.chunk_max_size is not None:
        kb.chunk_max_size = body.chunk_max_size
    if body.chunk_overlap is not None:
        kb.chunk_overlap = body.chunk_overlap

    sync_doc_ids: list[str] = []
    if enable_kg:
        for doc in kb.documents or []:
            if doc.status == "done" and (doc.parsed_text or "").strip():
                if (doc.kg_status or "") in ("", "skipped", "failed"):
                    sync_doc_ids.append(doc.id)

    await session.commit()
    await session.refresh(kb)

    if sync_doc_ids:
        from src.capabilities.knowledge.graph.sync import sync_document_to_lightrag

        for did in sync_doc_ids:
            background.add_task(sync_document_to_lightrag, did)

    return kb.to_public_dict(my_role="owner")


@router.post("/{kb_id}/rebuild")
async def rebuild_kb(
    kb_id: str,
    user: CurrentUser,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Owner-only. Drops the vector collection and re-ingests every Document.

    Purpose (v3-M3): upgrade a pre-v3-M3 dense-only Milvus collection to the
    hybrid schema (dense + BM25). Since Milvus doesn't support adding a
    sparse field to an existing collection, the only path is drop+recreate
    +re-embed. Document SQLite rows survive — original files on disk
    (data/uploads/{kb_id}/{doc_id}.{ext}) drive re-ingest.

    URL-sourced documents re-fetch from source_url. File-sourced documents
    need the original upload still on disk; if missing, that doc is marked
    failed but other docs proceed.

    During the rebuild window (~30-90s for typical KB) chat against this KB
    will see empty hits — acceptable trade-off for a one-time owner action.
    """
    kb = await _load_owner_kb(session, kb_id, user.id)
    if kb.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System KBs cannot be rebuilt",
        )

    store = get_store()
    if not hasattr(store, "delete_collection") or not hasattr(
        store, "create_collection"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "KB rebuild requires a multi-collection backend "
                "(qdrant or milvus)"
            ),
        )

    collection_name = kb.collection_name
    vector_size = kb.vector_size or await _resolve_vector_size(
        resolve_user_embedding(user)
    )

    # Reset all documents back to pending; zero the KB's chunks_count so the
    # ingest pipeline's delta math (kb.chunks_count -= prev + new) produces
    # the right total. error/chunks_count cleared per doc.
    docs = sorted(kb.documents, key=lambda d: d.created_at)
    for d in docs:
        d.status = "pending"
        d.chunks_count = 0
        d.error = ""
    kb.chunks_count = 0
    await session.commit()
    doc_ids = [d.id for d in docs]

    # Drop + recreate the collection with the current schema (v3-M3 hybrid
    # for Milvus, dense for Qdrant). create_collection is idempotent so
    # crash-recovery is safe.
    await store.delete_collection(collection_name)
    await store.create_collection(collection_name, vector_size)

    # Persist all work before handing it to this process. A worker can resume
    # any unfinished job after a deploy/restart.
    jobs = await enqueue_documents(session, doc_ids)
    await session.commit()
    handoff_ingestion(background, jobs)

    return {
        "rebuilding": True,
        "doc_count": len(doc_ids),
        "collection": collection_name,
    }


# ---------------------------------------------------------------------------
# Per-KB golden-set evaluation
# ---------------------------------------------------------------------------
@router.get("/{kb_id}/eval/templates")
async def list_kb_eval_templates(
    kb_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _load_writable_kb(session, kb_id, user.id)
    return {"templates": evaluation.list_templates()}


@router.get("/{kb_id}/eval/config")
async def get_kb_eval_config(
    kb_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    kb = await _load_writable_kb(session, kb_id, user.id)
    try:
        return await evaluation.public_config(session, kb.id)
    except Exception as exc:
        raise _eval_http_error(exc) from exc


@router.put("/{kb_id}/eval/config")
async def put_kb_eval_config(
    kb_id: str,
    body: PutEvalConfigRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    kb = await _load_writable_kb(session, kb_id, user.id)
    try:
        return await evaluation.save_config(
            session,
            kb,
            golden_set_jsonl=body.golden_set_jsonl,
            gate_json=body.gate_json,
            template=body.template,
        )
    except evaluation.EvaluationInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise _eval_http_error(exc) from exc


@router.post("/{kb_id}/eval/run")
async def run_kb_eval_regression(
    kb_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    kb = await _load_writable_kb(session, kb_id, user.id)
    try:
        return await evaluation.run_regression_public(session, kb, created_by=user.id)
    except Exception as exc:
        raise _eval_http_error(exc) from exc


@router.get("/{kb_id}/eval/runs")
async def list_kb_eval_runs(
    kb_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    kb = await _load_writable_kb(session, kb_id, user.id)
    return await evaluation.list_runs(session, kb.id, limit=limit, offset=offset)


@router.get("/{kb_id}/eval/runs/{run_id}")
async def get_kb_eval_run(
    kb_id: str,
    run_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    kb = await _load_writable_kb(session, kb_id, user.id)
    run = await session.get(KbEvalRun, run_id)
    if run is None or run.kb_id != kb.id:
        raise HTTPException(status_code=404, detail="eval run not found")
    return run.to_public_dict(include_report=True)


@router.post("/{kb_id}/eval/replay")
async def replay_kb_eval(
    kb_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    run_id: str | None = Query(default=None),
    retrieval_jsonl: UploadFile | None = File(default=None),
) -> dict:
    kb = await _load_writable_kb(session, kb_id, user.id)
    has_file = retrieval_jsonl is not None and bool(retrieval_jsonl.filename)
    if bool(run_id) == has_file:
        raise HTTPException(
            status_code=400,
            detail="provide either run_id or retrieval_jsonl, not both",
        )
    try:
        if run_id:
            source = await session.get(KbEvalRun, run_id)
            if source is None or source.kb_id != kb.id:
                raise HTTPException(status_code=404, detail="eval run not found")
            predictions = evaluation.predictions_from_run(source)
        else:
            assert retrieval_jsonl is not None
            raw = await retrieval_jsonl.read()
            if len(raw) > evaluation.max_predictions_bytes():
                raise HTTPException(status_code=400, detail="retrieval.jsonl is too large")
            predictions = evaluation.parse_predictions(raw)
        return await evaluation.replay(session, kb, predictions, created_by=user.id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _eval_http_error(exc) from exc


@router.get("/{kb_id}/eval/monitor")
async def get_kb_eval_monitor(
    kb_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    hours: int | None = Query(None, ge=1, le=24 * 31),
) -> dict:
    kb = await _load_readable_kb(session, kb_id, user.id)
    from src.platform.observability import build_rag_monitor_snapshot

    snapshot = await build_rag_monitor_snapshot(session, hours=hours, kb_id=kb.id)
    snapshot["kb_id"] = kb.id
    snapshot["scope_note"] = "仅统计含 kb_id 的近期 Trace；升级前的历史检索不会出现在本页。"
    return snapshot


# ---------------------------------------------------------------------------
# Document upload
# ---------------------------------------------------------------------------
@router.post("/{kb_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    kb_id: str,
    user: CurrentUser,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    file: Optional[UploadFile] = File(default=None),
    url: Annotated[str, Form()] = "",
) -> dict:
    """Upload a file (multipart) OR a URL (form field `url=...`).

    Exactly one of `file` / `url` must be provided.
    """
    kb = await _load_writable_kb(session, kb_id, user.id)
    # v3-M8.2: BYOK gate is conditional — KB with its own embedding cfg is
    # self-sufficient (the whole point of v3-M7 per-KB cfg). Only enforce the
    # user-level gate when the KB has no own embedding cfg.
    if not (kb.embedding_provider and kb.embedding_base_url and kb.embedding_model_override):
        require_user_embedding(user)

    if (file is None) == (not url):
        raise HTTPException(
            status_code=400,
            detail="provide exactly one of `file` (multipart) or `url` (form field)",
        )

    # Validate credentials before saving a pending document. Otherwise a
    # configuration error would leave a record that no worker could process.
    ecfg = resolve_kb_embedding(kb, user)
    if ecfg is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "embedding_not_configured",
                "message": "知识库未配置 embedding，且当前用户也未配置默认 embedding；请在创建知识库时填写 embedding 凭据。",
                "settings_url": "/settings",
            },
        )

    doc_id = str(uuid.uuid4())

    if file is not None:
        ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
        if ext not in SUPPORTED_EXTS:
            raise HTTPException(
                status_code=415,
                detail=f"unsupported file type '.{ext}'. supported: {sorted(SUPPORTED_EXTS)}",
            )
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="empty file")
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"file too large ({len(content)} > {MAX_UPLOAD_BYTES})",
            )
        await documents.save_upload(
            kb_id,
            doc_id,
            file.filename or f"upload.{ext}",
            content,
            content_type=file.content_type,
        )
        doc = Document(
            id=doc_id,
            kb_id=kb_id,
            filename=file.filename or f"upload.{ext}",
            mime=file.content_type or "",
            size_bytes=len(content),
            source_type="file",
            source_url="",
            status="pending",
        )
    else:
        # URL upload: display label = filename if given, else URL itself
        url_str = url.strip()
        doc = Document(
            id=doc_id,
            kb_id=kb_id,
            filename=url_str[:255],  # display as-is; ingest will fetch + parse
            mime="text/html",
            size_bytes=0,  # filled in by ingest if needed
            source_type="url",
            source_url=url_str,
            status="pending",
        )

    session.add(doc)
    jobs = await enqueue_documents(session, [doc_id])
    await session.commit()
    await session.refresh(doc)
    handoff_ingestion(background, jobs)

    return doc.to_public_dict(kb=kb)


@router.get("/{kb_id}/documents")
async def list_documents(
    kb_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    kb = await _load_readable_kb(session, kb_id, user.id)
    docs_sorted = sorted(kb.documents, key=lambda d: d.created_at)
    return [d.to_public_dict(kb=kb) for d in docs_sorted]


@router.delete(
    "/{kb_id}/documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_document(
    kb_id: str,
    doc_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> None:
    kb = await _load_writable_kb(session, kb_id, user.id)
    doc = await session.get(Document, doc_id)
    if doc is None or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="document not found")

    chunks_to_subtract = doc.chunks_count or 0
    filename_snap = doc.filename
    doc_id_snap = doc.id
    kg_doc_id_snap = getattr(doc, "kg_doc_id", "") or ""
    kg_track_id_snap = getattr(doc, "kg_track_id", "") or ""
    kg_enabled_snap = bool(getattr(kb, "kg_enabled", False))

    # A graph workspace is an external source copy.  Its strict cleanup must
    # happen while the Document still retains the LightRAG identifiers, so the
    # caller can retry a transient failure without losing that metadata.
    if kg_enabled_snap and (kg_doc_id_snap or kg_track_id_snap):
        from src.capabilities.knowledge.graph.sync import delete_document_from_lightrag

        await delete_document_from_lightrag(
            kb_id=kb_id,
            kg_doc_id=kg_doc_id_snap,
            kg_track_id=kg_track_id_snap,
            strict=True,
        )

    # Drop chunks from Qdrant (idempotent), then DB row, then on-disk file.
    await documents.remove_document_chunks(kb.collection_name, doc_id_snap)
    await session.execute(delete(IngestionJob).where(IngestionJob.document_id == doc_id_snap))
    await session.delete(doc)
    if chunks_to_subtract:
        kb.chunks_count = max(0, (kb.chunks_count or 0) - chunks_to_subtract)
    await session.commit()
    await documents.delete_upload(kb_id, doc_id_snap, filename_snap)

@router.get("/{kb_id}/documents/{doc_id}")
async def get_document(
    kb_id: str,
    doc_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    include_parsed_text: bool = Query(default=False),
) -> dict:
    kb = await _load_readable_kb(session, kb_id, user.id)
    doc = await _load_document(session, kb_id, doc_id)
    return doc.to_public_dict(include_parsed_text=include_parsed_text, kb=kb)


@router.patch("/{kb_id}/documents/{doc_id}")
async def patch_document(
    kb_id: str,
    doc_id: str,
    body: PatchDocumentRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    kb = await _load_writable_kb(session, kb_id, user.id)
    doc = await _load_document(session, kb_id, doc_id)
    enabled_changed = False
    fields_set = body.model_fields_set
    if body.filename is not None:
        doc.filename = body.filename.strip()
    if "chunk_strategy" in fields_set:
        doc.chunk_strategy = body.chunk_strategy
    if "chunk_target" in fields_set:
        doc.chunk_target = body.chunk_target
    if "chunk_max_size" in fields_set:
        doc.chunk_max_size = body.chunk_max_size
    if "chunk_overlap" in fields_set:
        doc.chunk_overlap = body.chunk_overlap
    if body.enabled is not None and doc.enabled != body.enabled:
        doc.enabled = body.enabled
        enabled_changed = True
    if enabled_changed:
        store = get_store()
        if hasattr(store, "upsert"):
            ecfg = await _optional_doc_embedding_cfg(session, kb, user)
            await chunks.sync_document_vector_payloads(session, store, kb, doc, ecfg)
    await session.commit()
    await session.refresh(doc)
    return doc.to_public_dict(kb=kb)


@router.get("/{kb_id}/documents/{doc_id}/download")
async def download_document(
    kb_id: str,
    doc_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _load_readable_kb(session, kb_id, user.id)
    doc = await _load_document(session, kb_id, doc_id)
    if doc.source_type != "file":
        raise HTTPException(status_code=400, detail="only file uploads can be downloaded")
    try:
        content = await documents.read_upload(kb_id, doc_id, doc.filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="original file not found") from exc
    return Response(
        content=content,
        media_type=doc.mime or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'},
    )


@router.post("/{kb_id}/documents/{doc_id}/reingest")
async def reingest_document(
    kb_id: str,
    doc_id: str,
    user: CurrentUser,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict:
    kb = await _load_writable_kb(session, kb_id, user.id)
    doc = await _load_document(session, kb_id, doc_id)
    await _resolve_doc_embedding_cfg(session, kb, user)
    prev_chunks = doc.chunks_count or 0
    await documents.remove_document_chunks(kb.collection_name, doc.id)
    doc.status = "pending"
    doc.chunks_count = 0
    doc.error = ""
    if prev_chunks:
        kb.chunks_count = max(0, (kb.chunks_count or 0) - prev_chunks)
    await session.commit()

    jobs = await enqueue_documents(session, [doc.id])
    await session.commit()
    handoff_ingestion(background, jobs)
    return doc.to_public_dict(kb=kb)


@router.get("/{kb_id}/documents/{doc_id}/chunks")
async def list_document_chunks(
    kb_id: str,
    doc_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=200),
    enabled: bool | None = Query(default=None),
) -> dict:
    kb = await _load_readable_kb(session, kb_id, user.id)
    doc = await _load_document(session, kb_id, doc_id)
    store = get_store()
    rows, total = await chunks.list_document_chunks_with_backfill(
        session,
        store,
        kb,
        doc,
        page=page,
        page_size=page_size,
        q=q,
        enabled=enabled,
    )
    return {
        "items": [c.to_public_dict() for c in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{kb_id}/documents/{doc_id}/chunks/{chunk_id}")
async def get_chunk(
    kb_id: str,
    doc_id: str,
    chunk_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _load_readable_kb(session, kb_id, user.id)
    await _load_document(session, kb_id, doc_id)
    chunk = await session.get(Chunk, chunk_id)
    if chunk is None or chunk.doc_id != doc_id:
        raise HTTPException(status_code=404, detail="chunk not found")
    return chunk.to_public_dict()


@router.patch("/{kb_id}/documents/{doc_id}/chunks/batch-all")
async def batch_patch_all_chunks(
    kb_id: str,
    doc_id: str,
    body: BatchAllChunksRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    kb = await _load_writable_kb(session, kb_id, user.id)
    doc = await _load_document(session, kb_id, doc_id)
    ecfg = await _optional_doc_embedding_cfg(session, kb, user)
    store = get_store()
    if not hasattr(store, "upsert"):
        raise HTTPException(status_code=500, detail="vector store unavailable")
    total = await chunks.batch_set_all_document_chunks_enabled(
        session, store, kb, doc, enabled=body.enabled, embedding_cfg=ecfg
    )
    await session.commit()
    return {"updated": total, "enabled": body.enabled}


@router.patch("/{kb_id}/documents/{doc_id}/chunks/batch")
async def batch_patch_chunks(
    kb_id: str,
    doc_id: str,
    body: BatchPatchChunksRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    kb = await _load_writable_kb(session, kb_id, user.id)
    doc = await _load_document(session, kb_id, doc_id)
    ecfg = await _optional_doc_embedding_cfg(session, kb, user)
    store = get_store()
    if not hasattr(store, "upsert"):
        raise HTTPException(status_code=500, detail="vector store unavailable")
    rows = await chunks.batch_set_chunks_enabled(
        session,
        store,
        kb,
        doc,
        body.chunk_ids,
        enabled=body.enabled,
        embedding_cfg=ecfg,
    )
    await session.commit()
    return {
        "updated": len(rows),
        "items": [c.to_public_dict() for c in rows],
    }


@router.patch("/{kb_id}/documents/{doc_id}/chunks/{chunk_id}")
async def patch_chunk(
    kb_id: str,
    doc_id: str,
    chunk_id: str,
    body: PatchChunkRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    kb = await _load_writable_kb(session, kb_id, user.id)
    doc = await _load_document(session, kb_id, doc_id)
    chunk = await session.get(Chunk, chunk_id)
    if chunk is None or chunk.doc_id != doc_id:
        raise HTTPException(status_code=404, detail="chunk not found")

    text_changed = False
    if body.text is not None:
        new_text = body.text.strip()
        if new_text != chunk.text:
            chunk.text = new_text
            chunk.char_count = len(chunk.text)
            text_changed = True
    if body.enabled is not None:
        chunk.enabled = body.enabled

    store = get_store()
    if not hasattr(store, "upsert"):
        raise HTTPException(status_code=500, detail="vector store unavailable")
    if text_changed:
        ecfg = await _resolve_doc_embedding_cfg(session, kb, user)
        await chunks.upsert_single_chunk_vector(session, store, kb, doc, chunk, ecfg)
    elif body.enabled is not None:
        ecfg = await _optional_doc_embedding_cfg(session, kb, user)
        await chunks.sync_chunk_payloads_only(
            session, store, kb, doc, [chunk], embedding_cfg=ecfg
        )
    await session.commit()
    await session.refresh(chunk)
    return chunk.to_public_dict()


@router.delete(
    "/{kb_id}/documents/{doc_id}/chunks/{chunk_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_chunk(
    kb_id: str,
    doc_id: str,
    chunk_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> None:
    kb = await _load_writable_kb(session, kb_id, user.id)
    doc = await _load_document(session, kb_id, doc_id)
    chunk = await session.get(Chunk, chunk_id)
    if chunk is None or chunk.doc_id != doc_id:
        raise HTTPException(status_code=404, detail="chunk not found")
    store = get_store()
    await chunks.delete_single_chunk(session, store, kb, doc, chunk)
    await session.commit()


@router.post("/{kb_id}/documents/{doc_id}/chunks/{chunk_id}/split")
async def split_chunk_route(
    kb_id: str,
    doc_id: str,
    chunk_id: str,
    body: SplitChunkRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    kb = await _load_writable_kb(session, kb_id, user.id)
    doc = await _load_document(session, kb_id, doc_id)
    chunk = await session.get(Chunk, chunk_id)
    if chunk is None or chunk.doc_id != doc_id:
        raise HTTPException(status_code=404, detail="chunk not found")
    ecfg = await _resolve_doc_embedding_cfg(session, kb, user)
    store = get_store()
    try:
        left, right = await chunks.split_chunk(
            session, store, kb, doc, chunk, body.offset, ecfg
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return {"chunks": [left.to_public_dict(), right.to_public_dict()]}


@router.post("/{kb_id}/documents/{doc_id}/chunks/merge")
async def merge_chunks_route(
    kb_id: str,
    doc_id: str,
    body: MergeChunksRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    kb = await _load_writable_kb(session, kb_id, user.id)
    doc = await _load_document(session, kb_id, doc_id)
    a = await session.get(Chunk, body.chunk_ids[0])
    b = await session.get(Chunk, body.chunk_ids[1])
    if a is None or b is None:
        raise HTTPException(status_code=404, detail="chunk not found")
    # Validate the requested operation before requiring embedding credentials.
    # Otherwise a malformed merge misleadingly reports a configuration error
    # instead of the actionable adjacency problem.
    if a.doc_id != doc.id or b.doc_id != doc.id:
        raise HTTPException(status_code=400, detail="chunks must belong to the same document")
    if a.id == b.id:
        raise HTTPException(status_code=400, detail="cannot merge a chunk with itself")
    if abs(a.chunk_idx - b.chunk_idx) != 1:
        raise HTTPException(status_code=400, detail="chunks must be adjacent")
    ecfg = await _resolve_doc_embedding_cfg(session, kb, user)
    store = get_store()
    try:
        merged = await chunks.merge_chunks(session, store, kb, doc, a, b, ecfg)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return merged.to_public_dict()


# ---------------------------------------------------------------------------
# v2-M9: Members management
# ---------------------------------------------------------------------------
@router.get("/{kb_id}/members")
async def list_members(
    kb_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List owner + members of a KB. Any role can see (transparency).

    Returns:
      {
        "owner": {"user_id", "email", "display_name"} | None (system KB has no real owner),
        "members": [{"user_id", "email", "display_name", "role", "invited_by_email", "created_at"}]
      }
    """
    kb = await _load_readable_kb(session, kb_id, user.id)
    return await members.list_members(session, kb)


@router.post("/{kb_id}/members", status_code=status.HTTP_201_CREATED)
async def invite_member(
    kb_id: str,
    req: InviteMemberRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Invite an existing user by email + role. Owner only."""
    kb = await _load_owner_kb(session, kb_id, user.id)

    try:
        return await members.invite(
            session, kb, email=req.email, role=req.role, invited_by=user.id
        )
    except members.MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except members.InvalidMemberOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{kb_id}/members/{user_id}")
async def patch_member(
    kb_id: str,
    user_id: str,
    req: PatchMemberRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Change a member's role. Owner only."""
    kb = await _load_owner_kb(session, kb_id, user.id)
    try:
        return await members.update_role(session, kb.id, user_id=user_id, role=req.role)
    except members.MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/{kb_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def remove_member(
    kb_id: str,
    user_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove a member. Either the owner (any user_id) or the member themselves
    (user_id == caller) can call this. Editor cannot remove peers."""
    kb, role = await _resolve_role(session, kb_id, user.id)
    is_owner = role == "owner"
    is_self = user_id == user.id
    if not (is_owner or is_self):
        raise HTTPException(status_code=403, detail="owner or self only")
    try:
        await members.remove(session, kb.id, user_id=user_id)
    except members.MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
