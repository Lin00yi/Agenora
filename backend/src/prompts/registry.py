"""Named prompt lookup."""

from src.prompts.system import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_GENERAL,
    build_kb_reason_system_prompt,
    build_kb_system_prompt,
)

PROMPTS = {
    "chat.system": SYSTEM_PROMPT_GENERAL,
    "chat.system.legacy": SYSTEM_PROMPT,
}

__all__ = [
    "PROMPTS",
    "SYSTEM_PROMPT",
    "SYSTEM_PROMPT_GENERAL",
    "build_kb_reason_system_prompt",
    "build_kb_system_prompt",
]
