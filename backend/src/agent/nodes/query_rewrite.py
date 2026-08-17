"""Query rewrite node: expand user questions into KB search queries."""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.state import AgentState
from src.infra.llm import CostTracker, pick_model, with_cache_control

from .constants import MAX_KB_REWRITE_QUERIES, _latest_user_text
from .query_policy import _coerce_kb_queries, _configured_kb_final_limit, _extract_json_object

if TYPE_CHECKING:
    from src.settings_user import UserLLMConfig


async def query_rewrite_node(
    state: AgentState,
    *,
    cost: CostTracker,
    kb_name: str = "",
    kb_description: str = "",
    llm_cfg: "UserLLMConfig | None" = None,
) -> AgentState:
    """Rewrite the latest user question into 1-3 KB search queries.

    This is an internal orchestration node, not a user-visible tool. It owns
    KB query expansion so the later reason node no longer freely calls
    ``search_kb`` multiple times.
    """
    user_query = _latest_user_text(state.get("messages", []))
    if not user_query:
        return {
            **state,
            "kb_queries": [],
            "kb_context": "",
            "retrieved_evidence": [],
            "kb_search_done": True,
        }

    model = pick_model(state.get("messages", []), [], llm_cfg)
    # Resolve via package so ``monkeypatch.setattr("src.agent.nodes.get_client", ...)`` works.
    from src.agent.nodes import get_client

    client = get_client(llm_cfg)

    system_prompt = (
        "你是知识库检索 query 改写器。你的任务是把用户问题改写成 1 到 3 条适合向量检索的查询。\n"
        "要求：\n"
        f"- 最多 {MAX_KB_REWRITE_QUERIES} 条，不能更多。\n"
        "- 保留用户问题里的关键实体、产品名、专有名词和约束。\n"
        "- 查询之间要覆盖不同检索角度，但不要制造用户没有问到的新主题。\n"
        "- 每条 query 适合直接传给 KB 向量检索。\n"
        "- 只输出 JSON，不要输出解释文字。\n"
        f'JSON 格式：{{"queries":[{{"query":"...","limit":{_configured_kb_final_limit()}}}]}}\n'
    )
    if kb_name or kb_description:
        system_prompt += (
            "\n当前知识库信息：\n"
            f"- name: {kb_name}\n"
            f"- description: {kb_description or '(empty)'}\n"
        )

    try:
        from src.settings import get_settings

        if llm_cfg is not None:
            is_anthropic = llm_cfg.provider == "anthropic"
        else:
            is_anthropic = get_settings().llm_provider == "anthropic"

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

        parsed = _extract_json_object(text)
        queries = _coerce_kb_queries(parsed, user_query)
    except Exception:  # noqa: BLE001
        queries = _coerce_kb_queries([], user_query)

    return {
        **state,
        "kb_queries": queries,
        "kb_context": "",
        "retrieved_evidence": [],
        "kb_search_done": False,
        "cost_usd": cost.total_usd,
    }
