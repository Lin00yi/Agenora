"use client";

import { useEffect, useMemo, useRef } from "react";

import type { Graph as G6Graph } from "@antv/g6";
import type { GraphEdge, GraphNode } from "@/lib/kb-api";

type KnowledgeGraphCanvasProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  mode: "overview" | "evidence";
  selectedId?: string;
  onSelect: (id: string) => void;
};

function graphLabel(name: string) {
  return name.length > 11 ? `${name.slice(0, 11)}…` : name;
}

function nodeSize(node: GraphNode, selected = false) {
  if (selected) return 48;
  return Math.min(42, Math.max(34, 30 + Math.sqrt(Math.max(node.evidence_count, 1)) * 3));
}

function themeColor(host: HTMLElement, token: string, fallback: string, alpha = 1) {
  const value = getComputedStyle(host).getPropertyValue(token).trim();
  if (!value || value.includes("var(")) return fallback;
  return `rgb(${value} / ${alpha})`;
}

function focusPositions(nodes: GraphNode[], selectedId: string, width: number, height: number) {
  const positions = new Map<string, { x: number; y: number }>();
  const center = { x: width / 2, y: height / 2 };
  positions.set(selectedId, center);
  const neighbours = nodes.filter((node) => node.id !== selectedId).sort((left, right) => left.name.localeCompare(right.name, "zh-CN"));
  const radius = Math.max(156, Math.min(218, Math.min(width, height) / 2 - 86));
  neighbours.forEach((node, index) => {
    const radians = (Math.PI * 2 * index) / Math.max(neighbours.length, 1) - Math.PI / 2;
    positions.set(node.id, { x: center.x + Math.cos(radians) * radius, y: center.y + Math.sin(radians) * radius });
  });
  return positions;
}

