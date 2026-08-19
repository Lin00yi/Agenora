"""Provider adapters for chat + tool-calling APIs."""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

from src.models.gateway import get_client, system_blocks_with_prefix_cache_control
from src.settings import get_settings
from src.tools.base import ToolSchema

if TYPE_CHECKING:
    from src.settings_user import UserLLMConfig

OnTextDelta = Callable[[str], Awaitable[None] | None]
OnToolDetected = Callable[[], Awaitable[None] | None]


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


@dataclass
class StreamHooks:
    """Optional callbacks while consuming a provider stream.

    ``on_text_delta`` — each text chunk (final-answer path may forward to SSE).
    ``on_tool_detected`` — first signal that the model is calling tools (stop live tokens).
    """

    on_text_delta: OnTextDelta | None = None
    on_tool_detected: OnToolDetected | None = None
    _tool_notified: bool = field(default=False, repr=False)
    _first_text: bool = field(default=False, repr=False)

    async def notify_tool(self) -> None:
        if self._tool_notified:
            return
        self._tool_notified = True
        if self.on_tool_detected is not None:
            result = self.on_tool_detected()
            if result is not None:
                await result

    async def notify_text(self, text: str) -> None:
        if not text:
            return
        self._first_text = True
        if self.on_text_delta is not None:
            result = self.on_text_delta(text)
            if result is not None:
                await result


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

    async def chat_with_tools_stream(
        self,
        *,
        model: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
        max_tokens: int,
        hooks: StreamHooks | None = None,
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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mark_ttft(gen: Any) -> None:
    """Record completion_start_time on the active generation span (Langfuse TTFT)."""
    if gen is None:
        return
    now = _utcnow()
    try:
        gen.update(completion_start_time=now)
    except TypeError:
        # Older SpanHandle without the kwarg — best-effort via Langfuse obs.
        pass
    obs = getattr(gen, "observation", None)
    lf = getattr(obs, "_lf_obs", None) if obs is not None else None
    if lf is not None:
        try:
            lf.update(completion_start_time=now)
        except Exception:  # noqa: BLE001
            pass


def _finalize_generation(
    gen: Any,
    *,
    model: str,
    text_parts: list[str],
    tool_calls: list[LLMToolCall],
    usage: Any,
    llm_cfg: "UserLLMConfig | None" = None,
) -> None:
    from src.models.gateway import CostTracker

    cost_usd = None
    try:
        tracker = CostTracker()
        tracker.add(model, usage, cfg=llm_cfg)
        cost_usd = tracker.usd
    except Exception:  # noqa: BLE001
        pass
    if gen is not None:
        gen.update(
            output={"text": "\n".join(text_parts), "tool_calls": [tc.name for tc in tool_calls]},
            usage=usage,
            cost_usd=cost_usd,
        )


async def _fanout_complete_response(
    resp: LLMToolChatResponse,
    hooks: StreamHooks | None,
    gen: Any,
) -> LLMToolChatResponse:
    """Synthesize stream hooks from a non-streaming response (tests / fallback).

    Text is fanned out before tools so callers can show a thinking draft when the
    model returns both prose and tool_calls (same order as a real stream).
    """
    hooks = hooks or StreamHooks()
    if resp.text_parts:
        _mark_ttft(gen)
        for part in resp.text_parts:
            await hooks.notify_text(part)
    if resp.tool_calls:
        await hooks.notify_tool()
    return resp


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
        from src.observability import ageneration

        async with ageneration(
            "llm.chat_with_tools",
            model=model,
            input={"system": system_prompt, "messages": messages, "tools": [t.get("name") for t in tools]},
            metadata={"max_tokens": max_tokens, "provider": "anthropic"},
        ) as gen:
            system_blocks = system_blocks_with_prefix_cache_control(system_prompt, self.llm_cfg)
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

            _finalize_generation(
                gen, model=model, text_parts=text_parts, tool_calls=tool_calls, usage=resp.usage,
                llm_cfg=self.llm_cfg,
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

    async def chat_with_tools_stream(
        self,
        *,
        model: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
        max_tokens: int,
        hooks: StreamHooks | None = None,
    ) -> LLMToolChatResponse:
        from src.observability import ageneration

        hooks = hooks or StreamHooks()
        async with ageneration(
            "llm.chat_with_tools",
            model=model,
            input={"system": system_prompt, "messages": messages, "tools": [t.get("name") for t in tools]},
            metadata={"max_tokens": max_tokens, "provider": "anthropic", "stream": True},
        ) as gen:
            system_blocks = system_blocks_with_prefix_cache_control(system_prompt, self.llm_cfg)

            # Prefer SDK stream helper; fall back to create(stream=True) / non-stream mocks.
            stream_cm = getattr(self.client.messages, "stream", None)
            if stream_cm is not None:
                try:
                    async with stream_cm(
                        model=model,
                        max_tokens=max_tokens,
                        system=system_blocks,
                        messages=messages,
                        tools=tools or None,
                    ) as stream:
                        ttft_marked = False
                        async for event in stream:
                            et = getattr(event, "type", None)
                            if et == "content_block_start":
                                block = getattr(event, "content_block", None)
                                btype = getattr(block, "type", None)
                                if btype == "tool_use":
                                    await hooks.notify_tool()
                            elif et == "content_block_delta":
                                delta = getattr(event, "delta", None)
                                dtype = getattr(delta, "type", None)
                                if dtype == "text_delta":
                                    text = getattr(delta, "text", "") or ""
                                    if text and not ttft_marked:
                                        _mark_ttft(gen)
                                        ttft_marked = True
                                    if text and not hooks._tool_notified:
                                        await hooks.notify_text(text)
                        final = await stream.get_final_message()
                        return self._response_from_anthropic_message(final, gen=gen, model=model)
                except (AttributeError, TypeError, NotImplementedError):
                    # Incomplete client mocks — fall through to non-stream create.
                    pass

            resp = await self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_blocks,
                messages=messages,
                tools=tools,
            )
            # Streaming create() may return an async iterator.
            if hasattr(resp, "__aiter__"):
                return await self._consume_anthropic_event_stream(
                    resp, hooks=hooks, gen=gen, model=model
                )
            parsed = self._parse_anthropic_message(resp)
            _finalize_generation(
                gen,
                model=model,
                text_parts=parsed.text_parts,
                tool_calls=parsed.tool_calls,
                usage=parsed.usage,
                llm_cfg=self.llm_cfg,
            )
            return await _fanout_complete_response(parsed, hooks, gen)

    def _parse_anthropic_message(self, resp: Any) -> LLMToolChatResponse:
        text_parts: list[str] = []
        tool_calls: list[LLMToolCall] = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(block.text)
            elif getattr(block, "type", None) == "tool_use":
                tool_calls.append(
                    LLMToolCall(
                        id=block.id,
                        name=block.name,
                        input=dict(getattr(block, "input", None) or {}),
                    )
                )
        return LLMToolChatResponse(
            text_parts=text_parts,
            tool_calls=tool_calls,
            assistant_content=[
                b.model_dump() if hasattr(b, "model_dump") else dict(b)
                for b in resp.content
            ],
            usage=getattr(resp, "usage", None),
            stop_reason=getattr(resp, "stop_reason", None),
        )

    def _response_from_anthropic_message(
        self, resp: Any, *, gen: Any, model: str
    ) -> LLMToolChatResponse:
        parsed = self._parse_anthropic_message(resp)
        _finalize_generation(
            gen,
            model=model,
            text_parts=parsed.text_parts,
            tool_calls=parsed.tool_calls,
            usage=parsed.usage,
            llm_cfg=self.llm_cfg,
        )
        return parsed

    async def _consume_anthropic_event_stream(
        self,
        stream: Any,
        *,
        hooks: StreamHooks,
        gen: Any,
        model: str,
    ) -> LLMToolChatResponse:
        ttft_marked = False
        # Collect via final message if available; else rebuild from events.
        final = None
        async for event in stream:
            et = getattr(event, "type", None)
            if et == "content_block_start":
                block = getattr(event, "content_block", None)
                if getattr(block, "type", None) == "tool_use":
                    await hooks.notify_tool()
            elif et == "content_block_delta":
                delta = getattr(event, "delta", None)
                if getattr(delta, "type", None) == "text_delta":
                    text = getattr(delta, "text", "") or ""
                    if text and not ttft_marked:
                        _mark_ttft(gen)
                        ttft_marked = True
                    if text and not hooks._tool_notified:
                        await hooks.notify_text(text)
            elif et == "message_stop":
                final = getattr(event, "message", None)
            get_final = getattr(stream, "get_final_message", None)
            if get_final is None and et == "message":
                final = getattr(event, "message", event)

        if final is None and hasattr(stream, "get_final_message"):
            final = await stream.get_final_message()
        if final is None:
            raise RuntimeError("anthropic stream ended without a final message")
        return self._response_from_anthropic_message(final, gen=gen, model=model)


class OpenAICompatToolAdapter:
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
        from src.observability import ageneration

        async with ageneration(
            "llm.chat_with_tools",
            model=model,
            input={"system": system_prompt, "messages": messages, "tools": [t.get("name") for t in tools]},
            metadata={"max_tokens": max_tokens, "provider": "openai-compat"},
        ) as gen:
            _, openai_messages, openai_tools = convert_to_openai_format(messages, tools)
            resp = await self.client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system_prompt}] + openai_messages,
                tools=openai_tools if openai_tools else None,
                max_tokens=max_tokens,
            )
            parsed = self._parse_openai_response(resp)
            _finalize_generation(
                gen,
                model=model,
                text_parts=parsed.text_parts,
                tool_calls=parsed.tool_calls,
                usage=parsed.usage,
                llm_cfg=self.llm_cfg,
            )
            return parsed

    async def chat_with_tools_stream(
        self,
        *,
        model: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
        max_tokens: int,
        hooks: StreamHooks | None = None,
    ) -> LLMToolChatResponse:
        from src.observability import ageneration

        hooks = hooks or StreamHooks()
        async with ageneration(
            "llm.chat_with_tools",
            model=model,
            input={"system": system_prompt, "messages": messages, "tools": [t.get("name") for t in tools]},
            metadata={"max_tokens": max_tokens, "provider": "openai-compat", "stream": True},
        ) as gen:
            _, openai_messages, openai_tools = convert_to_openai_format(messages, tools)
            create_kwargs: dict[str, Any] = {
                "model": model,
                "messages": [{"role": "system", "content": system_prompt}] + openai_messages,
                "tools": openai_tools if openai_tools else None,
                "max_tokens": max_tokens,
                "stream": True,
            }
            # Best-effort: some providers support usage on the last chunk.
            try:
                resp = await self.client.chat.completions.create(
                    **create_kwargs,
                    stream_options={"include_usage": True},
                )
            except TypeError:
                resp = await self.client.chat.completions.create(**create_kwargs)

            if not hasattr(resp, "__aiter__"):
                # Unit-test mocks often ignore stream=True and return a full response.
                parsed = self._parse_openai_response(resp)
                _finalize_generation(
                    gen,
                    model=model,
                    text_parts=parsed.text_parts,
                    tool_calls=parsed.tool_calls,
                    usage=parsed.usage,
                    llm_cfg=self.llm_cfg,
                )
                return await _fanout_complete_response(parsed, hooks, gen)

            return await self._consume_openai_stream(resp, hooks=hooks, gen=gen, model=model)

    def _parse_openai_response(self, resp: Any) -> LLMToolChatResponse:
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
            usage=getattr(resp, "usage", None),
            stop_reason=getattr(choice, "finish_reason", None),
        )

    async def _consume_openai_stream(
        self,
        stream: Any,
        *,
        hooks: StreamHooks,
        gen: Any,
        model: str,
    ) -> LLMToolChatResponse:
        text_acc: list[str] = []
        # index -> {id, name, arguments}
        tool_acc: dict[int, dict[str, str]] = {}
        usage: Any = None
        stop_reason: str | None = None
        ttft_marked = False

        async for chunk in stream:
            if getattr(chunk, "usage", None) is not None:
                usage = chunk.usage
            if not getattr(chunk, "choices", None):
                continue
            choice = chunk.choices[0]
            fr = getattr(choice, "finish_reason", None)
            if fr:
                stop_reason = fr
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue

            if getattr(delta, "tool_calls", None):
                await hooks.notify_tool()
                for tc in delta.tool_calls:
                    idx = getattr(tc, "index", 0) or 0
                    slot = tool_acc.setdefault(
                        idx, {"id": "", "name": "", "arguments": ""}
                    )
                    if getattr(tc, "id", None):
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            slot["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            slot["arguments"] += fn.arguments

            content = getattr(delta, "content", None)
            if content:
                if not ttft_marked:
                    _mark_ttft(gen)
                    ttft_marked = True
                text_acc.append(content)
                if not hooks._tool_notified:
                    await hooks.notify_text(content)

        tool_calls: list[LLMToolCall] = []
        for idx in sorted(tool_acc.keys()):
            slot = tool_acc[idx]
            tool_input: dict[str, Any] = {}
            raw = slot.get("arguments") or ""
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        tool_input = parsed
                except json.JSONDecodeError:
                    tool_input = {"_raw": raw}
            tool_calls.append(
                LLMToolCall(
                    id=slot.get("id") or f"call_{idx}",
                    name=slot.get("name") or "unknown",
                    input=tool_input,
                )
            )

        text_parts = ["".join(text_acc)] if text_acc else []
        # If tools won, drop text_parts for state consistency with non-stream path
        # when providers send both (reason_node prefers tool_calls).
        assistant_content: list[dict[str, Any]] = []
        if text_parts and not tool_calls:
            assistant_content.append({"type": "text", "text": text_parts[0]})
        elif text_parts and tool_calls:
            assistant_content.append({"type": "text", "text": text_parts[0]})
        for tc in tool_calls:
            assistant_content.append(
                {
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                }
            )

        parsed = LLMToolChatResponse(
            text_parts=text_parts,
            tool_calls=tool_calls,
            assistant_content=assistant_content,
            usage=usage,
            stop_reason=stop_reason,
        )
        _finalize_generation(
            gen,
            model=model,
            text_parts=parsed.text_parts,
            tool_calls=parsed.tool_calls,
            usage=parsed.usage,
            llm_cfg=self.llm_cfg,
        )
        return parsed


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
