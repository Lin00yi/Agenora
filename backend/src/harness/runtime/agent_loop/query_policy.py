"""Query policy node: rule-first KB search planning with LLM fallback."""
from __future__ import annotations

import json
import time
from typing import Any, TYPE_CHECKING

from src.harness.contracts.state import AgentState
from src.platform.llm import CostTracker, pick_model, with_cache_control
from src.harness.context.rag.policy import resolve_kb_retrieval_policy
from src.platform.observability import ageneration, traced
from src.harness.policy.prompt_injection import assess_prompt_injection

from .constants import (
    MAX_KB_REWRITE_QUERIES,
    QueryPolicyAction,
    QueryPolicyDecision,
    QueryPolicySource,
    _QUERY_POLICY_ACTIONS,
    _QUERY_POLICY_MODES,
    _RULE_ABUSE_HINTS,
    _RULE_FOLLOWUP_KEYWORDS,
    _RULE_INFORMATION_SEEKING_HINTS,
    _RULE_MULTI_INTENT_KEYWORDS,
    _RULE_SKIP_KEYWORDS,
    _latest_user_text,
)

if TYPE_CHECKING:
    from src.capabilities.settings.domain.models import UserLLMConfig


def _configured_max_kb_queries() -> int:
    from src.settings import get_settings

    raw = get_settings().kb_query_policy_max_queries
    try:
        return max(1, min(int(raw), MAX_KB_REWRITE_QUERIES))
    except (TypeError, ValueError):
        return MAX_KB_REWRITE_QUERIES


def _configured_kb_final_limit() -> int:
    return resolve_kb_retrieval_policy().final_limit


def _coerce_kb_queries(
    payload: Any,
    fallback_query: str,
    *,
    max_queries: int = MAX_KB_REWRITE_QUERIES,
) -> list[dict[str, Any]]:
    """Normalize model JSON into at most three deterministic KB search calls."""
    max_queries = max(1, min(max_queries, MAX_KB_REWRITE_QUERIES))
    raw_queries: Any
    if isinstance(payload, dict):
        raw_queries = payload.get("queries", [])
    else:
        raw_queries = payload

    queries: list[dict[str, Any]] = []
    seen: set[str] = set()
    final_limit = _configured_kb_final_limit()
    if isinstance(raw_queries, list):
        for item in raw_queries:
            query = ""
            limit = final_limit
            if isinstance(item, str):
                query = item
            elif isinstance(item, dict):
                query = str(item.get("query") or "")
                raw_limit = item.get("limit")
                if raw_limit is not None:
                    try:
                        limit = int(raw_limit)
                    except (TypeError, ValueError):
                        limit = final_limit
            query = " ".join(query.split())
            if not query or query in seen:
                continue
            seen.add(query)
            queries.append({"query": query, "limit": max(1, min(limit, final_limit))})
            if len(queries) >= max_queries:
                break

    if not queries and fallback_query.strip():
        queries.append({"query": fallback_query.strip(), "limit": final_limit})
    return queries


def _direct_policy_decision(
    query: str,
    *,
    reason: str,
    source: QueryPolicySource,
    latency_ms: int,
) -> QueryPolicyDecision:
    return {
        "action": "direct",
        "queries": _coerce_kb_queries([query], query, max_queries=1),
        "reason": reason,
        "source": source,
        "latency_ms": latency_ms,
    }


def _skip_policy_decision(
    *,
    reason: str,
    source: QueryPolicySource,
    latency_ms: int,
) -> QueryPolicyDecision:
    return {
        "action": "skip_kb",
        "queries": [],
        "reason": reason,
        "source": source,
        "latency_ms": latency_ms,
    }


def _apply_query_policy_decision(
    state: AgentState,
    decision: QueryPolicyDecision,
    *,
    cost: CostTracker | None = None,
) -> AgentState:
    should_search = decision["action"] != "skip_kb" and bool(decision["queries"])
    next_state: AgentState = {
        **state,
        "kb_queries": decision["queries"],
        "kb_context": "",
        "retrieved_evidence": [],
        "kb_search_done": not should_search,
        "query_policy_action": decision["action"],
        "query_policy_reason": decision["reason"],
        "query_policy_source": decision["source"],
        "query_policy_latency_ms": decision["latency_ms"],
    }
    if cost is not None:
        next_state["cost_usd"] = cost.total_usd
    return next_state


