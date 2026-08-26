"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import type { TraceObservationNode } from "@/lib/trace-types";
import { cn } from "@/lib/cn";
import { usePreviewPanel } from "@/components/preview/PreviewPanelProvider";

const SPAN_LABELS: Record<string, string> = {
  runtime_scope: "运行范围",
  "runtime_scope.intent": "意图识别",
  "runtime_scope.intent.triage": "意图分流",
  "runtime_scope.intent.complex": "精细意图",
  auto_kb_route: "知识库路由",
  "auto_kb_route.llm": "路由模型",
  scope: "范围解析",
  reason: "推理",
  call_tools: "执行工具",
  "llm.chat_with_tools": "模型调用",
  build_context: "组装上下文",
  query_policy: "查询策略",
  kb_search: "检索知识库",
  search_kb: "检索知识库",
  search_kg: "检索知识图谱",
  web_search: "搜索网络",
  generate_kb_report: "生成知识库报告",
  get_current_time: "获取当前时间",
  list_orders: "查询订单",
  get_order: "订单详情",
  prepare_refund: "准备退款",
  confirm_refund: "确认退款",
};

type Props = {
  nodes: TraceObservationNode[];
  totalMs: number;
  rootStart: number;
};

export function SpanWaterfall({ nodes, totalMs, rootStart }: Props) {
  const expandableIds = useMemo(() => collectExpandableIds(nodes), [nodes]);
  const [expanded, setExpanded] = useState<Set<string>>(() => defaultExpanded(nodes, 1));
  const [activeId, setActiveId] = useState<string | null>(null);
  const { openPreview } = usePreviewPanel();

  useEffect(() => {
    setExpanded(defaultExpanded(nodes, 1));
    setActiveId(null);
  }, [nodes]);

  const allExpanded = expandableIds.length > 0 && expandableIds.every((id) => expanded.has(id));

  const toggle = (id: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const inspect = (node: TraceObservationNode) => {
    setActiveId(node.id);
    openPreview({
      kind: "trace-io",
      title: spanTitle(node.name),
      subtitle: `${typeLabel(node.type)} · ${formatDuration(node.duration_ms)}`,
      input: node.input_preview,
      output: node.output_preview,
      error: node.error,
      metadata: node.metadata,
    });
  };

  return (
    <div className="overflow-hidden rounded-lg border border-surface-border/70">
      <div className="flex items-center gap-3 border-b border-surface-border/70 bg-surface-2/40 px-3 py-2">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-ink">执行链路</p>
          <p className="text-[11px] text-muted">点选节点预览输入 / 输出，右侧时间轴相对整次请求对齐</p>
        </div>
        <button
          type="button"
          className="shrink-0 text-[11px] text-muted transition hover:text-ink"
          onClick={() => setExpanded(allExpanded ? new Set() : new Set(expandableIds))}
        >
          {allExpanded ? "全部折叠" : "全部展开"}
        </button>
        <span className="w-40 shrink-0 text-right text-[11px] tabular-nums text-muted">
          {formatDuration(totalMs)}
        </span>
      </div>

      <div className="min-w-0 overflow-x-hidden">
        {nodes.map((node, index) => (
          <SpanRow
            key={node.id}
            node={node}
            depth={0}
            index={index}
            totalMs={totalMs}
            rootStart={rootStart}
            expanded={expanded}
            activeId={activeId}
            onToggle={toggle}
            onInspect={inspect}
          />
        ))}
      </div>
    </div>
  );
}

function SpanRow({
  node,
  depth,
  index,
  totalMs,
  rootStart,
  expanded,
  activeId,
  onToggle,
  onInspect,
}: {
  node: TraceObservationNode;
  depth: number;
  index: number | null;
  totalMs: number;
  rootStart: number;
  expanded: Set<string>;
  activeId: string | null;
  onToggle: (id: string) => void;
  onInspect: (node: TraceObservationNode) => void;
}) {
  const children = node.children ?? [];
  const hasChildren = children.length > 0;
  const open = hasChildren && expanded.has(node.id);
  const startMs = node.started_at ? Date.parse(node.started_at) - rootStart : 0;
  const dur = Math.max(0, node.duration_ms ?? 0);
  const leftPct = Math.max(0, Math.min(100, (startMs / totalMs) * 100));
  const widthPct = Math.max(1.2, Math.min(100 - leftPct, (dur / totalMs) * 100));
  const slow = dur >= 1000 || dur / totalMs >= 0.35;
  const tokens = tokenLabel(node.usage);
  const ttft = node.type === "generation" ? node.ttft_ms : null;
  const active = activeId === node.id;

  return (
    <div>
      <div
        className={cn(
          "flex min-w-0 items-stretch border-b border-surface-border/40",
          node.status === "error" && "bg-danger/5",
          active && "bg-surface-2/80"
        )}
      >
        <div
          className="flex min-w-0 flex-1 items-center gap-1 py-1.5 pr-2"
          style={{ paddingLeft: 8 + depth * 14 }}
        >
          {hasChildren ? (
            <button
              type="button"
              className="inline-flex size-5 shrink-0 items-center justify-center rounded text-muted hover:bg-surface-2 hover:text-ink"
              aria-label={open ? "折叠" : "展开"}
              onClick={() => onToggle(node.id)}
            >
              {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
            </button>
          ) : (
            <span className="size-5 shrink-0" />
          )}

          <button
            type="button"
            className="flex min-w-0 flex-1 items-center gap-2 text-left hover:text-ink"
            title={node.error ? `${node.name} · ${node.error}` : node.name}
            onClick={() => onInspect(node)}
          >
            <TypeMark type={node.type} />
            {depth === 0 && index != null ? (
              <span className="w-4 shrink-0 text-[10px] tabular-nums text-muted">{index + 1}</span>
            ) : null}
            <span className="min-w-0 flex-1 truncate text-[13px] text-ink" title={node.name}>
              {spanTitle(node.name)}
            </span>
            {node.status === "error" ? (
              <span className="chip chip-danger shrink-0 text-[10px]">失败</span>
            ) : null}
            {node.model ? (
              <span className="hidden max-w-[9rem] truncate text-[11px] text-muted lg:inline">
                {node.model}
              </span>
            ) : null}
            {tokens ? (
              <span className="hidden shrink-0 tabular-nums text-[11px] text-muted md:inline">{tokens}</span>
            ) : null}
            {ttft != null ? (
              <span className="hidden shrink-0 tabular-nums text-[11px] text-muted lg:inline" title="模型调用到首个输出 token 的耗时">
                TTFT {formatDuration(ttft)}
              </span>
            ) : null}
            {node.cost_usd != null && node.cost_usd > 0 ? (
              <span className="hidden shrink-0 tabular-nums text-[11px] text-muted lg:inline">
                ${node.cost_usd.toFixed(4)}
              </span>
            ) : null}
            <span
              className={cn(
                "shrink-0 tabular-nums text-[11px]",
                slow ? "font-medium text-warning" : "text-muted"
              )}
            >
              {formatDuration(node.duration_ms)}
            </span>
          </button>
        </div>

        <div className="relative w-40 shrink-0 border-l border-surface-border/50 bg-surface-2/30">
          <div
            className={cn(
              "absolute top-1/2 h-2 -translate-y-1/2 rounded-sm",
              barTone(node.type, node.status === "error")
            )}
            style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
            title={`${formatDuration(startMs)} → ${formatDuration(startMs + dur)}`}
          />
        </div>
      </div>

      {open
        ? children.map((child) => (
            <SpanRow
              key={child.id}
              node={child}
              depth={depth + 1}
              index={null}
              totalMs={totalMs}
              rootStart={rootStart}
              expanded={expanded}
              activeId={activeId}
              onToggle={onToggle}
              onInspect={onInspect}
            />
          ))
        : null}
    </div>
  );
}

function TypeMark({ type }: { type: string }) {
  const tone =
    type === "generation" ? "bg-ink" : type === "tool" ? "bg-ink/55" : "bg-ink/25";
  return <span className={cn("size-1.5 shrink-0 rounded-full", tone)} title={typeLabel(type)} />;
}

function barTone(type: string, error: boolean): string {
  if (error) return "bg-danger/80";
  if (type === "generation") return "bg-ink/80";
  if (type === "tool") return "bg-ink/50";
  return "bg-ink/25";
}

function spanTitle(name: string): string {
  const stripped = name.replace(/^LLM\s+/i, "").trim();
  return SPAN_LABELS[stripped] ?? SPAN_LABELS[name] ?? name;
}

function typeLabel(type: string): string {
  if (type === "generation") return "模型";
  if (type === "tool") return "工具";
  return "步骤";
}

function tokenLabel(usage: Record<string, number> | null): string | null {
  if (!usage) return null;
  const input = usage.input_tokens ?? usage.prompt_tokens;
  const output = usage.output_tokens ?? usage.completion_tokens;
  if (input == null && output == null) return null;
  if (input != null && output != null) return `${input}→${output}`;
  return String(input ?? output);
}

function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`;
  return `${(ms / 60_000).toFixed(2)} min`;
}

function collectExpandableIds(nodes: TraceObservationNode[]): string[] {
  const ids: string[] = [];
  const walk = (list: TraceObservationNode[]) => {
    for (const node of list) {
      if (node.children?.length) {
        ids.push(node.id);
        walk(node.children);
      }
    }
  };
  walk(nodes);
  return ids;
}

function defaultExpanded(nodes: TraceObservationNode[], maxDepth: number): Set<string> {
  const ids = new Set<string>();
  const walk = (list: TraceObservationNode[], depth: number) => {
    for (const node of list) {
      if (node.children?.length && depth < maxDepth) {
        ids.add(node.id);
        walk(node.children, depth + 1);
      }
    }
  };
  walk(nodes, 0);
  return ids;
}
