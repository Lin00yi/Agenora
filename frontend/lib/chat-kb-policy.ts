/**
 * Controls whether a blank chat exposes a knowledge-base picker.
 *
 * A conversation's final `kb_id` remains server-authoritative. This policy
 * only controls whether the composer offers a user-facing way to choose one.
 */
export type ChatKbSelectionMode = "hidden" | "selectable";

export function parseChatKbSelectionMode(value: string | undefined): ChatKbSelectionMode {
  return value?.trim().toLowerCase() === "selectable" ? "selectable" : "hidden";
}

export const chatKbSelectionMode = parseChatKbSelectionMode(
  process.env.NEXT_PUBLIC_CHAT_KB_SELECTION_MODE
);

export const chatKbPickerEnabled = chatKbSelectionMode === "selectable";