def _rule_query_policy(query: str, *, max_queries: int) -> QueryPolicyDecision | None:
    """Return a high-confidence rule decision, or None when LLM judgment is useful."""
    text = " ".join(query.split())
    lowered = text.lower()
    if not text:
        return _skip_policy_decision(reason="empty_query", source="rule", latency_ms=0)

    if any(keyword in text for keyword in _RULE_SKIP_KEYWORDS):
        return _skip_policy_decision(reason="obvious_non_kb_intent", source="rule", latency_ms=0)

    # Do not make a retrieval decision solely from a sensitive-word match.
    # Route ambiguous emotional/abusive wording to the policy classifier below;
    # it can distinguish "去死吧 Roogoo" from a genuine question that quotes
    # the same phrase. The rule layer remains responsible only for obvious,
    # semantically stable intents.
    if _needs_semantic_non_kb_classification(text):
        return None

    punctuation_multi = text.count("？") + text.count("?") + text.count("；") + text.count(";")
    intent_hits = sum(1 for keyword in _RULE_MULTI_INTENT_KEYWORDS if keyword in text)
    has_connector = any(connector in text for connector in ("和", "及", "与", "、", ",", "，"))
    # Ambiguous / multi-intent → leave for policy LLM (do not short-circuit with rules).
    if punctuation_multi >= 2 or (has_connector and intent_hits >= 2):
        return None

    has_followup = any(keyword in text for keyword in _RULE_FOLLOWUP_KEYWORDS)
    has_named_entity = any(ch.isupper() for ch in text) or any(
        token in lowered for token in ("agenora", "kb", "api", "sdk", "sso", "ldap")
    )
    if has_followup and not has_named_entity:
        return None

    if len(text) > 120:
        return None

    if max_queries >= 1:
        return _direct_policy_decision(
            text,
            reason="clear_single_intent",
            source="rule",
            latency_ms=0,
        )
    return _skip_policy_decision(reason="max_queries_disabled", source="rule", latency_ms=0)


def _needs_semantic_non_kb_classification(text: str) -> bool:
    """True for emotional/abusive utterances that need intent classification.

    This is deliberately a *routing* heuristic, never the final decision.
    Presence of an information-seeking marker keeps the request on the normal
    policy path so quoted terms in a real question are not rejected by a word
    list alone.
    """
    return (
        any(keyword in text for keyword in _RULE_ABUSE_HINTS)
        and not any(marker in text for marker in _RULE_INFORMATION_SEEKING_HINTS)
    )


def _normalize_query_policy_mode(value: str | None) -> str:
    mode = (value or "llm_fallback").strip().lower()
    return mode if mode in _QUERY_POLICY_MODES else "llm_fallback"


def _normalize_policy_action(value: Any, query_count: int) -> QueryPolicyAction:
    action = str(value or "").strip().lower()
    if action in _QUERY_POLICY_ACTIONS:
        return action  # type: ignore[return-value]
    if query_count >= 2:
        return "expand"
    if query_count == 1:
        return "direct"
    return "skip_kb"


def _coerce_policy_decision(
    payload: Any,
    fallback_query: str,
    *,
    max_queries: int,
    source: QueryPolicySource,
    latency_ms: int,
) -> QueryPolicyDecision:
    data = payload if isinstance(payload, dict) else {}
    raw_action = data.get("action") if isinstance(data, dict) else None
    raw_queries = data.get("queries", []) if isinstance(data, dict) else payload
    queries = _coerce_kb_queries(raw_queries, fallback_query, max_queries=max_queries)
    action = _normalize_policy_action(raw_action, len(queries))

    if action == "skip_kb":
        queries = []
    elif action in {"direct", "normalize"}:
        queries = queries[:1] or _coerce_kb_queries([fallback_query], fallback_query, max_queries=1)
    elif action == "expand":
        queries = queries[:max_queries] or _coerce_kb_queries(
            [fallback_query], fallback_query, max_queries=1
        )
        if len(queries) <= 1:
            action = "direct"

    reason = str(data.get("reason") or action) if isinstance(data, dict) else action
    return {
        "action": action,
        "queries": queries,
        "reason": reason[:80],
        "source": source,
        "latency_ms": latency_ms,
    }


