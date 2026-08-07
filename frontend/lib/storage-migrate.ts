/**
 * One-time localStorage namespace migration into `agenora:*`.
 *
 * History:
 * - TravelGPT → KnowFlow/AnyKB (`travelgpt:*` → `anykb:*`) on 2026-05-14
 * - KnowFlow/AnyKB → Agenora (`anykb:*` → `agenora:*`)
 *
 * Idempotent: once the Agenora sentinel exists the scan short-circuits.
 * Old keys are removed only after the new keys are confirmed written.
 */

const SENTINEL_KEY = "agenora:_migrated_from_legacy";
const TARGET_PREFIX = "agenora:";
const LEGACY_PREFIXES = ["travelgpt:", "anykb:"] as const;

function migratePrefix(ls: Storage, oldPrefix: string): boolean {
  const oldKeys: string[] = [];
  for (let i = 0; i < ls.length; i++) {
    const k = ls.key(i);
    if (k && k.startsWith(oldPrefix)) oldKeys.push(k);
  }
  if (oldKeys.length === 0) return true;

  const copied: string[] = [];
  for (const oldKey of oldKeys) {
    const newKey = TARGET_PREFIX + oldKey.slice(oldPrefix.length);
    if (ls.getItem(newKey) != null) {
      copied.push(oldKey);
      continue;
    }
    const value = ls.getItem(oldKey);
    if (value == null) continue;
    try {
      ls.setItem(newKey, value);
      copied.push(oldKey);
    } catch {
      // Quota — abort; retry next load.
      return false;
    }
  }

  for (const oldKey of copied) {
    try {
      ls.removeItem(oldKey);
    } catch {
      /* ignore */
    }
  }
  return true;
}

export function migrateLegacyKeys(): void {
  if (typeof window === "undefined") return;
  let ls: Storage;
  try {
    ls = window.localStorage;
  } catch {
    return;
  }

  if (ls.getItem(SENTINEL_KEY)) return;

  for (const prefix of LEGACY_PREFIXES) {
    if (!migratePrefix(ls, prefix)) return;
  }

  // Drop the intermediate AnyKB sentinel if present.
  try {
    ls.removeItem("anykb:_migrated_from_travelgpt");
  } catch {
    /* ignore */
  }

  try {
    ls.setItem(SENTINEL_KEY, "1");
  } catch {
    /* ignore */
  }
}
