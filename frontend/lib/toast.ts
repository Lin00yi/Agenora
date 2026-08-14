import type { ReactNode } from "react";
import { toast as sonnerToast, type ExternalToast } from "sonner";

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
const active = new Set<ToastId>();
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
  if (!active.delete(id)) return;
  scheduleFlush();
}

function show(entry: QueuedToast) {
  // Entries that start together are deliberately staggered, so the oldest
  // closes first instead of all four expiring during the same frame.
  const position = active.size;
  active.add(entry.id);
  const { onAutoClose, onDismiss, duration, ...options } = entry.options;
  const baseDuration = duration ?? DEFAULT_DURATION_MS;

  callSonner(entry.kind, entry.message, {
    ...options,
    id: entry.id,
    duration: baseDuration + position * DISMISS_STAGGER_MS,
    onAutoClose: (toast) => {
      onAutoClose?.(toast);
      release(entry.id);
    },
    onDismiss: (toast) => {
      onDismiss?.(toast);
      release(entry.id);
    },
  });
}

function flush() {
  while (active.size < MAX_VISIBLE_TOASTS && pending.length > 0) {
    const entry = pending.shift();
    if (entry) show(entry);
  }
}

function enqueue(kind: ToastKind, message: ReactNode, options: ExternalToast = {}): ToastId {
  const id = options.id ?? createId();

  if (active.has(id)) {
    // Preserve the original lifecycle callbacks for an in-place update (for
    // example, a loading toast that becomes a success toast).
    return callSonner(kind, message, { ...options, id });
  }

  const existingPending = pending.findIndex((entry) => entry.id === id);
  const entry = { id, kind, message, options: { ...options, id } };
  if (existingPending >= 0) {
    pending[existingPending] = entry;
  } else {
    pending.push(entry);
  }
  flush();
  return id;
}

function dismiss(id?: ToastId): ToastId | undefined {
  if (id === undefined) {
    pending.length = 0;
    active.clear();
    return sonnerToast.dismiss();
  }

  const pendingIndex = pending.findIndex((entry) => entry.id === id);
  if (pendingIndex >= 0) {
    pending.splice(pendingIndex, 1);
    return id;
  }

  if (active.delete(id)) scheduleFlush();
  return sonnerToast.dismiss(id);
}

/**
 * Application notification queue. Four notices may be visible at once; their
 * lifetime is FIFO, and queued notices do not start counting down early.
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