def _extract_json_object(text: str) -> Any:
    """Best-effort JSON extraction for providers that wrap JSON in prose."""
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty rewrite response")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    start_candidates = [idx for idx in (stripped.find("{"), stripped.find("[")) if idx >= 0]
    if not start_candidates:
        raise ValueError("no JSON object found")
    start = min(start_candidates)
    end = max(stripped.rfind("}"), stripped.rfind("]"))
    if end <= start:
        raise ValueError("no JSON object found")
    return json.loads(stripped[start : end + 1])


@traced("query_policy")
async def query_policy_node(
    state: AgentState,
    *,
    cost: CostTracker,
    kb_name: str = "",
    kb_description: str = "",
    llm_cfg: "UserLLMConfig | None" = None,
) -> AgentState:
    """Plan KB search with deterministic rules first, then LLM fallback."""
    from src.settings import get_settings

    start = time.perf_counter()
    user_query = _latest_user_text(state.get("messages", []))
    if not user_query:
        decision = _skip_policy_decision(reason="empty_query", source="rule", latency_ms=0)
        return _apply_query_policy_decision(state, decision, cost=cost)
    prompt_assessment = assess_prompt_injection(user_query)
    prompt_risk = state.get("prompt_injection_risk") or prompt_assessment.level
    prompt_reasons = list(state.get("prompt_injection_reasons") or prompt_assessment.reasons)
    if prompt_risk == "high":
        decision = _skip_policy_decision(
            reason="high_risk_prompt_injection",
            source="rule",
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
        next_state = _apply_query_policy_decision(state, decision, cost=cost)
        next_state["prompt_injection_risk"] = prompt_risk
        next_state["prompt_injection_reasons"] = prompt_reasons
        return next_state

    settings = get_settings()
    mode = _normalize_query_policy_mode(settings.kb_query_policy_mode)
    max_queries = _configured_max_kb_queries()

    if mode == "always_direct":
        decision = _direct_policy_decision(
            user_query,
            reason="mode_always_direct",
            source="rule",
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
        return _apply_query_policy_decision(state, decision, cost=cost)

    if mode != "always_llm":
        rule_decision = _rule_query_policy(user_query, max_queries=max_queries)
        if rule_decision is not None:
            rule_decision["latency_ms"] = int((time.perf_counter() - start) * 1000)
            return _apply_query_policy_decision(state, rule_decision, cost=cost)
        if mode == "rule_only":
            if _needs_semantic_non_kb_classification(user_query):
                decision = _skip_policy_decision(
                    reason="semantic_non_kb_classification_unavailable",
                    source="fallback",
                    latency_ms=int((time.perf_counter() - start) * 1000),
                )
                return _apply_query_policy_decision(state, decision, cost=cost)
            decision = _direct_policy_decision(
                user_query,
                reason="rule_only_uncertain_fallback_direct",
                source="fallback",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
            return _apply_query_policy_decision(state, decision, cost=cost)

    # Resolve via package so ``monkeypatch.setattr("src.harness.runtime.agent_loop.get_client", ...)`` works.
    from src.harness.runtime.agent_loop import get_client

    client = get_client(llm_cfg)
    policy_model_is_compatible = (
        (llm_cfg is not None and llm_cfg.provider == "openai-compat")
        or (llm_cfg is None and settings.llm_provider != "anthropic")
    )
    if settings.kb_query_policy_llm_model and policy_model_is_compatible:
        model = settings.kb_query_policy_llm_model
    else:
        model = pick_model(state.get("messages", []), [], llm_cfg)

    system_prompt = (
        "你是企业知识库检索策略器。请判断用户问题是否需要检索 KB，并在需要时生成检索 query。\n"
        "只输出 JSON，不要输出解释文字。\n"
        "action 只能是 direct、normalize、expand、skip_kb。\n"
        "- direct: 单一明确意图，queries 最多 1 条，通常使用原问题。\n"
        "- normalize: 追问、代词或上下文依赖，补全成 1 条明确 query。\n"
        f"- expand: 仅当问题明确包含多个独立意图时才使用，拆成最多 {max_queries} 条 query；"
        "能用 1 条就不要 expand。\n"
        "- skip_kb: 闲聊、翻译、润色、总结刚才回答、系统操作，以及没有明确事实/流程/政策问题的情绪表达、抱怨或攻击性话语；queries 为空。\n"
        "- 不要因为文本包含产品名就检索。只有用户明确询问产品事实、费用、规则、操作流程、故障或政策时才检索。\n"
        "优先 direct / normalize；不要为了“更全面”而随意 expand。\n"
        "query 必须保留用户原问题里的产品名、实体、限制条件，不要制造新主题。\n"
        'JSON 格式：{"action":"direct","queries":[{"query":"...","limit":'
        f'{_configured_kb_final_limit()}'
        '}],"reason":"short_reason"}\n'
    )
    if kb_name or kb_description:
        system_prompt += (
            "\n当前知识库信息：\n"
            f"- name: {kb_name}\n"
            f"- description: {kb_description or '(empty)'}\n"
        )

    try:
        if llm_cfg is not None:
            is_anthropic = llm_cfg.provider == "anthropic"
        else:
            is_anthropic = settings.llm_provider == "anthropic"

        async with ageneration(
            "query_policy.llm",
            model=model,
            input={"query": user_query},
        ) as gen:
            if not is_anthropic:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_query},
                    ],
                    max_tokens=512,
                )
                cost.add(model, getattr(resp, "usage", None), cfg=llm_cfg)
                text = resp.choices[0].message.content or ""
                if gen is not None:
                    gen.update(output=text, usage=getattr(resp, "usage", None))
            else:
                resp = await client.messages.create(
                    model=model,
                    max_tokens=512,
                    system=with_cache_control([{"type": "text", "text": system_prompt}], llm_cfg),
                    messages=[{"role": "user", "content": user_query}],
                )
                cost.add(model, resp.usage, cfg=llm_cfg)
                text = "\n".join(
                    block.text for block in resp.content if getattr(block, "type", "") == "text"
                )
                if gen is not None:
                    gen.update(output=text, usage=resp.usage)

        parsed = _extract_json_object(text)
        decision = _coerce_policy_decision(
            parsed,
            user_query,
            max_queries=max_queries,
            source="llm",
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
    except Exception:  # noqa: BLE001
        if _needs_semantic_non_kb_classification(user_query):
            decision = _skip_policy_decision(
                reason="semantic_non_kb_classification_failed",
                source="fallback",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
        else:
            decision = _direct_policy_decision(
                user_query,
                reason="llm_policy_failed_fallback_direct",
                source="fallback",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )

    return _apply_query_policy_decision(state, decision, cost=cost)
