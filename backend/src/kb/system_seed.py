"""Startup housekeeping for built-in KBs.

The travel demo KB has been removed. On every boot we delete any leftover
row, unbind conversations that still point at it, and drop the legacy
``restaurants`` vector collection so existing installs stop listing it.
"""
from __future__ import annotations

import structlog
from sqlalchemy import update

from src.infra.database import get_session_factory
from src.kb.models import KB

log = structlog.get_logger()

# Retired travel demo. Kept only so leftover rows can be identified and purged.
LEGACY_TRAVEL_KB_ID = "00000000-0000-4000-8000-000000000001"
LEGACY_TRAVEL_COLLECTION = "restaurants"


async def seed_system_kbs() -> None:
    """No built-in KBs are seeded. Purge the retired travel demo if present."""
    await purge_legacy_travel_kb()


async def purge_legacy_travel_kb() -> None:
    """Idempotent removal of the retired travel demo KB and its vectors."""
    from src.conversations.models import Conversation
    from src.infra.vector_store import get_store
    from src.kb.routes import purge_kb

    factory = get_session_factory()
    async with factory() as session:
        unbound = await session.execute(
            update(Conversation)
            .where(Conversation.kb_id == LEGACY_TRAVEL_KB_ID)
            .values(kb_id=None)
        )
        if unbound.rowcount:
            log.info("legacy_travel_conversations_unbound", count=unbound.rowcount)

        kb = await session.get(KB, LEGACY_TRAVEL_KB_ID)
        if kb is not None:
            await purge_kb(session, kb)
            log.info("legacy_travel_kb_purged", kb_id=LEGACY_TRAVEL_KB_ID)
        else:
            await session.commit()
            log.info("legacy_travel_kb_absent")

    store = get_store()
    if hasattr(store, "delete_collection"):
        try:
            await store.delete_collection(LEGACY_TRAVEL_COLLECTION)
        except Exception:  # noqa: BLE001
            log.warning("legacy_travel_collection_drop_failed", collection=LEGACY_TRAVEL_COLLECTION)
