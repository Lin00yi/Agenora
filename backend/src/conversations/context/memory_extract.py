"""Rule- and LLM-based memory candidate extraction."""
from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import TYPE_CHECKING, Any

from src.conversations.models import Message

from .constants import (
    MAX_MEMORY_EXTRACTION_SOURCE_CHARS,
    SENSITIVE_PATTERNS,
    MemoryCandidate,
)

if TYPE_CHECKING:
    from src.settings_user import UserLLMConfig

def contains_sensitive_memory_content(text: str) -> bool:
    return any(pattern.search(text) for pattern in SENSITIVE_PATTERNS)


def extract_explicit_memory_candidate(text: str) -> str | None:
    """Extract only user-explicit memory requests.

    This avoids silently persisting arbitrary conversation facts. Richer
    candidate extraction can be added later behind user-visible controls.
    """
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return None

    patterns = [
        r"^(?:请你?|帮我)?记住[:：\s]*(.+)$",
        r"^以后(?:请)?记住[:：\s]*(.+)$",
        r"^请把(?:这点|这个|以下内容)?记到长期记忆[:：\s]*(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, cleaned)
        if match:
            candidate = match.group(1).strip()
            if 4 <= len(candidate) <= 500 and not contains_sensitive_memory_content(candidate):
                return candidate
    return None


def _is_question(text: str) -> bool:
    return text.rstrip().endswith(("?", "？", "吗", "么")) or bool(
        re.search(r"能否|可不可以|是否|怎么", text)
    )


def _stable_key(prefix: str, value: str) -> str:
    digest = sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _language_value(value: str) -> str:
    normalized = value.lower()
    if normalized in {"中文", "汉语", "chinese"}:
        return "zh-CN"
    return "en"


# Canonical constraint topics. Same topic + scope → one active value (supersede).
CONSTRAINT_TOPICS: dict[str, tuple[str, ...]] = {
    "stack.database": (
        "postgresql",
        "postgres",
        "mysql",
        "mariadb",
        "mongodb",
        "mongo",
        "redis",
        "sqlite",
        "cockroach",
        "数据库",
        "持久化",
    ),
    "stack.backend": (
        "fastapi",
        "django",
        "flask",
        "express",
        "nestjs",
        "spring boot",
        "springboot",
        "后端框架",
    ),
    "stack.frontend": (
        "react",
        "vue",
        "next.js",
        "nextjs",
        "nuxt",
        "angular",
        "svelte",
        "前端框架",
    ),
    "stack.language": (
        "python",
        "typescript",
        "javascript",
        "golang",
        "rust",
        "kotlin",
        "java",
        "go语言",
    ),
    "stack.orm": (
        "sqlalchemy",
        "prisma",
        "typeorm",
        "hibernate",
        "gorm",
        "django orm",
    ),
    "stack.vector": (
        "milvus",
        "qdrant",
        "pinecone",
        "weaviate",
        "向量库",
        "vector store",
        "vector database",
    ),
    "policy.testing": (
        "pytest",
        "jest",
        "vitest",
        "unittest",
        "单测",
        "单元测试",
        "测试覆盖",
    ),
    "policy.ci": (
        "github actions",
        "gitlab ci",
        "ci/cd",
        "持续集成",
        "jenkins",
    ),
    "policy.security": (
        "禁止提交密钥",
        "不得明文",
        "强制 https",
        "禁止硬编码",
        "no plaintext secret",
    ),
}

CONSTRAINT_TOPIC_ALIASES: dict[str, str] = {
    "database": "stack.database",
    "db": "stack.database",
    "postgres": "stack.database",
    "postgresql": "stack.database",
    "mysql": "stack.database",
    "mongodb": "stack.database",
    "backend": "stack.backend",
    "framework": "stack.backend",
    "fastapi": "stack.backend",
    "django": "stack.backend",
    "frontend": "stack.frontend",
    "react": "stack.frontend",
    "language": "stack.language",
    "lang": "stack.language",
    "python": "stack.language",
    "typescript": "stack.language",
    "orm": "stack.orm",
    "vector": "stack.vector",
    "embedding_store": "stack.vector",
    "testing": "policy.testing",
    "test": "policy.testing",
    "ci": "policy.ci",
    "cd": "policy.ci",
    "security": "policy.security",
}


def _strip_constraint_key_prefix(key: str) -> str:
    raw = key.strip().lower().replace("_", ".").replace(" ", ".")
    for prefix in ("constraint.", "constraint:", "topic.", "topic:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
    return raw.strip(".")


def infer_constraint_topic(*texts: str) -> str | None:
    """Infer a canonical topic from free-form constraint text.

    Longer keyword matches win so ``spring boot`` beats ``spring``-style
    collisions when both are present. Returns ``None`` when no topic keyword hits.
    """
    haystack = " ".join(part for part in texts if part).lower()
    if not haystack:
        return None
    best_topic: str | None = None
    best_len = 0
    for topic, keywords in CONSTRAINT_TOPICS.items():
        for keyword in keywords:
            if keyword.lower() in haystack and len(keyword) > best_len:
                best_topic = topic
                best_len = len(keyword)
    return best_topic


def normalize_constraint_key(key: str | None = None, *texts: str) -> str:
    """Map a constraint to ``constraint.<topic>`` for supersede-friendly writes.

    Unknown topics fall back to a content hash under ``constraint.misc:`` so
    unrelated free-form rules still do not collide with each other.
    """
    stripped = _strip_constraint_key_prefix(key or "")
    if stripped in CONSTRAINT_TOPICS:
        return f"constraint.{stripped}"
    if stripped in CONSTRAINT_TOPIC_ALIASES:
        return f"constraint.{CONSTRAINT_TOPIC_ALIASES[stripped]}"
    inferred = infer_constraint_topic(stripped, *texts)
    if inferred:
        return f"constraint.{inferred}"
    seed = " ".join(part for part in (key, *texts) if part).strip() or "constraint"
    return _stable_key("constraint.misc", seed)


def _constraint_topic_for_candidate(candidate: MemoryCandidate) -> str | None:
    return constraint_topic_from_memory_key(candidate.key) or infer_constraint_topic(
        candidate.key, candidate.value, candidate.content
    )


def constraint_topic_from_memory_key(memory_key: str | None) -> str | None:
    """Return the topic segment for a stored constraint key, if structured."""
    if not memory_key:
        return None
    stripped = _strip_constraint_key_prefix(memory_key)
    if stripped in CONSTRAINT_TOPICS:
        return stripped
    if stripped.startswith("misc:") or stripped.startswith("misc."):
        return None
    # Legacy ``constraint:<hash>`` has no topic.
    if re.fullmatch(r"[0-9a-f]{12,64}", stripped):
        return None
    return stripped if stripped in CONSTRAINT_TOPICS else None


def extract_memory_candidates(text: str) -> list[MemoryCandidate]:
    """Silently extract only stable, user-authored, high-confidence memories.

    The rules intentionally favour precision over recall: a false positive is
    more harmful than asking a user to repeat a preference once. Explicit
    ``记住`` commands always qualify; implicit capture requires future/default
    language that signals a durable preference or constraint.
    """
    cleaned = " ".join((text or "").strip().split())
    if not cleaned or contains_sensitive_memory_content(cleaned):
        return []

    explicit = extract_explicit_memory_candidate(cleaned)
    if explicit:
        # Promote project constraints phrased as ``记住：…`` into the structured
        # constraint lane when a topic can be inferred; otherwise keep explicit.
        if re.search(r"(?:项目|团队|代码库).{0,36}?(必须|禁止|不可|不能|统一使用)", explicit):
            topic_key = normalize_constraint_key(None, explicit)
            if not topic_key.startswith("constraint.misc:"):
                return [
                    MemoryCandidate(
                        type="constraint",
                        key=topic_key,
                        value=explicit,
                        content=f"项目约束：{explicit}。",
                        confidence=0.92,
                        importance=0.9,
                        source="explicit",
                        scope="kb",
                        expires_in_days=180,
                    )
                ]
        return [
            MemoryCandidate(
                type="explicit",
                key=_stable_key("explicit", explicit),
                value=explicit,
                content=explicit,
                confidence=0.95,
                importance=0.8,
                source="explicit",
            )
        ]
    if _is_question(cleaned):
        return []

    candidates: list[MemoryCandidate] = []
    future_marker = r"(?:以后|今后|之后|默认|长期|一直)"

    language = re.search(
        future_marker + r".{0,20}?(?:使用|用|回复|回答|输出|写)(中文|汉语|英文|English|Chinese)",
        cleaned,
        re.IGNORECASE,
    )
    if language:
        value = _language_value(language.group(1))
        display = "中文" if value == "zh-CN" else "英文"
        candidates.append(
            MemoryCandidate(
                type="preference",
                key="response_language",
                value=value,
                content=f"用户偏好使用{display}回复。",
                confidence=0.86,
                importance=0.9,
                source="auto_rule",
                expires_in_days=180,
            )
        )

    style = re.search(
        future_marker + r".{0,24}?(简洁|详细|专业|口语化)(?:回复|回答|输出|报告|说明)?",
        cleaned,
    )
    if style:
        value = style.group(1)
        candidates.append(
            MemoryCandidate(
                type="preference",
                key="response_style",
                value=value,
                content=f"用户偏好{value}的回复风格。",
                confidence=0.82,
                importance=0.75,
                source="auto_rule",
                expires_in_days=180,
            )
        )

    length = re.search(
        future_marker + r".{0,30}?(?:控制在|不超过|少于)\s*(\d{2,5})\s*字", cleaned
    )
    if length:
        value = length.group(1)
        candidates.append(
            MemoryCandidate(
                type="preference",
                key="response_max_chars",
                value=value,
                content=f"用户偏好回复控制在 {value} 字以内。",
                confidence=0.84,
                importance=0.75,
                source="auto_rule",
                expires_in_days=180,
            )
        )

    constraint = re.search(
        r"(?:项目|团队|代码库).{0,36}?(必须|禁止|不可|不能|统一使用)\s*(.{4,160})", cleaned
    )
    if constraint:
        value = f"{constraint.group(1)} {constraint.group(2).rstrip('。.!！')}"
        candidates.append(
            MemoryCandidate(
                type="constraint",
                key=normalize_constraint_key(None, value, cleaned),
                value=value,
                content=f"项目约束：{value}。",
                confidence=0.8,
                importance=0.9,
                source="auto_rule",
                scope="kb",
                expires_in_days=180,
            )
        )

    # A message can state the same preference twice; retain one candidate per
    # structured key so writes are deterministic.
    unique: dict[str, MemoryCandidate] = {}
    for candidate in candidates:
        unique[candidate.key] = candidate
    return list(unique.values())


def _memory_extraction_source(
    messages: list[Message], *, max_chars: int = MAX_MEMORY_EXTRACTION_SOURCE_CHARS
) -> str:
    lines: list[str] = []
    for message in messages:
        if message.role != "user":
            continue
        text = " ".join((message.content or "").split())
        if not text:
            continue
        lines.append(f"[message_id={message.id}] {text[:1200]}")
    source = "\n".join(lines)
    if len(source) <= max_chars:
        return source
    head = source[: max_chars // 2].rsplit("\n", 1)[0]
    tail = source[-(max_chars // 2) :].split("\n", 1)[-1]
    return f"{head}\n[older messages omitted]\n{tail}"


def _parse_json_array_from_text(text: str) -> list[Any]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    try:
        parsed = json.loads(cleaned)
    except ValueError:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start < 0 or end <= start:
            return []
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except ValueError:
            return []
    return parsed if isinstance(parsed, list) else []


def _coerce_llm_memory_candidate(item: Any) -> MemoryCandidate | None:
    if not isinstance(item, dict):
        return None
    memory_type = str(item.get("type") or "explicit").strip().lower()
    if memory_type not in {"explicit", "preference", "constraint", "fact"}:
        return None
    value = " ".join(str(item.get("value") or "").split())
    content = " ".join(str(item.get("content") or value).split())
    if len(value) < 2 or len(content) < 4 or len(content) > 500:
        return None
    if contains_sensitive_memory_content(value) or contains_sensitive_memory_content(content):
        return None
    try:
        confidence = float(item.get("confidence", 0.0))
        importance = float(item.get("importance", 0.5))
    except (TypeError, ValueError):
        return None
    if confidence < 0.72:
        return None
    raw_key = " ".join(str(item.get("key") or "").split())[:128]
    if memory_type == "constraint":
        key = normalize_constraint_key(raw_key, value, content)
    elif raw_key:
        key = raw_key
    else:
        key = _stable_key(memory_type, value)
    scope = str(item.get("scope") or "personal").strip().lower()
    if scope not in {"personal", "kb"}:
        scope = "personal"
    expires_in_days = item.get("expires_in_days")
    try:
        expires = int(expires_in_days) if expires_in_days is not None else None
    except (TypeError, ValueError):
        expires = None
    return MemoryCandidate(
        type=memory_type,
        key=key,
        value=value[:500],
        content=content,
        confidence=max(0.0, min(1.0, confidence)),
        importance=max(0.0, min(1.0, importance)),
        source="auto_session",
        scope=scope,
        expires_in_days=expires if expires and expires > 0 else None,
    )


async def extract_conversation_memory_candidates_with_llm(
    messages: list[Message],
    *,
    llm_cfg: "UserLLMConfig | None" = None,
) -> list[MemoryCandidate]:
    """Best-effort whole-conversation memory extraction.

    The realtime path stays conservative and rule-based. This lower-frequency
    pass can spend a small no-tool LLM call to improve recall after a
    conversation is done or idle.
    """
    from src.infra.llm import get_client, pick_model, with_cache_control
    from src.settings import get_settings

    source = _memory_extraction_source(messages)
    if not source:
        return []

    settings = get_settings()
    if llm_cfg is None:
        has_system_key = bool(
            settings.deepseek_api_key
            if settings.llm_provider == "deepseek"
            else settings.anthropic_api_key
        )
        if not has_system_key:
            return []

    system_prompt = (
        "Extract durable user memory candidates from the transcript. "
        "Keep only stable preferences, explicit remember requests, profile facts, "
        "or project constraints that will still matter in future conversations. "
        "Do not store passwords, tokens, API keys, payment data, government IDs, "
        "medical/legal/financial advice, transient questions, or assistant claims. "
        "Return only a JSON array. Each item must have: type, key, value, content, "
        "confidence, importance, scope. Optional: expires_in_days. "
        "Use type one of explicit, preference, constraint, fact. "
        "For preference keys prefer: response_language, response_style, response_max_chars. "
        "For constraint keys use a topic from: stack.database, stack.backend, "
        "stack.frontend, stack.language, stack.orm, stack.vector, policy.testing, "
        "policy.ci, policy.security. Example constraint key: stack.database. "
        "Use scope personal unless the memory is clearly tied to the current KB/project."
    )
    user_prompt = (
        "<transcript>\n"
        f"{source}\n"
        "</transcript>\n\n"
        "Return JSON only. Example: "
        '[{"type":"preference","key":"response_language","value":"zh-CN",'
        '"content":"User prefers Chinese responses.","confidence":0.86,'
        '"importance":0.9,"scope":"personal","expires_in_days":180},'
        '{"type":"constraint","key":"stack.database","value":"PostgreSQL",'
        '"content":"Project must use PostgreSQL.","confidence":0.88,'
        '"importance":0.9,"scope":"kb","expires_in_days":180}]'
    )
    try:
        client = get_client(llm_cfg)
        model = pick_model([], [], llm_cfg)
        is_anthropic = (
            llm_cfg.provider == "anthropic" if llm_cfg else settings.llm_provider == "anthropic"
        )
        if not is_anthropic:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=900,
            )
            text = response.choices[0].message.content or ""
        else:
            response = await client.messages.create(
                model=model,
                max_tokens=900,
                system=with_cache_control([{"type": "text", "text": system_prompt}], llm_cfg),
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = "".join(
                block.text for block in response.content if getattr(block, "type", None) == "text"
            )
    except Exception:  # noqa: BLE001 - extraction must not block chat/maintenance
        return []

    unique: dict[str, MemoryCandidate] = {}
    for item in _parse_json_array_from_text(text):
        candidate = _coerce_llm_memory_candidate(item)
        if candidate:
            unique[candidate.key] = candidate
    return list(unique.values())[:12]

