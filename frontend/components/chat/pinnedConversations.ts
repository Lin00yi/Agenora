"use client";

const STORAGE_KEY = "kf.pinned-conversation-ids";

function readPinnedIds(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((id): id is string => typeof id === "string" && id.length > 0);
  } catch {
    return [];
  }
}

function writePinnedIds(ids: string[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
  } catch {
    // Ignore quota / private-mode failures; pin state stays in-memory.
  }
}

/** Load persisted pin order (first = highest). */
export function loadPinnedConversationIds(): string[] {
  return readPinnedIds();
}

export function persistPinnedConversationIds(ids: string[]) {
  writePinnedIds(ids);
}

export function togglePinnedConversationId(ids: string[], id: string): string[] {
  if (ids.includes(id)) {
    return ids.filter((item) => item !== id);
  }
  return [id, ...ids];
}

export function sortConversationsByPin<T extends { id: string; updated_at: number }>(
  items: T[],
  pinnedIds: string[]
): T[] {
  if (pinnedIds.length === 0) return items;
  const rank = new Map(pinnedIds.map((id, index) => [id, index]));
  return [...items].sort((a, b) => {
    const aPinned = rank.has(a.id);
    const bPinned = rank.has(b.id);
    if (aPinned !== bPinned) return aPinned ? -1 : 1;
    if (aPinned && bPinned) {
      return (rank.get(a.id) ?? 0) - (rank.get(b.id) ?? 0);
    }
    return b.updated_at - a.updated_at;
  });
}
