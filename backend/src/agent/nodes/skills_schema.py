"""Legacy plan_node alias for older tests."""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.prompts import SYSTEM_PROMPT
from src.agent.state import AgentState
from src.infra.llm import CostTracker
from src.tools.base import ToolRegistry

if TYPE_CHECKING:
    from src.settings_user import UserLLMConfig


async def plan_node(
    state: AgentState,
    *,
    registry: ToolRegistry,
    cost: CostTracker,
    system_prompt: str = SYSTEM_PROMPT,
    llm_cfg: "UserLLMConfig | None" = None,
) -> AgentState:
    """Backward-compatible alias for the legacy graph/tests."""
    from .reason import reason_node

    return await reason_node(
        state,
        registry=registry,
        cost=cost,
        system_prompt=system_prompt,
        llm_cfg=llm_cfg,
    )
