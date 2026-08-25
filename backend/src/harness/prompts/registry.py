"""Prompt Registry use cases and safe runtime resolution."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import re
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.harness.prompts.models import PromptTemplate, PromptTemplateAuditEvent, PromptTemplateVersion
from src.harness.prompts.system import (
    PROMPT_KEY_GRAPH_EXTRACTION,
    PROMPT_KEY_GENERAL,
    PROMPT_KEY_KNOWLEDGE_BASE_ROUTING,
    PROMPT_KEY_RUNTIME_SCOPE,
    PROMPT_KEY_MEMORY_EXTRACTION,
    PROMPT_KEY_CONVERSATION_COMPRESSION,
    PROMPT_KEY_KNOWLEDGE_BASE,
    default_prompt_template,
)


@dataclass(frozen=True, slots=True)
class PromptDefinition:
    key: str
    display_name: str
    description: str
    allowed_variables: tuple[str, ...]


PROMPT_DEFINITIONS: tuple[PromptDefinition, ...] = (
    PromptDefinition(
        key=PROMPT_KEY_GENERAL,
        display_name="通用对话",
        description="未绑定知识库时的回答角色、表达方式和公开信息使用规则。",
        allowed_variables=(),
    ),
    PromptDefinition(
        key=PROMPT_KEY_KNOWLEDGE_BASE,
        display_name="知识库问答",
        description="绑定或自动路由到知识库后的检索、回答与来源展示规则。",
        allowed_variables=("kb_name", "kb_description"),
    ),
    PromptDefinition(
        key=PROMPT_KEY_GRAPH_EXTRACTION,
        display_name="知识图谱抽取",
        description="从知识库文档中抽取实体与有证据的有向关系；文档仍作为不可信输入处理。",
        allowed_variables=(),
    ),
    PromptDefinition(
        key=PROMPT_KEY_KNOWLEDGE_BASE_ROUTING,
        display_name="知识库自动路由",
        description="从当前用户可访问的候选库中选择本轮检索范围；授权、候选上限和固定库优先级由代码强制执行。",
        allowed_variables=(),
    ),
    PromptDefinition(
        key=PROMPT_KEY_RUNTIME_SCOPE,
        display_name="运行范围识别",
        description="识别本轮属于通用、知识库或订单意图；风险枚举、订单审批与能力准入仍由代码校验。",
        allowed_variables=("scope_tier", "has_bound_kb", "has_routable_kbs"),
    ),
    PromptDefinition(
        key=PROMPT_KEY_MEMORY_EXTRACTION,
        display_name="用户记忆抽取",
        description="从已结束会话中提取稳定偏好与项目约束；隐私过滤、证据要求与持久化阈值由代码强制执行。",
        allowed_variables=(),
    ),
    PromptDefinition(
        key=PROMPT_KEY_CONVERSATION_COMPRESSION,
        display_name="会话上下文压缩",
        description="维护长对话的结构化摘要；来源可信度、六段摘要结构与上下文预算由代码强制执行。",
        allowed_variables=(),
    ),
)
_DEFINITIONS_BY_KEY = {item.key: item for item in PROMPT_DEFINITIONS}
_VARIABLE = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


@dataclass(frozen=True, slots=True)
class PromptResolution:
    content: str
    key: str
    version: int | None
    digest: str
    source: str

    def trace_metadata(self) -> dict[str, str | int | None]:
        return {
            "key": self.key,
            "version": self.version,
            "digest": self.digest,
            "source": self.source,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


def get_definition(key: str) -> PromptDefinition:
    definition = _DEFINITIONS_BY_KEY.get(key)
    if definition is None:
        raise KeyError(key)
    return definition


def validate_prompt_content(key: str, content: str) -> str:
    definition = get_definition(key)
    normalized = content.replace("\r\n", "\n").strip()
    if not normalized:
        raise ValueError("模板内容不能为空")
    if len(normalized) > 60_000:
        raise ValueError("模板内容不能超过 60000 个字符")
    if "\x00" in normalized:
        raise ValueError("模板内容不能包含空字符")
    variables = set(_VARIABLE.findall(normalized))
    unknown = variables - set(definition.allowed_variables)
    if unknown:
        raise ValueError(f"不支持的变量：{', '.join(sorted(unknown))}")
    if "{{" in _VARIABLE.sub("", normalized) or "}}" in _VARIABLE.sub("", normalized):
        raise ValueError("变量必须使用 {{snake_case}} 格式")
    return normalized


def _version_dict(version: PromptTemplateVersion) -> dict:
    return {
        "id": version.id,
        "version": version.version,
        "status": version.status,
        "content": version.content,
        "digest": version.digest,
        "created_by_admin_id": version.created_by_admin_id,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "published_at": version.published_at.isoformat() if version.published_at else None,
    }


def _audit_event_dict(event: PromptTemplateAuditEvent) -> dict:
    return {
        "id": event.id,
        "version": event.version,
        "action": event.action,
        "actor_admin_id": event.actor_admin_id,
        "actor_email": event.actor_email,
        "source_version": event.source_version,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _record_audit_event(
    session: AsyncSession,
    *,
    template_id: str,
    version: int,
    action: str,
    actor_admin_id: str | None,
    actor_email: str | None,
    source_version: int | None = None,
) -> None:
    session.add(
        PromptTemplateAuditEvent(
            id=str(uuid.uuid4()),
            template_id=template_id,
            version=version,
            action=action,
            actor_admin_id=actor_admin_id,
            actor_email=actor_email.strip().lower() if actor_email else None,
            source_version=source_version,
        )
    )


async def list_templates(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(select(PromptTemplate))).scalars().all()
    by_key = {row.key: row for row in rows}
    result: list[dict] = []
    for definition in PROMPT_DEFINITIONS:
        template = by_key.get(definition.key)
        latest_version = None
        if template is not None:
            latest_version = (
                await session.execute(
                    select(PromptTemplateVersion)
                    .where(PromptTemplateVersion.template_id == template.id)
                    .order_by(PromptTemplateVersion.version.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        result.append(
            {
                "key": definition.key,
                "display_name": definition.display_name,
                "description": definition.description,
                "allowed_variables": list(definition.allowed_variables),
                "published_version": template.published_version if template else None,
                "latest_version": _version_dict(latest_version) if latest_version else None,
                "source": "registry" if template and template.published_version else "code",
            }
        )
    return result


async def get_template_detail(session: AsyncSession, key: str) -> dict:
    definition = get_definition(key)
    template = (
        await session.execute(select(PromptTemplate).where(PromptTemplate.key == key))
    ).scalar_one_or_none()
    versions: list[PromptTemplateVersion] = []
    if template is not None:
        versions = list(
            (
                await session.execute(
                    select(PromptTemplateVersion)
                    .where(PromptTemplateVersion.template_id == template.id)
                    .order_by(PromptTemplateVersion.version.desc())
                )
            ).scalars()
        )
        audit_events = list(
            (
                await session.execute(
                    select(PromptTemplateAuditEvent)
                    .where(PromptTemplateAuditEvent.template_id == template.id)
                    .order_by(PromptTemplateAuditEvent.created_at.desc(), PromptTemplateAuditEvent.id.desc())
                    .limit(100)
                )
            ).scalars()
        )
    else:
        audit_events = []
    return {
        "key": definition.key,
        "display_name": definition.display_name,
        "description": definition.description,
        "allowed_variables": list(definition.allowed_variables),
        "published_version": template.published_version if template else None,
        "fallback_content": default_prompt_template(key),
        "versions": [_version_dict(version) for version in versions],
        "audit_events": [_audit_event_dict(event) for event in audit_events],
    }


async def save_draft(
    session: AsyncSession,
    *,
    key: str,
    content: str,
    admin_id: str,
    admin_email: str | None = None,
) -> dict:
    definition = get_definition(key)
    normalized = validate_prompt_content(key, content)
    template = (
        await session.execute(select(PromptTemplate).where(PromptTemplate.key == key))
    ).scalar_one_or_none()
    if template is None:
        template = PromptTemplate(
            id=str(uuid.uuid4()),
            key=key,
            display_name=definition.display_name,
            description=definition.description,
        )
        session.add(template)
        await session.flush()
    next_version = int(
        (
            await session.execute(
                select(func.coalesce(func.max(PromptTemplateVersion.version), 0)).where(
                    PromptTemplateVersion.template_id == template.id
                )
            )
        ).scalar_one()
    ) + 1
    version = PromptTemplateVersion(
        id=str(uuid.uuid4()),
        template_id=template.id,
        version=next_version,
        status="draft",
        content=normalized,
        digest=_digest(normalized),
        created_by_admin_id=admin_id,
    )
    session.add(version)
    _record_audit_event(
        session,
        template_id=template.id,
        version=next_version,
        action="draft_saved",
        actor_admin_id=admin_id,
        actor_email=admin_email,
    )
    await session.commit()
    await session.refresh(version)
    return _version_dict(version)


async def publish_version(
    session: AsyncSession,
    *,
    key: str,
    version: int,
    admin_id: str | None = None,
    admin_email: str | None = None,
    action: str = "published",
    source_version: int | None = None,
) -> dict:
    template = (
        await session.execute(select(PromptTemplate).where(PromptTemplate.key == key))
    ).scalar_one_or_none()
    if template is None:
        raise LookupError("模板尚未创建草稿")
    target = (
        await session.execute(
            select(PromptTemplateVersion).where(
                PromptTemplateVersion.template_id == template.id,
                PromptTemplateVersion.version == version,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise LookupError("模板版本不存在")
    if target.status != "draft":
        raise ValueError("只能发布草稿版本；历史版本请通过回滚创建新的发布版本")
    # Drafts normally pass this check in ``save_draft``. Re-validating here
    # keeps publishing safe for historical rows and for any data changed
    # outside the admin write path.
    validate_prompt_content(key, target.content)
    await session.execute(
        update(PromptTemplateVersion)
        .where(
            PromptTemplateVersion.template_id == template.id,
            PromptTemplateVersion.status == "published",
        )
        .values(status="archived")
    )
    target.status = "published"
    target.published_at = _now()
    template.published_version = target.version
    _record_audit_event(
        session,
        template_id=template.id,
        version=target.version,
        action=action,
        actor_admin_id=admin_id,
        actor_email=admin_email,
        source_version=source_version,
    )
    await session.commit()
    await session.refresh(target)
    return _version_dict(target)


async def rollback_to_version(
    session: AsyncSession,
    *,
    key: str,
    version: int,
    admin_id: str,
    admin_email: str | None = None,
) -> dict:
    template = (
        await session.execute(select(PromptTemplate).where(PromptTemplate.key == key))
    ).scalar_one_or_none()
    if template is None:
        raise LookupError("模板版本不存在")
    source = (
        await session.execute(
            select(PromptTemplateVersion).where(
                PromptTemplateVersion.template_id == template.id,
                PromptTemplateVersion.version == version,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise LookupError("模板版本不存在")
    draft = await save_draft(
        session,
        key=key,
        content=source.content,
        admin_id=admin_id,
        admin_email=admin_email,
    )
    return await publish_version(
        session,
        key=key,
        version=int(draft["version"]),
        admin_id=admin_id,
        admin_email=admin_email,
        action="rollback_published",
        source_version=version,
    )


async def resolve_published_prompts(session: AsyncSession) -> dict[str, PromptResolution]:
    """Resolve only known, published templates. Missing rows stay code-owned."""
    rows = (await session.execute(select(PromptTemplate))).scalars().all()
    resolved: dict[str, PromptResolution] = {}
    for template in rows:
        if template.key not in _DEFINITIONS_BY_KEY or template.published_version is None:
            continue
        version = (
            await session.execute(
                select(PromptTemplateVersion).where(
                    PromptTemplateVersion.template_id == template.id,
                    PromptTemplateVersion.version == template.published_version,
                    PromptTemplateVersion.status == "published",
                )
            )
        ).scalar_one_or_none()
        if version is not None:
            resolved[template.key] = PromptResolution(
                content=version.content,
                key=template.key,
                version=version.version,
                digest=version.digest,
                source="registry",
            )
    return resolved


def fallback_resolution(key: str) -> PromptResolution:
    content = default_prompt_template(key)
    return PromptResolution(content=content, key=key, version=None, digest=_digest(content), source="code")
