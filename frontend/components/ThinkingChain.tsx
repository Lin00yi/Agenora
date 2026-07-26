"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  Ban,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  LoaderCircle,
  Search,
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

type DetailRow = {
  text: string;
  duration: string;
  status: ToolEvent["status"];
};

type ToolGroup = {
  name: string;
  events: ToolEvent[];
  status: ToolEvent["status"];
  detailRows: DetailRow[];
  latencyMs: number | null;
};

type ChainSummary = {
  text: string;
  duration: string | null;
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
  const hasRunning = events.some((event) => event.status === "running");
  const [open, setOpen] = useState(hasRunning);
  const [, force] = useState(0);
  const groups = useMemo(() => groupToolEvents(events), [events]);

  useEffect(() => {
    if (!hasRunning) return;
    const id = setInterval(() => force((value) => value + 1), 200);
    return () => clearInterval(id);
  }, [hasRunning]);

  const summary = formatChainSummary(groups, hasRunning);

  return (
    <div className="rounded-lg border border-fg/10 bg-surface/90">
      <button
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-11 w-full cursor-pointer items-center justify-between gap-3 px-3 py-2 text-sm transition-colors hover:bg-fg/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/70"
        type="button"
      >
        <span className="flex min-w-0 items-center gap-2 text-muted">
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          {hasRunning ? (
            <LoaderCircle className="h-3.5 w-3.5 animate-spin text-brand" />
          ) : (
            <Search className="h-3.5 w-3.5 text-brand" />
          )}
          <span className="truncate">{summary.text}</span>
        </span>
        {summary.duration && (
          <span className="shrink-0 rounded-full bg-fg/7 px-2 py-0.5 text-xs tabular-nums text-muted">
            {summary.duration}
          </span>
        )}
      </button>

      {open && (
        <ul className="space-y-2 border-t border-fg/10 p-3 text-sm">
          {groups.map((group) => (
            <li
              className="rounded-lg border border-fg/10 bg-fg/[0.025] px-3 py-2.5"
              key={group.name}
            >
              <div className="flex items-start gap-2">
                <span className="mt-0.5">{STATUS_ICON[group.status]}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-3">
                    <span className="truncate text-sm font-medium text-fg/85">
                      {formatGroupTitle(group)}
                    </span>
                    {group.latencyMs != null && (
                      <span className="shrink-0 rounded-full bg-fg/7 px-2 py-0.5 text-xs tabular-nums text-muted">
                        {formatDuration(group.latencyMs)}
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 text-xs text-muted">{formatGroupMeta(group)}</div>
                </div>
              </div>

              {group.detailRows.length > 0 && (
                <ul className="mt-2.5 space-y-1.5 border-l border-fg/10 pl-3 text-xs text-muted">
                  {group.detailRows.map((row, index) => (
                    <li className="flex items-start gap-3" key={`${row.text}-${index}`}>
                      <span className="mt-[0.45rem] h-1 w-1 shrink-0 rounded-full bg-brand/70" />
                      <span className="min-w-0 flex-1 break-words leading-5">{row.text}</span>
                      <span className={detailDurationClass(row.status)}>{row.duration}</span>
                    </li>
                  ))}
                </ul>
              )}

              {group.events.some((event) => event.error || event.reason) && (
                <div className="mt-2 space-y-1 text-xs">
                  {group.events.map((event) => {
                    const message = event.error || event.reason;
                    if (!message) return null;
                    return (
                      <p
                        className={event.error ? "text-red-500" : "text-amber-600"}
                        key={event.id ?? message}
                      >
                        {message}
                      </p>
                    );
                  })}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function groupToolEvents(events: ToolEvent[]): ToolGroup[] {
  const groups = new Map<string, ToolEvent[]>();
  for (const event of events) {
    groups.set(event.name, [...(groups.get(event.name) ?? []), event]);
  }
  return Array.from(groups.entries()).map(([name, groupedEvents]) => ({
    name,
    events: groupedEvents,
    status: aggregateStatus(groupedEvents),
    detailRows: groupedEvents.map(formatToolDetailRow).filter((row) => row.text),
    latencyMs: maxLatency(groupedEvents),
  }));
}

function aggregateStatus(events: ToolEvent[]): ToolEvent["status"] {
  if (events.some((event) => event.status === "running")) return "running";
  if (events.some((event) => event.status === "error")) return "error";
  if (events.some((event) => event.status === "blocked")) return "blocked";
  return "ok";
}

function maxLatency(events: ToolEvent[]): number | null {
  return events.reduce<number | null>((max, event) => {
    if (event.latency_ms == null) return max;
    return max == null ? event.latency_ms : Math.max(max, event.latency_ms);
  }, null);
}

function formatChainSummary(groups: ToolGroup[], hasRunning: boolean): ChainSummary {
  const calls = groups.reduce((total, group) => total + group.events.length, 0);
  const duration = formatOptionalDuration(maxGroupLatency(groups));
  if (groups.length === 1) {
    const group = groups[0];
    return {
      text: `${formatGroupTitle(group)} \u00b7 ${formatGroupMeta(group)}`,
      duration,
    };
  }
  return {
    text: `${hasRunning ? "\u6b63\u5728\u4f7f\u7528\u5de5\u5177" : "\u5df2\u4f7f\u7528\u5de5\u5177"} \u00b7 ${groups.length} \u7ec4 \u00b7 ${calls} \u6b21\u8c03\u7528`,
    duration,
  };
}

function maxGroupLatency(groups: ToolGroup[]): number | null {
  return groups.reduce<number | null>((max, group) => {
    if (group.latencyMs == null) return max;
    return max == null ? group.latencyMs : Math.max(max, group.latencyMs);
  }, null);
}

function formatGroupTitle(group: ToolGroup): string {
  const base = NAME_LABEL[group.name] ?? group.name;
  if (group.status === "running") {
    return group.events.length > 1 && isSearchTool(group.name)
      ? `\u6b63\u5728\u5e76\u884c${base}`
      : `\u6b63\u5728${base}`;
  }
  if (group.status === "ok") {
    return group.events.length > 1 && isSearchTool(group.name)
      ? `\u5df2\u5e76\u884c${base}`
      : `\u5df2${base}`;
  }
  if (group.status === "blocked") return `${base} \u5df2\u963b\u6b62`;
  return `${base} \u5931\u8d25`;
}

function formatGroupMeta(group: ToolGroup): string {
  const unit = isSearchTool(group.name) ? "\u6761\u67e5\u8be2" : "\u6b21\u8c03\u7528";
  const status =
    group.status === "ok"
      ? "\u5168\u90e8\u5b8c\u6210"
      : group.status === "running"
        ? "\u8fdb\u884c\u4e2d"
        : group.status === "blocked"
          ? "\u90e8\u5206\u963b\u6b62"
          : "\u90e8\u5206\u5931\u8d25";
  return `${group.events.length} ${unit} \u00b7 ${status}`;
}

function isSearchTool(name: string): boolean {
  return name === "search_kb" || name === "web_search" || name === "search_restaurant_kb";
}

function formatToolInputSummary(event: ToolEvent): string {
  const input = event.input;
  if (!input) return "";
  const query = input.query;
  if (typeof query === "string" && query.trim()) return query.trim();
  const city = input.city;
  if (typeof city === "string" && city.trim()) return city.trim();
  return formatToolInput(input)
    .map((row) => `${row.label}: ${row.value}`)
    .join(" \u00b7 ");
}

function formatToolDetailRow(event: ToolEvent): DetailRow {
  const text = formatToolInputSummary(event) || NAME_LABEL[event.name] || event.name;
  return {
    text,
    duration:
      event.status === "running"
        ? formatRunningDuration(event)
        : event.latency_ms != null
          ? formatDuration(event.latency_ms)
          : getStatusText(event.status),
    status: event.status,
  };
}

function formatRunningDuration(event: ToolEvent): string {
  if (!event.t0) return "\u8fdb\u884c\u4e2d";
  return `${formatDuration(Math.max(0, Date.now() - event.t0))} \u8fdb\u884c\u4e2d`;
}

function getStatusText(status: ToolEvent["status"]): string {
  if (status === "ok") return "\u5df2\u5b8c\u6210";
  if (status === "running") return "\u8fdb\u884c\u4e2d";
  if (status === "blocked") return "\u5df2\u963b\u6b62";
  return "\u5931\u8d25";
}

function detailDurationClass(status: ToolEvent["status"]): string {
  const base =
    "shrink-0 rounded-full px-2 py-0.5 text-[11px] tabular-nums leading-4";
  if (status === "ok") return `${base} bg-brand/10 text-brand`;
  if (status === "running") return `${base} bg-brand/10 text-brand`;
  if (status === "blocked") return `${base} bg-amber-500/10 text-amber-500`;
  return `${base} bg-red-500/10 text-red-500`;
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

function formatOptionalDuration(ms: number | null): string | null {
  return ms == null ? null : formatDuration(ms);
}

function formatDuration(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}
