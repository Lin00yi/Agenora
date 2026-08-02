"""Provider adapters for chat + tool-calling APIs."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from src.infra.llm import get_client, with_cache_control
from src.settings import get_settings
from src.tools.base import ToolSchema

if TYPE_CHECKING:
    from src.settings_user import UserLLMConfig


@dataclass
class LLMToolCall:
    id: str
    name: str
    input: dict[str, Any]

    def as_state(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "input": self.input}


@dataclass
class LLMToolChatResponse:
    text_parts: list[str]
    tool_calls: list[LLMToolCall]
    assistant_content: list[dict[str, Any]]
    usage: Any = None
    stop_reason: str | None = None


class LLMToolAdapter(Protocol):
    async def chat_with_tools(
        self,
        *,
        model: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
        max_tokens: int,
    ) -> LLMToolChatResponse: ...


def convert_to_openai_format(
    messages: list[dict[str, Any]],
    tools: list[ToolSchema],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert Anthropic-style tool messages and schemas to OpenAI format."""
    system = ""
    openai_messages: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")

        if role == "system":
            if isinstance(content, list):
                system = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
            else:
                system = content
            continue

        if isinstance(content, list):
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "id": block.get("id"),
                            "type": "function",
                            "function": {
                                "name": block.get("name"),
                                # OpenAI-compatible APIs require a JSON string,
                                # not Python's single-quoted dict repr.
                                "arguments": json.dumps(
                                    block.get("input", {}), ensure_ascii=False
                                ),
                            },
                        }
                    )
                elif block.get("type") == "tool_result":
                    openai_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id"),
                            "content": block.get("content", ""),
                        }
                    )

            msg_dict: dict[str, Any] = {
                "role": role,
                "content": " ".join(text_parts) if text_parts else "",
            }
            if tool_calls:
                msg_dict["tool_calls"] = tool_calls
            openai_messages.append(msg_dict)
        else:
            openai_messages.append({"role": role, "content": content})

    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": tool.get("name"),
                "description": tool.get("description"),
                "parameters": tool.get("input_schema", {}),
            },
        }
        for tool in tools
    ]

    return system, openai_messages, openai_tools


class AnthropicToolAdapter:
    def __init__(self, *, llm_cfg: "UserLLMConfig | None" = None) -> None:
        self.llm_cfg = llm_cfg
        self.client = get_client(llm_cfg)

    async def chat_with_tools(
        self,
        *,
        model: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
        max_tokens: int,
    ) -> LLMToolChatResponse:
        system_blocks = with_cache_control(
            [{"type": "text", "text": system_prompt}], self.llm_cfg
        )
        resp = await self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=messages,
            tools=tools,
        )

        text_parts: list[str] = []
        tool_calls: list[LLMToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    LLMToolCall(id=block.id, name=block.name, input=dict(block.input or {}))
                )

        return LLMToolChatResponse(
            text_parts=text_parts,
            tool_calls=tool_calls,
            assistant_content=[
                b.model_dump() if hasattr(b, "model_dump") else dict(b)
                for b in resp.content
            ],
            usage=resp.usage,
            stop_reason=getattr(resp, "stop_reason", None),
        )


class OpenAICompatToolAdapter:
    def __init__(self, *, llm_cfg: "UserLLMConfig | None" = None) -> None:
        self.client = get_client(llm_cfg)

    async def chat_with_tools(
        self,
        *,
        model: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
        max_tokens: int,
    ) -> LLMToolChatResponse:
        _, openai_messages, openai_tools = convert_to_openai_format(messages, tools)
        resp = await self.client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}] + openai_messages,
            tools=openai_tools if openai_tools else None,
            max_tokens=max_tokens,
        )

        choice = resp.choices[0]
        text_parts: list[str] = []
        tool_calls: list[LLMToolCall] = []

        if choice.message.content:
            text_parts.append(choice.message.content)

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_input: dict[str, Any] = {}
                if tc.function.arguments:
                    parsed = json.loads(tc.function.arguments)
                    if isinstance(parsed, dict):
                        tool_input = parsed
                tool_calls.append(
                    LLMToolCall(id=tc.id, name=tc.function.name, input=tool_input)
                )

        assistant_content: list[dict[str, Any]] = []
        if text_parts:
            assistant_content.append({"type": "text", "text": " ".join(text_parts)})
        for tc in tool_calls:
            assistant_content.append(
                {
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                }
            )

        return LLMToolChatResponse(
            text_parts=text_parts,
            tool_calls=tool_calls,
            assistant_content=assistant_content,
            usage=resp.usage,
            stop_reason=getattr(choice, "finish_reason", None),
        )


def create_tool_adapter(
    llm_cfg: "UserLLMConfig | None" = None,
) -> LLMToolAdapter:
    """Return the provider adapter for the current LLM configuration."""
    if llm_cfg is not None:
        provider = llm_cfg.provider
    else:
        provider = get_settings().llm_provider

    if provider == "anthropic":
        return AnthropicToolAdapter(llm_cfg=llm_cfg)
    return OpenAICompatToolAdapter(llm_cfg=llm_cfg)
