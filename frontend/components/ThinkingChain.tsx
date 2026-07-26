"use client";

import React, { useEffect, useState } from "react";
import {
  Ban,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  LoaderCircle,
} from "lucide-react";

export type ToolEvent = {
  id?: string;
  name: string;
  input?: Record<string, unknown>;
  status: "running" | "ok" | "error" | "blocked";
  latency_ms?: number | null;
  t0?: number;
  error?: string | null;
  reason?: string;
};

const NAME_LABEL: Record<string, string> = {
  search_kb: "\u68c0\u7d22 KB",
  web_search: "\u641c\u7d22\u7f51\u7edc",
  generate_kb_report: "\u751f\u6210 KB \u62a5\u544a",
  get_weather: "\u67e5\u5929\u6c14",
  search_restaurant_kb: "\u627e\u672c\u5730\u9910\u5385",
  amap_search: "\u5730\u56fe\u641c\u7d22",
  generate_travel_report: "\u751f\u6210\u65c5\u884c\u62a5\u544a",
};

const STATUS_ICON: Record<ToolEvent["status"], React.ReactNode> = {
  running: <LoaderCircle className="h-3.5 w-3.5 animate-spin text-brand" />,
  ok: <CircleCheck className="h-3.5 w-3.5 text-brand" />,
  error: <CircleAlert className="h-3.5 w-3.5 text-red-500" />,
  blocked: <Ban className="h-3.5 w-3.5 text-amber-500" />,
};

export default function ThinkingChain({ events }: { events: ToolEvent[] }) {
  const [open, setOpen] = useState(true);
  const hasRunning = events.some((e) => e.status === "running");
  const [, force] = useState(0);

  useEffect(() => {
    if (!hasRunning) return;
    const id = setInterval(() => force((v) => v + 1), 200);
    return () => clearInterval(id);
  }, [hasRunning]);

  const doneCount = events.filter((e) => e.status !== "running").length;
  const summary = hasRunning
    ? `\u601d\u8003\u4e2d · ${doneCount}/${events.length} \u6b65`
    : `\u601d\u8003\u8fc7\u7a0b · ${events.length} \u6b65`;

  return (
    <div className="rounded-lg border bg-surface">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-sm"
        type="button"
      >
        <span className="flex items-center gap-2 text-muted">
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          {hasRunning && <LoaderCircle className="h-3.5 w-3.5 animate-spin text-brand" />}
          {summary}
        </span>
      </button>
      {open && (
        <ul className="space-y-2 border-t p-3 text-sm">
          {events.map((event, i) => {
            const running = event.status === "running";
            const elapsed = running && event.t0 ? Math.max(0, Date.now() - event.t0) : null;
            const inputRows = formatToolInput(event.input);
            return (
              <li key={event.id ?? i} className="flex items-start gap-2">
                {STATUS_ICON[event.status]}
                <div className="flex-1">
                  <div className="flex items-center justify-between">
                    <span className={running ? "text-fg" : "text-fg/80"}>
                      {NAME_LABEL[event.name] || event.name}
                    </span>
                    {running && elapsed != null && (
                      <span className="text-xs text-muted tabular-nums">
                        {(elapsed / 1000).toFixed(1)}s
                      </span>
                    )}
                    {!running && event.latency_ms != null && (
                      <span className="text-xs text-muted tabular-nums">
                        {event.latency_ms}ms
                      </span>
                    )}
                  </div>
                  {inputRows.length > 0 && (
                    <div className="mt-1 rounded bg-fg/5 p-2 text-xs text-muted">
                      {inputRows.map((row) => (
                        <div className="flex gap-2" key={row.label}>
                          <span className="shrink-0 text-fg/60">{row.label}</span>
                          <span className="min-w-0 break-words">{row.value}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {event.error && <p className="mt-1 text-xs text-red-500">{event.error}</p>}
                  {event.reason && (
                    <p className="mt-1 text-xs text-amber-600">{event.reason}</p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function formatToolInput(input?: Record<string, unknown>): { label: string; value: string }[] {
  if (!input || Object.keys(input).length === 0) return [];
  const rows: { label: string; value: string }[] = [];
  const consumed = new Set<string>();

  addStringRow(rows, consumed, input, "query", "\u67e5\u8be2");
  addStringRow(rows, consumed, input, "city", "\u57ce\u5e02");
  addStringRow(rows, consumed, input, "date", "\u65e5\u671f");
  addScalarRow(rows, consumed, input, "limit", "TopK");
  addScalarRow(rows, consumed, input, "max_results", "\u6570\u91cf");

  for (const [key, value] of Object.entries(input)) {
    if (consumed.has(key) || value == null) continue;
    rows.push({ label: key, value: formatInputValue(value) });
  }
  return rows;
}

function addStringRow(
  rows: { label: string; value: string }[],
  consumed: Set<string>,
  input: Record<string, unknown>,
  key: string,
  label: string
) {
  const value = input[key];
  if (typeof value !== "string" || !value.trim()) return;
  rows.push({ label, value: value.trim() });
  consumed.add(key);
}

function addScalarRow(
  rows: { label: string; value: string }[],
  consumed: Set<string>,
  input: Record<string, unknown>,
  key: string,
  label: string
) {
  const value = input[key];
  if (typeof value !== "string" && typeof value !== "number") return;
  rows.push({ label, value: String(value) });
  consumed.add(key);
}

function formatInputValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}
