"""Permission-scoped knowledge-base intent detection for unbound chats."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform.llm import CostTracker, get_client, pick_model, with_cache_control
from src.platform.observability import ageneration, traced
from src.capabilities.knowledge.domain.models import KB, KBMember
from src.harness.prompts.system import build_kb_routing_system_prompt
from src.harness.policy.prompt_injection import assess_prompt_injection

if TYPE_CHECKING:
    from src.capabilities.settings.domain.models import UserLLMConfig

log = logging.getLogger(__name__)
RouteSource = Literal["disabled", "rule", "llm", "fallback"]
_ROUTE_MODES = frozenset({"off", "rule_only", "llm_fallback", "always_llm"})
_SKIP_HINTS = ("你好", "您好", "在吗", "谢谢", "多谢", "再见", "翻译", "润色", "改写", "总结刚才", "总结一下刚才", "写一首", "写个")


@dataclass(frozen=True, slots=True)
class AutoKBRoute:
    """A safe decision, with the selected row retained only server-side."""
    kb: KB | None
    needs_retrieval: bool
    source: RouteSource
    confidence: str
    reason: str
    latency_ms: int
    cost_usd: float | None = None
    candidate_count: int = 0
    prompt_registry: dict[str, str | int | None] | None = None
    # A non-empty tuple represents an explicit multi-source request. ``kb``
    # remains for backward compatibility with single-KB callers.
    kbs: tuple[KB, ...] = ()

    @property
    def selected_kb_id(self) -> str | None:
        selected = self.selected_kbs
        return selected[0].id if selected else None

    @property
    def selected_kbs(self) -> tuple[KB, ...]:
        if self.kbs:
            return self.kbs
        return (self.kb,) if self.kb is not None else ()

    @property
    def selected_kb_ids(self) -> list[str]:
        return [kb.id for kb in self.selected_kbs]

    def trace_metadata(self) -> dict[str, Any]:
        return {
            "needs_retrieval": self.needs_retrieval,
            "selected_kb_id": self.selected_kb_id,
            "selected_kb_ids": self.selected_kb_ids,
            "source": self.source,
            "confidence": self.confidence,
            "reason": self.reason,
            "latency_ms": self.latency_ms,
            "candidate_count": self.candidate_count,
            "prompt_registry": self.prompt_registry,
        }


def _normalize_mode(value: str | None) -> str:
    mode = (value or "llm_fallback").strip().lower()
    return mode if mode in _ROUTE_MODES else "llm_fallback"


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        content = message.get("content")
        if message.get("role") == "user" and isinstance(content, str) and content.strip():
            return " ".join(content.split())
    return ""


async def list_readable_routable_kbs(session: AsyncSession, *, user_id: str, limit: int) -> list[KB]:
    """Return only readable KBs that can possibly satisfy a vector search."""
    max_candidates = max(1, min(int(limit), 12))
    statement = (select(KB).outerjoin(KBMember, (KBMember.kb_id == KB.id) & (KBMember.user_id == user_id)).where(or_(KB.user_id == user_id, KB.is_system.is_(True), KBMember.user_id == user_id), KB.chunks_count > 0).order_by(KB.is_system.desc(), KB.chunks_count.desc(), KB.created_at.desc()).limit(max_candidates))
    return list((await session.execute(statement)).scalars().unique().all())


def _safe_catalog_value(value: str, *, limit: int) -> str:
    text = " ".join((value or "").split())[:limit]
    return "[omitted: untrusted metadata]" if text and assess_prompt_injection(text).level == "high" else text


def _catalog(candidates: list[KB]) -> list[dict[str, str]]:
    return [{"id": kb.id, "name": _safe_catalog_value(kb.name, limit=128), "description": _safe_catalog_value(kb.description, limit=240)} for kb in candidates]


def _rule_decision(query: str, candidates: list[KB]) -> AutoKBRoute | None:
    if not query:
        return AutoKBRoute(None, False, "rule", "high", "empty_query", 0, candidate_count=len(candidates))
    if len(query) <= 16 and any(hint in query for hint in _SKIP_HINTS):
        return AutoKBRoute(None, False, "rule", "high", "obvious_general_intent", 0, candidate_count=len(candidates))
    matches = [kb for kb in candidates if len(kb.name.strip()) >= 2 and kb.name.strip().lower() in query.lower()]
    if len(matches) == 1:
        return AutoKBRoute(matches[0], True, "rule", "high", "kb_name_mentioned", 0, candidate_count=len(candidates))
    # Multiple explicitly named KBs are not ambiguous: the user has stated a
    # multi-source intent. Keep the fan-out bounded even if names overlap.
    if 1 < len(matches) <= 3:
        return AutoKBRoute(
            matches[0], True, "rule", "high", "kb_names_mentioned", 0,
            candidate_count=len(candidates), kbs=tuple(matches),
        )
    return None


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty auto-route response")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object found") from None
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("auto-route response must be an object")
    return payload


def _coerce_llm_decision(payload: dict[str, Any], *, candidates: list[KB], latency_ms: int, cost_usd: float | None) -> AutoKBRoute:
    by_id = {kb.id: kb for kb in candidates}
    needs_retrieval = payload.get("needs_retrieval") is True
    selected_ids_raw = payload.get("selected_kb_ids")
    if isinstance(selected_ids_raw, list):
        selected_ids = [str(item).strip() for item in selected_ids_raw if str(item).strip()]
    else:
        selected_id = str(payload.get("selected_kb_id") or "").strip()
        selected_ids = [selected_id] if selected_id else []
    confidence = str(payload.get("confidence") or "low").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    reason = str(payload.get("reason") or "llm_decision").strip()[:80] or "llm_decision"
    selected_rows: list[KB] = []
    seen_ids: set[str] = set()
    for item in selected_ids:
        if item in by_id and item not in seen_ids:
            selected_rows.append(by_id[item])
            seen_ids.add(item)
    selected = tuple(selected_rows)
    if len(selected) > 3:
        selected = ()
    kb = selected[0] if selected else None
    return AutoKBRoute(
        kb, needs_retrieval and kb is not None, "llm", confidence,
        reason if kb is not None else "no_confident_kb_match", latency_ms,
        cost_usd, len(candidates), kbs=selected,
    )


@traced("auto_kb_route")
async def resolve_auto_kb_route_from_candidates(
    *,
    messages: list[dict[str, Any]],
    candidates: list[KB],
    llm_cfg: "UserLLMConfig | None",
    system_prompt: str | None = None,
    prompt_metadata: dict[str, str | int | None] | None = None,
) -> AutoKBRoute:
    """Choose from a pre-filtered, ACL-safe candidate list."""
    from src.settings import get_settings

    started = time.perf_counter()
    mode = _normalize_mode(getattr(get_settings(), "kb_auto_route_mode", "llm_fallback"))
    if mode == "off":
        return AutoKBRoute(None, False, "disabled", "high", "auto_route_disabled", 0)
    query = _latest_user_text(messages)
    if not query:
        return AutoKBRoute(None, False, "rule", "high", "empty_query", 0)
    if assess_prompt_injection(query).level == "high":
        return AutoKBRoute(None, False, "rule", "high", "high_risk_input", 0)
    if not candidates:
        return AutoKBRoute(None, False, "rule", "high", "no_readable_kb", int((time.perf_counter() - started) * 1000))
    if mode != "always_llm":
        rule = _rule_decision(query, candidates)
        if rule is not None:
            return AutoKBRoute(
                rule.kb,
                rule.needs_retrieval,
                rule.source,
                rule.confidence,
                rule.reason,
                int((time.perf_counter() - started) * 1000),
                candidate_count=len(candidates),
                kbs=rule.selected_kbs,
            )
        if mode == "rule_only":
            return AutoKBRoute(None, False, "fallback", "low", "rule_only_uncertain", int((time.perf_counter() - started) * 1000), candidate_count=len(candidates))

    model = pick_model(messages, [], llm_cfg)
    catalog_json = json.dumps(_catalog(candidates), ensure_ascii=False)
    resolved_system_prompt = (
        build_kb_routing_system_prompt(template=system_prompt).rstrip()
        + f"\n<kb_catalog untrusted=\"true\">{catalog_json}</kb_catalog>"
    )
    tracker = CostTracker()
    try:
        client = get_client(llm_cfg)
        async with ageneration("auto_kb_route.llm", model=model, input={"candidate_count": len(candidates)}) as gen:
            if llm_cfg is not None and llm_cfg.provider == "anthropic":
                response = await client.messages.create(model=model, max_tokens=180, system=with_cache_control([{"type": "text", "text": resolved_system_prompt}], llm_cfg), messages=[{"role": "user", "content": query}])
                tracker.add(model, response.usage, cfg=llm_cfg)
                text = "\n".join(block.text for block in response.content if getattr(block, "type", "") == "text")
                if gen is not None:
                    gen.update(output=text, usage=response.usage)
            else:
                response = await client.chat.completions.create(model=model, messages=[{"role": "system", "content": resolved_system_prompt}, {"role": "user", "content": query}], max_tokens=180)
                tracker.add(model, getattr(response, "usage", None), cfg=llm_cfg)
                text = response.choices[0].message.content or ""
                if gen is not None:
                    gen.update(output=text, usage=getattr(response, "usage", None))
        route = _coerce_llm_decision(
            _extract_json_object(text),
            candidates=candidates,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=tracker.total_usd,
        )
        return AutoKBRoute(
            route.kb,
            route.needs_retrieval,
            route.source,
            route.confidence,
            route.reason,
            route.latency_ms,
            route.cost_usd,
            route.candidate_count,
            prompt_registry=prompt_metadata,
            kbs=route.kbs,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("auto_kb_route_failed", exc_info=exc)
        return AutoKBRoute(None, False, "fallback", "low", "router_unavailable", int((time.perf_counter() - started) * 1000), candidate_count=len(candidates))


async def resolve_auto_kb_route(session: AsyncSession, *, user_id: str, messages: list[dict[str, Any]], llm_cfg: "UserLLMConfig | None") -> AutoKBRoute:
    """Resolve KB selection for compatibility callers outside ReAct scope."""
    from src.settings import get_settings

    candidates = await list_readable_routable_kbs(session, user_id=user_id, limit=getattr(get_settings(), "kb_auto_route_max_candidates", 8))
    return await resolve_auto_kb_route_from_candidates(messages=messages, candidates=candidates, llm_cfg=llm_cfg)
