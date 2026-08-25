"use client";

import { Filter, Network, Play, RefreshCw, Settings2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { AdminPanel, AdminSection } from "@/components/kb/AdminPageShell";
import { KnowledgeGraphCanvas } from "@/components/kb/KnowledgeGraphCanvas";
import { Button } from "@/components/ui/button";
import { StateView } from "@/components/ui/state-view";
import { Switch } from "@/components/ui/switch";
import { getToken } from "@/lib/auth";
import { cn } from "@/lib/cn";
import {
  getGraphEntity,
  getGraphScans,
  getKb,
  getKnowledgeGraph,
  patchKb,
  patchGraphSource,
  runGraphScan,
  type GraphEntityDetail,
  type GraphEdge,
  type GraphNode,
  type GraphScan,
  type KnowledgeGraph,
  type KBDetail,
} from "@/lib/kb-api";
import { toast } from "@/lib/toast";

function localTime(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

type GraphViewMode = "overview" | "evidence";

const OVERVIEW_RELATIONS = new Set(["depends_on", "contains"]);

function normalizedText(value: string) {
  return value.trim().toLocaleLowerCase();
}

function createsCycle(adjacency: Map<string, Set<string>>, source: string, target: string) {
  const pending = [target];
  const seen = new Set<string>();
  while (pending.length > 0) {
    const current = pending.pop();
    if (!current || seen.has(current)) continue;
    if (current === source) return true;
    seen.add(current);
    adjacency.get(current)?.forEach((next) => pending.push(next));
  }
  return false;
}

function buildOverviewGraph(graph: KnowledgeGraph, query: string) {
  const structuralEdges = graph.edges
    .filter((edge) => OVERVIEW_RELATIONS.has(edge.type))
    .sort((left, right) => right.confidence - left.confidence || right.evidence_count - left.evidence_count);
  const adjacency = new Map<string, Set<string>>();
  const pairs = new Set<string>();
  const edges: GraphEdge[] = [];
  for (const edge of structuralEdges) {
    const pair = `${edge.source}:${edge.target}`;
    if (edge.source === edge.target || pairs.has(pair) || createsCycle(adjacency, edge.source, edge.target)) continue;
    pairs.add(pair);
    edges.push(edge);
    const neighbours = adjacency.get(edge.source) ?? new Set<string>();
    neighbours.add(edge.target);
    adjacency.set(edge.source, neighbours);
  }
  const needle = normalizedText(query);
  const matchingIds = new Set(graph.nodes.filter((node) => !needle || normalizedText(`${node.name} ${node.type}`).includes(needle)).map((node) => node.id));
  const visibleEdges = needle ? edges.filter((edge) => matchingIds.has(edge.source) || matchingIds.has(edge.target)) : edges;
  const nodeIds = new Set(visibleEdges.flatMap((edge) => [edge.source, edge.target]));
  if (needle) matchingIds.forEach((id) => nodeIds.add(id));
  return {
    nodes: graph.nodes.filter((node) => nodeIds.has(node.id)),
    edges: visibleEdges,
    omittedCycles: structuralEdges.length - edges.length,
  };
}

function buildEvidenceGraph(graph: KnowledgeGraph, selectedId: string | undefined, relationTypes: string[], confidenceFloor: number) {
  if (!selectedId) return { nodes: [], edges: [] };
  const edges = graph.edges
    .filter((edge) => (edge.source === selectedId || edge.target === selectedId) && (relationTypes.length === 0 || relationTypes.includes(edge.type)) && edge.confidence >= confidenceFloor)
    .sort((left, right) => right.evidence_count - left.evidence_count || right.confidence - left.confidence)
    .slice(0, 12);
  const nodeIds = new Set([selectedId, ...edges.flatMap((edge) => [edge.source, edge.target])]);
  return { nodes: graph.nodes.filter((node) => nodeIds.has(node.id)), edges };
}

export function KnowledgeGraphPanel({ kbId: id }: { kbId: string }) {
  const router = useRouter();
  const [kb, setKb] = useState<KBDetail | null>(null);
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [scans, setScans] = useState<GraphScan[]>([]);
  const [selected, setSelected] = useState<GraphEntityDetail | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [running, setRunning] = useState(false);
  const [kgBusy, setKgBusy] = useState(false);
  const [sourceBusy, setSourceBusy] = useState<string | null>(null);
  const [relationTypes, setRelationTypes] = useState<string[]>([]);
  const [confidenceFloor, setConfidenceFloor] = useState(0);
  const [viewMode, setViewMode] = useState<GraphViewMode>("overview");
  const [appliedQuery, setAppliedQuery] = useState("");

  const refresh = useCallback(async (search = "") => {
    const [nextKb, nextGraph, nextScans] = await Promise.all([
      getKb(id),
      getKnowledgeGraph(id, search),
      getGraphScans(id),
    ]);
    setKb(nextKb);
    setGraph(nextGraph);
    setScans(nextScans.items);
  }, [id]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    refresh().catch((error: Error) => toast.error(error.message)).finally(() => setLoading(false));
  }, [refresh, router]);

  const hasActiveScan = scans.some((scan) => ["pending", "running", "extracting"].includes(scan.status));
  useEffect(() => {
    if (!hasActiveScan) return;
    const timer = window.setInterval(() => {
      refresh().catch(() => {});
    }, 3000);
    return () => window.clearInterval(timer);
  }, [hasActiveScan, refresh]);

  const role = kb?.my_role ?? "viewer";
  const canRun = !kb?.is_system && (role === "owner" || role === "editor");
  const isOwner = !kb?.is_system && role === "owner";
  const availableRelationTypes = useMemo(() => [...new Set(graph?.edges.map((edge) => edge.type) ?? [])].sort(), [graph?.edges]);
  const overviewGraph = useMemo(() => graph ? buildOverviewGraph(graph, appliedQuery) : { nodes: [], edges: [], omittedCycles: 0 }, [appliedQuery, graph]);
  const evidenceGraph = useMemo(() => graph ? buildEvidenceGraph(graph, selected?.entity.id, relationTypes, confidenceFloor) : { nodes: [], edges: [] }, [confidenceFloor, graph, relationTypes, selected?.entity.id]);

  const toggleFilter = (value: string, current: string[], setCurrent: (next: string[]) => void) => {
    setCurrent(current.includes(value) ? current.filter((item) => item !== value) : [...current, value]);
  };

  const onSearch = async (event: FormEvent) => {
    event.preventDefault();
    setRefreshing(true);
    try {
      await refresh();
      setAppliedQuery(query);
      setSelected(null);
      setViewMode("overview");
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setRefreshing(false);
    }
  };

  const onRunScan = async () => {
    setRunning(true);
    try {
      await runGraphScan(id);
      toast.success("图谱扫描已提交，关系抽取会在后台执行。");
      await refresh();
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const onSelectNode = async (nodeId: string) => {
    try {
      setSelected(await getGraphEntity(id, nodeId));
    } catch (error) {
      toast.error((error as Error).message);
    }
  };

  const openEvidenceView = () => {
    if (!selected) return;
    setViewMode("evidence");
  };

  const onToggleKg = async (next: boolean) => {
    if (!kb) return;
    setKgBusy(true);
    setKb({ ...kb, kg_enabled: next });
    try {
      const updated = await patchKb(id, { kg_enabled: next });
      setKb((current) => current ? { ...current, kg_enabled: updated.kg_enabled } : current);
      toast.success(next ? "已开启知识图谱召回，正在同步已入库文档。" : "已关闭知识图谱召回。");
    } catch (error) {
      setKb((current) => current ? { ...current, kg_enabled: !next } : current);
      toast.error((error as Error).message);
    } finally {
      setKgBusy(false);
    }
  };

  const onSourceInterval = async (sourceId: string, minutes: number) => {
    setSourceBusy(sourceId);
    try {
      await patchGraphSource(id, sourceId, { scan_interval_minutes: minutes });
      toast.success(minutes ? "已更新定时扫描频率。" : "已关闭定时扫描。");
      await refresh();
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setSourceBusy(null);
    }
  };

  if (loading) {
    return <StateView variant="loading" title="正在加载知识图谱" description="正在获取实体、关系与扫描状态。" className="m-8" />;
  }
  if (!kb || !graph) {
    return <StateView variant="error" title="无法加载知识图谱" description="请返回知识库后重试。" className="m-8" />;
  }

  return (
    <>
      <section className="admin-panel mb-4 overflow-hidden" aria-label="图谱概览">
        <div className="grid gap-4 bg-surface-2/35 px-5 py-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
          <div className="flex min-w-0 items-start gap-3">
            <span className="admin-icon-tile admin-icon-tile-brand">
              <Network className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-ink">图谱概览</h2>
              <p className="mt-1 text-sm leading-6 text-muted">从依赖结构定位实体，再追溯关系对应的原文证据。</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <dl className="grid grid-cols-3 divide-x divide-surface-border/70 rounded-lg border border-surface-border/70 bg-surface text-sm">
              <GraphMetric label="活跃实体" value={graph.stats.entities} />
              <GraphMetric label="活跃关系" value={graph.stats.relations} />
              <GraphMetric label="最近扫描" value={scans[0] ? localTime(scans[0].created_at) : "尚未扫描"} compact />
            </dl>
            {canRun ? (
              <Button type="button" onClick={() => void onRunScan()} disabled={running || hasActiveScan}>
                <Play className="h-4 w-4" />
                {running ? "提交中" : hasActiveScan ? "抽取中" : "立即扫描"}
              </Button>
            ) : null}
          </div>
        </div>
      </section>

      <AdminPanel title="图谱召回" subtitle="控制知识图谱是否参与混合检索，并决定是否对文档执行实体关系抽取。" className="mb-4">
        <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <span className="admin-icon-tile admin-icon-tile-brand">
              <Network className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-medium text-ink">{kb.kg_enabled ? "已开启" : "未开启"}</p>
              <p className="mt-1 text-xs leading-5 text-muted">首次开启会同步已入库文档并发起关系抽取，可能增加模型调用。</p>
            </div>
          </div>
          {isOwner ? <Switch checked={Boolean(kb.kg_enabled)} disabled={kgBusy} onCheckedChange={(checked) => void onToggleKg(checked)} aria-label="切换知识图谱召回" /> : <span className={cn("chip shrink-0", kb.kg_enabled ? "chip-success" : "chip-muted")}>{kb.kg_enabled ? "已开启" : "未开启"}</span>}
        </div>
      </AdminPanel>

      {!kb.kg_enabled ? (
        <StateView
          variant="notice"
          title="尚未开启知识图谱召回"
          description={isOwner ? "请在上方开启图谱召回，再执行扫描与关系抽取。" : "请联系知识库所有者在本页开启图谱召回，再执行扫描与关系抽取。"}
          className="mb-4"
        />
      ) : null}

      <AdminPanel
        title="图谱画布"
        subtitle={graph.truncated ? "当前结果已限制在 120 个实体内；请搜索实体缩小范围。" : "先从依赖总览理解结构，再按需查看实体证据。"}
        busy={refreshing}
        busyTitle="正在刷新图谱"
        toolbar={
          <form onSubmit={onSearch} className="flex items-center gap-2">
            <label className="sr-only" htmlFor="graph-query">搜索实体</label>
            <input id="graph-query" value={query} onChange={(event) => setQuery(event.target.value)} className="admin-input h-[var(--control-h-sm)] w-44" placeholder="搜索实体" />
            <Button type="submit" size="sm" variant="outline">搜索</Button>
            <Button type="button" size="sm" variant="ghost" aria-label="刷新图谱" onClick={() => { setRefreshing(true); refresh().catch((error: Error) => toast.error(error.message)).finally(() => setRefreshing(false)); }}>
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
          </form>
        }
      >
        {graph.nodes.length === 0 ? (
          <StateView
            variant="empty"
            title="还没有可展示的关系"
            description={canRun ? "执行一次扫描，系统会从已入库文档中抽取带原文证据的实体关系。" : "等待知识库编辑者执行扫描后，这里会显示可追溯的实体关系。"}
            action={canRun ? <Button type="button" onClick={() => void onRunScan()} disabled={running || hasActiveScan}><Network className="h-4 w-4" />{hasActiveScan ? "抽取中" : "立即扫描"}</Button> : undefined}
          />
        ) : (
          <>
            <GraphViewSwitch mode={viewMode} selectedName={selected?.entity.name} onChange={setViewMode} />
            {viewMode === "overview" ? (
              overviewGraph.nodes.length === 0 ? <StateView variant="empty" density="compact" title="没有可组成依赖总览的关系" description="依赖总览只展示 depends_on 和 contains 关系；可以搜索其他实体或切换到实体证据。" className="border-t border-surface-border/60" /> : (
                <div className="grid gap-0 border-t border-surface-border/60 lg:grid-cols-[minmax(0,1fr)_20rem]">
                  <KnowledgeGraphCanvas nodes={overviewGraph.nodes} edges={overviewGraph.edges} mode="overview" selectedId={selected?.entity.id} onSelect={onSelectNode} />
                  <EntityInspector kbId={id} detail={selected} onClear={() => setSelected(null)} onOpenEvidence={openEvidenceView} showOpenEvidence />
                </div>
              )
            ) : !selected ? (
              <StateView variant="notice" density="compact" title="先从依赖总览选择一个实体" description="实体证据视图只展示该实体的一跳关系与原文证据，避免再次形成不可读的全量关系网。" action={<Button type="button" variant="outline" onClick={() => setViewMode("overview")}>返回依赖总览</Button>} className="border-t border-surface-border/60" />
            ) : evidenceGraph.nodes.length === 0 ? (
              <StateView variant="empty" density="compact" title="当前筛选下没有实体关系" description="请放宽关系类型或置信度筛选。" className="border-t border-surface-border/60" />
            ) : (
              <>
                <EvidenceFilters
                  relationTypes={availableRelationTypes}
                  selectedRelationTypes={relationTypes}
                  confidenceFloor={confidenceFloor}
                  shownEdgeCount={evidenceGraph.edges.length}
                  onToggleRelationType={(value) => toggleFilter(value, relationTypes, setRelationTypes)}
                  onConfidenceFloor={setConfidenceFloor}
                  onClearFilters={() => { setRelationTypes([]); setConfidenceFloor(0); }}
                />
                <div className="grid gap-0 border-t border-surface-border/60 lg:grid-cols-[minmax(0,1fr)_20rem]">
                  <KnowledgeGraphCanvas nodes={evidenceGraph.nodes} edges={evidenceGraph.edges} mode="evidence" selectedId={selected.entity.id} onSelect={onSelectNode} />
                  <EntityInspector kbId={id} detail={selected} onClear={() => setSelected(null)} onOpenEvidence={openEvidenceView} />
                </div>
              </>
            )}
          </>
        )}
      </AdminPanel>

      <AdminSection id="scans" icon={Settings2} title="扫描与来源" description="扫描任务可恢复、可重试；只有 URL 文档支持定时重新抓取。" className="mt-7">
        <AdminPanel title="最近扫描" subtitle="关系抽取在扫描后异步执行，完成后画布会自动更新。">
          {scans.length === 0 ? <StateView variant="empty" density="compact" title="还没有扫描记录" description="提交一次扫描后可在这里查看进度和结果。" /> : (
            <div className="divide-y divide-surface-border/60">
              {scans.slice(0, 8).map((scan) => (
                <div key={scan.id} className="flex flex-col gap-2 px-5 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0"><p className="font-medium">{scan.trigger === "schedule" ? "定时扫描" : scan.trigger === "enable" ? "启用图谱后回填" : "手动扫描"}</p><p className="mt-1 text-xs text-muted tabular-nums">{localTime(scan.created_at)} · 已检查 {scan.documents_seen} · 变化 {scan.documents_changed} · 已抽取 {scan.documents_extracted}</p></div>
                  <span className={cn("chip shrink-0", scan.status === "done" ? "chip-success" : scan.status === "dead_letter" ? "chip-danger" : "chip-muted")}>{scan.status === "done" ? "完成" : scan.status === "extracting" ? "关系抽取中" : scan.status === "running" ? "扫描中" : scan.status === "pending" ? "等待中" : scan.status}</span>
                </div>
              ))}
            </div>
          )}
        </AdminPanel>

        <AdminPanel title="定时来源" subtitle="远程 URL 的内容变化才会触发重新抽取，未变化不会重复调用模型。" className="mt-4">
          {graph.sources.length === 0 ? <StateView variant="notice" density="compact" title="扫描后会生成来源配置" description="首次扫描会将已入库文档登记为图谱来源。" /> : (
            <div className="divide-y divide-surface-border/60">
              {graph.sources.map((source) => (
                <div key={source.id} className="flex flex-col gap-2 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0"><p className="truncate text-sm font-medium">{source.source_type === "url" ? source.source_url : "已上传文件"}</p><p className="mt-1 text-xs text-muted">上次检查：{localTime(source.last_scan_at)}{source.last_error ? ` · ${source.last_error}` : ""}</p></div>
                  {source.source_type === "url" && isOwner ? <label className="flex shrink-0 items-center gap-2 text-xs text-muted"><span>定时扫描</span><select aria-label="定时扫描频率" disabled={sourceBusy === source.id} value={source.scan_interval_minutes} onChange={(event) => void onSourceInterval(source.id, Number(event.target.value))} className="admin-select-trigger h-[var(--control-h-sm)] min-w-28 text-xs"><option value={0}>关闭</option><option value={60}>每小时</option><option value={1440}>每天</option><option value={10080}>每周</option></select></label> : <span className="chip chip-muted shrink-0">{source.source_type === "url" ? (source.scan_interval_minutes ? `${source.scan_interval_minutes} 分钟` : "未定时") : "文件需手动更新"}</span>}
                </div>
              ))}
            </div>
          )}
        </AdminPanel>
      </AdminSection>
    </>
  );
}

function GraphMetric({ label, value, compact = false }: { label: string; value: number | string; compact?: boolean }) {
  return <div className="min-w-0 px-3 py-2.5 first:pl-4 last:pr-4"><dt className="text-[11px] text-muted">{label}</dt><dd className={cn("mt-1 truncate font-semibold tabular-nums text-ink", compact ? "text-xs" : "text-base")}>{value}</dd></div>;
}

function GraphViewSwitch({ mode, selectedName, onChange }: { mode: GraphViewMode; selectedName?: string; onChange: (mode: GraphViewMode) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2 bg-surface-2/30 px-5 py-4">
      <span className="text-xs font-medium text-ink">图谱视图</span>
      <button type="button" aria-pressed={mode === "overview"} onClick={() => onChange("overview")} className={cn("rounded-md border px-2.5 py-1.5 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30", mode === "overview" ? "border-brand bg-brand text-on-brand" : "border-surface-border bg-surface text-muted hover:border-brand/45 hover:text-ink")}>依赖总览</button>
      <button type="button" aria-pressed={mode === "evidence"} onClick={() => onChange("evidence")} className={cn("rounded-md border px-2.5 py-1.5 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30", mode === "evidence" ? "border-brand bg-brand text-on-brand" : "border-surface-border bg-surface text-muted hover:border-brand/45 hover:text-ink")}>实体证据</button>
      <span className="text-xs text-muted">{mode === "overview" ? "仅显示 depends_on、contains 的无环结构关系。" : selectedName ? `正在查看「${selectedName}」的一跳关系。` : "选择一个实体后查看其关系证据。"}</span>
    </div>
  );
}

function EvidenceFilters({
  relationTypes,
  selectedRelationTypes,
  confidenceFloor,
  shownEdgeCount,
  onToggleRelationType,
  onConfidenceFloor,
  onClearFilters,
}: {
  relationTypes: string[];
  selectedRelationTypes: string[];
  confidenceFloor: number;
  shownEdgeCount: number;
  onToggleRelationType: (value: string) => void;
  onConfidenceFloor: (value: number) => void;
  onClearFilters: () => void;
}) {
  const hasFilters = selectedRelationTypes.length > 0 || confidenceFloor > 0;
  return (
    <div className="space-y-3 bg-surface-2/30 px-5 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-ink"><Filter className="h-3.5 w-3.5 text-muted" />证据关系筛选</span>
        <span className="text-xs text-muted">显示 {shownEdgeCount} 条一跳关系</span>
        {hasFilters ? <Button type="button" variant="ghost" size="xs" className="ml-auto" onClick={onClearFilters}>清除筛选</Button> : null}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs text-muted">关系</span>
        {relationTypes.map((type) => <FilterChip key={type} active={selectedRelationTypes.includes(type)} onClick={() => onToggleRelationType(type)}>{type}</FilterChip>)}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-xs text-muted">最低置信度
          <select aria-label="最低关系置信度" value={confidenceFloor} onChange={(event) => onConfidenceFloor(Number(event.target.value))} className="admin-select-trigger h-[var(--control-h-sm)] min-w-24 text-xs">
            <option value={0}>全部</option><option value={0.6}>≥ 0.60</option><option value={0.75}>≥ 0.75</option><option value={0.9}>≥ 0.90</option>
          </select>
        </label>
      </div>
    </div>
  );
}

function FilterChip({ active, children, onClick }: { active: boolean; children: string; onClick: () => void }) {
  return <button type="button" aria-pressed={active} onClick={onClick} className={cn("rounded-full border px-2 py-1 text-[11px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30", active ? "border-brand bg-brand text-on-brand" : "border-surface-border bg-surface text-muted hover:border-brand/45 hover:text-ink")}>{children}</button>;
}

function EntityInspector({ kbId, detail, onClear, onOpenEvidence, showOpenEvidence = false }: { kbId: string; detail: GraphEntityDetail | null; onClear: () => void; onOpenEvidence: () => void; showOpenEvidence?: boolean }) {
  if (!detail) return <aside className="bg-surface-2/30 p-5"><StateView variant="notice" density="compact" title="选择一个实体" description="查看它的关联关系与支持该关系的原文证据。" /></aside>;
  return <aside className="bg-surface-2/30 p-5"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="text-xs text-muted">{detail.entity.type}</p><h3 className="mt-1 truncate text-balance text-base font-semibold">{detail.entity.name}</h3></div><Button type="button" size="xs" variant="ghost" onClick={onClear}>关闭</Button></div>{detail.entity.summary ? <p className="mt-2 text-pretty text-xs leading-5 text-muted">{detail.entity.summary}</p> : null}{showOpenEvidence ? <Button type="button" size="xs" variant="outline" className="mt-3" onClick={onOpenEvidence}>查看实体证据图</Button> : null}<div className="mt-5 space-y-3">{detail.relations.length === 0 ? <p className="text-xs text-muted">暂无关系证据。</p> : detail.relations.map((relation) => <div key={relation.id} className="rounded-lg border border-surface-border/70 bg-surface p-3"><p className="text-xs font-medium text-ink">{relation.type} <span className="text-muted">· {relation.confidence.toFixed(2)}</span></p>{relation.evidence.slice(0, 2).map((evidence) => <div key={evidence.id} className="mt-2 border-l-2 border-brand/35 pl-2"><p className="line-clamp-3 text-pretty text-xs leading-5 text-muted">{evidence.quote}</p><Link href={`/kbs/${kbId}/documents/${evidence.document_id}`} className="mt-1 inline-block text-xs text-brand hover:underline">查看原文</Link></div>)}</div>)}</div></aside>;
}
