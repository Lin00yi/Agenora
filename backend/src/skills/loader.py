"""Skill loader — loads SKILL.md and invokes via a second LLM call (no tools)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.context import (
    MAX_OUTPUT_TOKENS,
    estimate_tokens,
    resolve_output_token_budget,
)
from src.models.gateway import get_client, pick_model, with_cache_control
from src.settings import get_settings

if TYPE_CHECKING:
    from src.settings_user import UserLLMConfig

SKILLS_DIR = Path(__file__).parent
_SKILL_CACHE: dict[str, str] = {}


def load_skill_md(skill_name: str) -> str:
    if skill_name in _SKILL_CACHE:
        return _SKILL_CACHE[skill_name]
    path = SKILLS_DIR / skill_name / "SKILL.md"
    if not path.exists():
        raise FileNotFoundError(f"Skill not found: {skill_name} at {path}")
    content = path.read_text(encoding="utf-8")
    _SKILL_CACHE[skill_name] = content
    return content


async def invoke_skill(
    skill_name: str,
    args: dict[str, Any],
    *,
    llm_cfg: "UserLLMConfig | None" = None,
) -> str:
    """Invoke skill by sending SKILL.md + args to LLM (no tools, text only).

    v2-M8: prompt is generic. Templates carry their own heading conventions
    in SKILL.md so the LLM picks them up.
    v2-M8: also accepts `llm_cfg` so per-user LLM (v2-M1) routes through
    the skill call too, not just the planner step.
    """
    s = get_settings()
    skill_md = load_skill_md(skill_name)
    client = get_client(llm_cfg)
    model = pick_model([], [], llm_cfg)

    user_prompt = (
        "请根据下方的输入数据，按下方模板格式直接输出最终的 Markdown 报告。\n\n"
        "重要规则：\n"
        "1. 直接输出最终报告内容，不要输出模板本身\n"
        "2. 不要输出 SKILL 元数据 (---name: xxx---)\n"
        "3. 不要解释你在做什么，直接输出 `## ` 开头的报告\n"
        "4. 用真实数据填充模板里所有 {{xxx}} 形式的占位符\n"
        "5. {{#each xxx}} ... {{/each}} 循环段全部展开列出，不要保留模板语法\n\n"
        f"=== 模板格式参考 ===\n{skill_md}\n=== 模板结束 ===\n\n"
        f"=== 输入数据 ===\n{json.dumps(args, ensure_ascii=False, indent=2)}\n"
        "=== 数据结束 ===\n\n"
        "现在请直接输出最终的 Markdown 报告："
    )

    system_msg = (
        "你是 Markdown 报告生成助手。你的任务是把结构化数据填入模板，"
        "直接输出最终的 Markdown 报告。绝对不要原样输出模板内容或元数据。"
    )

    # Provider routing — user cfg wins; env fallback otherwise.
    if llm_cfg is not None:
        is_anthropic = llm_cfg.provider == "anthropic"
    else:
        is_anthropic = s.llm_provider == "anthropic"
    output_budget = resolve_output_token_budget(
        model=model,
        configured_window=getattr(llm_cfg, "context_window", None) if llm_cfg else None,
        task="report",
        reserved_prompt_tokens=estimate_tokens(system_msg) + estimate_tokens(user_prompt),
    )

    if not is_anthropic:
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_prompt},
        ]
        text, hit_limit = await _openai_text_completion(
            client,
            model=model,
            messages=messages,
            max_tokens=output_budget,
        )
        if hit_limit:
            text = await _auto_continue_openai_text(
                client,
                model=model,
                messages=messages,
                initial_text=text,
                max_tokens=output_budget,
            )
        return text

    system_blocks = with_cache_control([{"type": "text", "text": system_msg}], llm_cfg)
    messages = [{"role": "user", "content": user_prompt}]
    text, hit_limit = await _anthropic_text_completion(
        client,
        model=model,
        system=system_blocks,
        messages=messages,
        max_tokens=output_budget,
    )
    if hit_limit:
        text = await _auto_continue_anthropic_text(
            client,
            model=model,
            system=system_blocks,
            messages=messages,
            initial_text=text,
            max_tokens=output_budget,
        )
    return text


async def _openai_text_completion(
    client: Any,
    *,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> tuple[str, bool]:
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        if max_tokens > MAX_OUTPUT_TOKENS and _looks_like_output_budget_rejection(exc):
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
        else:
            raise
    choice = resp.choices[0]
    return choice.message.content or "", getattr(choice, "finish_reason", None) == "length"


async def _anthropic_text_completion(
    client: Any,
    *,
    model: str,
    system: list[dict[str, Any]],
    messages: list[dict[str, str]],
    max_tokens: int,
) -> tuple[str, bool]:
    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
    except Exception as exc:  # noqa: BLE001
        if max_tokens > MAX_OUTPUT_TOKENS and _looks_like_output_budget_rejection(exc):
            resp = await client.messages.create(
                model=model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system,
                messages=messages,
            )
        else:
            raise
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    return text, getattr(resp, "stop_reason", None) == "max_tokens"


async def _auto_continue_openai_text(
    client: Any,
    *,
    model: str,
    messages: list[dict[str, str]],
    initial_text: str,
    max_tokens: int,
) -> str:
    parts = [initial_text.rstrip()]
    continuation_messages = [
        *messages,
        {"role": "assistant", "content": parts[-1]},
        {"role": "user", "content": _continuation_prompt()},
    ]
    for _ in range(2):
        text, hit_limit = await _openai_text_completion(
            client,
            model=model,
            messages=continuation_messages,
            max_tokens=max_tokens,
        )
        text = text.strip()
        if not text:
            break
        parts.append(text)
        if not hit_limit:
            return "\n\n".join(part for part in parts if part)
        continuation_messages.extend(
            [
                {"role": "assistant", "content": text},
                {"role": "user", "content": _continuation_prompt()},
            ]
        )
    return _append_output_limit_notice("\n\n".join(part for part in parts if part))


async def _auto_continue_anthropic_text(
    client: Any,
    *,
    model: str,
    system: list[dict[str, Any]],
    messages: list[dict[str, str]],
    initial_text: str,
    max_tokens: int,
) -> str:
    parts = [initial_text.rstrip()]
    continuation_messages = [
        *messages,
        {"role": "assistant", "content": parts[-1]},
        {"role": "user", "content": _continuation_prompt()},
    ]
    for _ in range(2):
        text, hit_limit = await _anthropic_text_completion(
            client,
            model=model,
            system=system,
            messages=continuation_messages,
            max_tokens=max_tokens,
        )
        text = text.strip()
        if not text:
            break
        parts.append(text)
        if not hit_limit:
            return "\n\n".join(part for part in parts if part)
        continuation_messages.extend(
            [
                {"role": "assistant", "content": text},
                {"role": "user", "content": _continuation_prompt()},
            ]
        )
    return _append_output_limit_notice("\n\n".join(part for part in parts if part))


def _looks_like_output_budget_rejection(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "max_tokens",
            "maximum",
            "context_length",
            "too many tokens",
            "token limit",
            "requested tokens",
        )
    )


def _continuation_prompt() -> str:
    return (
        "上一段回答因为输出长度限制中断。请从断点继续补全，"
        "不要重复已经输出过的内容，不要重新开头，只输出后续内容。"
    )


def _append_output_limit_notice(text: str) -> str:
    notice = (
        "\n\n> 回答可能因输出长度限制被截断。"
        "请继续追问“继续”，我会从上次中断处补全。"
    )
    if notice.strip() in text:
        return text
    return text.rstrip() + notice
