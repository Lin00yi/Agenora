import type { ReactNode } from "react";
import { toast as sonnerToast, type ExternalToast, type ToastT } from "sonner";

const MAX_VISIBLE_TOASTS = 4;
const DEFAULT_DURATION_MS = 5000;
const DISMISS_STAGGER_MS = 600;
const REMOVAL_TRANSITION_MS = 220;

type ToastKind = "message" | "success" | "info" | "warning" | "error" | "loading";
type ToastId = string | number;

type QueuedToast = {
  id: ToastId;
  kind: ToastKind;
  message: ReactNode;
  options: ExternalToast;
};

const pending: QueuedToast[] = [];
const active = new Map<ToastId, ReturnType<typeof setTimeout>>();
let nextId = 0;
let flushTimer: ReturnType<typeof setTimeout> | undefined;

function createId(): string {
  nextId += 1;
  return `agenora-toast-${nextId}`;
}

function callSonner(kind: ToastKind, message: ReactNode, options: ExternalToast): ToastId {
  if (kind === "message") return sonnerToast.message(message, options);
  return sonnerToast[kind](message, options);
}

function scheduleFlush() {
  if (flushTimer) return;
  flushTimer = setTimeout(() => {
    flushTimer = undefined;
    flush();
  }, REMOVAL_TRANSITION_MS);
}

function release(id: ToastId) {
  if (!active.has(id)) return;
  clearTimeout(active.get(id));
  active.delete(id);
  scheduleFlush();
}

function show(entry: QueuedToast) {
  // Entries that start together are deliberately staggered, so the oldest
  // closes first instead of all four expiring during the same frame.
  const position = active.size;
  const { onAutoClose, onDismiss, duration, ...options } = entry.options;
  const baseDuration = duration ?? DEFAULT_DURATION_MS;
  const closeAfterMs = baseDuration + position * DISMISS_STAGGER_MS;
  const timer = setTimeout(() => {
    if (!active.has(entry.id)) return;
    onAutoClose?.({ id: entry.id } as ToastT);
    sonnerToast.dismiss(entry.id);
    release(entry.id);
  }, closeAfterMs);
  active.set(entry.id, timer);

  callSonner(entry.kind, entry.message, {
    ...options,
    id: entry.id,
    // The queue owns the clock. Sonner's own timer starts for hidden entries
    // too, which can collapse a burst of notifications at the same moment.
    duration: Infinity,
    onDismiss: (toast) => {
      onDismiss?.(toast);
      release(entry.id);
    },
  });
}

function flush() {
  if (active.size >= MAX_VISIBLE_TOASTS || pending.length === 0) return;
  // Only the most recent overflow notice remains pending during the exit
  // transition. A delayed, older notification should never displace it.
  const entry = pending.pop();
  pending.length = 0;
  if (entry) show(entry);
}

function evictOldest() {
  const oldestId = active.keys().next().value as ToastId | undefined;
  if (oldestId === undefined) return;
  sonnerToast.dismiss(oldestId);
  release(oldestId);
}

function enqueue(kind: ToastKind, message: ReactNode, options: ExternalToast = {}): ToastId {
  const id = options.id ?? createId();

  if (active.has(id)) {
    // Preserve the original lifecycle callbacks for an in-place update (for
    // example, a loading toast that becomes a success toast).
    return callSonner(kind, message, { ...options, id });
  }

  const entry = { id, kind, message, options: { ...options, id } };
  if (active.size >= MAX_VISIBLE_TOASTS) {
    evictOldest();
    pending.length = 0;
    pending.push(entry);
    return id;
  }

  if (pending.length > 0) {
    pending.length = 0;
    pending.push(entry);
    return id;
  }

  show(entry);
  return id;
}

function dismiss(id?: ToastId): ToastId | undefined {
  if (id === undefined) {
    pending.length = 0;
    active.forEach((timer) => clearTimeout(timer));
    active.clear();
    return sonnerToast.dismiss();
  }

  const pendingIndex = pending.findIndex((entry) => entry.id === id);
  if (pendingIndex >= 0) {
    pending.splice(pendingIndex, 1);
    return id;
  }

  if (active.has(id)) release(id);
  return sonnerToast.dismiss(id);
}

/**
 * Application notification stack. Four notices may be visible at once; new
 * notices enter at the front and replace the oldest item when the stack is full.
 */
export const toast = Object.assign(
  (message: ReactNode, options?: ExternalToast) => enqueue("message", message, options),
  {
    success: (message: ReactNode, options?: ExternalToast) => enqueue("success", message, options),
    info: (message: ReactNode, options?: ExternalToast) => enqueue("info", message, options),
    warning: (message: ReactNode, options?: ExternalToast) => enqueue("warning", message, options),
    error: (message: ReactNode, options?: ExternalToast) => enqueue("error", message, options),
    loading: (message: ReactNode, options?: ExternalToast) => enqueue("loading", message, options),
    dismiss,
    custom: sonnerToast.custom,
    promise: sonnerToast.promise,
    getHistory: sonnerToast.getHistory,
  }
);