export function KnowledgeGraphCanvas({ nodes, edges, mode, selectedId, onSelect }: KnowledgeGraphCanvasProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  const relatedIds = useMemo(() => {
    if (!selectedId) return new Set<string>();
    return new Set([
      selectedId,
      ...edges.flatMap((edge) => edge.source === selectedId ? [edge.target] : edge.target === selectedId ? [edge.source] : []),
    ]);
  }, [edges, selectedId]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    let cancelled = false;
    let graph: G6Graph | null = null;
    let resizeObserver: ResizeObserver | null = null;

    const renderGraph = async () => {
      const { Graph } = await import("@antv/g6");
      if (cancelled || !host) return;

      const visibleNodeIds = new Set(nodes.map((node) => node.id));
      const useRadialFocus = mode === "evidence" && Boolean(selectedId) && visibleNodeIds.has(selectedId ?? "");
      const positions = useRadialFocus && selectedId ? focusPositions(nodes, selectedId, host.clientWidth, host.clientHeight) : new Map<string, { x: number; y: number }>();
      const colors = {
        surface: themeColor(host, "--surface", "#ffffff"),
        border: themeColor(host, "--surface-border", "#94a3b8", 0.82),
        ink: themeColor(host, "--ink", "#1e293b"),
        muted: themeColor(host, "--muted", "#64748b"),
        brand: themeColor(host, "--brand", "#2563eb"),
        brandSoft: themeColor(host, "--brand", "#dbeafe", 0.16),
      };
      graph = new Graph({
        container: host,
        width: host.clientWidth,
        height: host.clientHeight,
        animation: false,
        data: {
          nodes: nodes.map((node) => ({ id: node.id, data: node, style: { size: mode === "overview" ? [160, 46] : nodeSize(node, node.id === selectedId), ...positions.get(node.id) } })),
          edges: edges.filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)).map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, data: edge })),
        },
        node: {
          type: mode === "overview" ? "rect" : "circle",
          style: (datum) => {
            const node = datum.data as GraphNode;
            const isSelected = node.id === selectedId;
            const isRelated = !selectedId || relatedIds.has(node.id);
            if (mode === "overview") {
              return {
                size: [160, 46],
                radius: 8,
                fill: isSelected ? colors.brandSoft : colors.surface,
                stroke: isSelected ? colors.brand : colors.border,
                lineWidth: isSelected ? 2.5 : 1.5,
                labelText: graphLabel(node.name),
                labelPlacement: "center",
                labelFill: colors.ink,
                labelFontSize: 12,
                labelWordWrap: false,
              };
            }
            return {
              size: nodeSize(node, isSelected),
              fill: isSelected ? colors.brand : colors.surface,
              stroke: isSelected ? colors.brand : colors.border,
              lineWidth: isSelected ? 4 : 2,
              opacity: isRelated ? 1 : 0.18,
              labelText: graphLabel(node.name),
              labelPlacement: "bottom",
              labelFill: colors.ink,
              labelFontSize: 11,
              labelWordWrap: false,
              labelOffsetY: 7,
            };
          },
        },
        edge: {
          type: "line",
          style: (datum) => {
            const edge = datum.data as GraphEdge;
            const isRelated = !selectedId || edge.source === selectedId || edge.target === selectedId;
            return {
              stroke: mode === "overview" ? colors.muted : isRelated ? colors.brand : colors.border,
              lineWidth: mode === "overview" ? 1.4 : isRelated ? Math.min(3.5, 1.25 + edge.confidence * 1.5) : 1,
              opacity: mode === "overview" ? 0.86 : isRelated ? 0.78 : 0.08,
              label: true,
              endArrow: true,
              endArrowSize: 5,
              labelText: mode === "overview" || (useRadialFocus && edges.length <= 12) ? edge.type : "",
              labelAutoRotate: false,
              labelFill: colors.ink,
              labelFontSize: 11,
              labelBackground: true,
              labelBackgroundFill: colors.surface,
              labelBackgroundOpacity: 1,
              labelBackgroundRadius: 4,
              labelOffsetY: 10,
              labelPadding: [3, 5],
            };
          },
        },
        ...(mode === "overview" ? { layout: {
          type: "dagre",
          rankdir: "TB",
          nodesep: 56,
          ranksep: 84,
          nodeSize: [160, 46],
          edgeLabelSize: [64, 18],
          edgeLabelOffset: 6,
          animation: false,
        } } : useRadialFocus ? {} : { layout: {
          type: "force",
          preventOverlap: true,
          nodeSize: (datum) => nodeSize(datum.data as GraphNode, datum.id === selectedId) + 42,
          linkDistance: 180,
          nodeStrength: -1200,
          edgeStrength: 50,
          gravity: 2,
          maxIteration: 800,
          animation: false,
        } }),
        behaviors: ["drag-canvas", "zoom-canvas", "drag-element"],
      });

      graph.on("node:click", (event) => {
        const id = (event as unknown as { target: { id?: string } }).target.id;
        if (id) onSelectRef.current(String(id));
      });
      await graph.render();
      if (cancelled) return;
      if (mode === "overview") {
        await graph.fitCenter(false);
      } else {
        await graph.fitView({ when: "always" }, false);
      }

      resizeObserver = new ResizeObserver(() => {
        if (!graph || cancelled) return;
        graph.setSize(host.clientWidth, host.clientHeight);
        if (mode === "overview") {
          void graph.fitCenter(false);
        } else {
          void graph.fitView({ when: "always" }, false);
        }
      });
      resizeObserver.observe(host);
    };

    void renderGraph();
    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      graph?.destroy();
    };
  }, [edges, mode, nodes, relatedIds, selectedId]);

  return (
    <div className="relative min-h-[34rem] overflow-hidden border-b border-surface-border/60 bg-surface sm:min-h-[38rem] lg:border-b-0 lg:border-r">
      <div ref={hostRef} className="absolute inset-0" role="application" aria-label="可交互知识图谱画布" />
      <p className="pointer-events-none absolute bottom-3 left-3 rounded-md border border-surface-border/80 bg-surface/90 px-2.5 py-1.5 text-[11px] text-muted shadow-sm">{mode === "overview" ? "拖拽查看结构 · 滚轮缩放 · 点击实体查看证据" : "拖拽画布 · 滚轮缩放 · 点击实体查看证据"}</p>
    </div>
  );
}
