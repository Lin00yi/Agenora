"""Request bodies for POST /api/chat."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] | None = Field(default=None)
    conversation_id: str | None = Field(default=None, max_length=36)
    kb_id: str | None = Field(default=None, description="Bind to a KB; agent uses search_kb only")
    # v3-M6: optional per-request LLM model override. Frontend reads
    # currentConv.llm_model (saved per-conversation in DB) and passes it here.
    # Server applies via dataclasses.replace() — no schema-level dependency.
    model: str | None = Field(default=None, max_length=128)
    # v5: stable user-owned model profile.  Unlike ``model`` this also
    # resolves the provider credentials, so two connections may safely expose
    # the same remote model identifier.
    model_profile_id: str | None = Field(default=None, max_length=36)
