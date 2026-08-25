"use client";

import { BookOpen, Network, Play, RefreshCw, Settings2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { AdminPageShell, AdminPanel, AdminSection } from "@/components/kb/AdminPageShell";
import { Button } from "@/components/ui/button";
import { StateView } from "@/components/ui/state-view";
import { getToken } from "@/lib/auth";
import { cn } from "@/lib/cn";
import {
  getGraphEntity,
  getGraphScans,
  getKb,
  getKnowledgeGraph,
  patchGraphSource,
  runGraphScan,
  type GraphEntityDetail,
  type GraphNode,
  type GraphScan,
  type KnowledgeGraph,
  type KBDetail,
} from "@/lib/kb-api";
import { toast } from "@/lib/toast";

type Point = { x: number; y: number };

function graphPoints(nodes: GraphNode[]): Record<string, Point> {
  const center = { x: 500, y: 300 };
  const radius = Math.max(145, Math.min(245, 65 + nodes.length * 8));
  return Object.fromEntries(
    nodes.map((node, index) => {
      const radians = (Math.PI * 2 * index) / Math.max(nodes.length, 1) - Math.PI / 2;
      return [node.id, {
        x: center.x + Math.cos(radians) * radius,
        y: center.y + Math.sin(radians) * radius,
      }];
    })
  );
}

function localTime(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

export default function KnowledgeGraphPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [kb, setKb] = useState<KBDetail | null>(null);
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [scans, setScans] = useState<GraphScan[]>([]);
  const [selected, setSelected] = useState<GraphEntityDetail | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [running, setRunning] = useState(false);
  const [sourceBusy, setSourceBusy] = useState<string | null>(null);

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

  const hasActiveScan = scans.some((scan) => scan.status === "pending" || scan.status === "running");
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
  const points = useMemo(() => graphPoints(graph?.nodes ?? []), [graph?.nodes]);

  const onSearch = async (event: FormEvent) => {
    event.preventDefault();
    setRefreshing(true);
    try {
      await refresh(query);
      setSelected(null);
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
      await refresh(query);
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

  const onSourceInterval = async (sourceId: string, minutes: number) => {
    setSourceBusy(sourceId);
    try {
      await patchGraphSource(id, sourceId, { scan_interval_minutes: minutes });
      toast.success(minutes ? "已更新定时扫描频率。" : "已关闭定时扫描。");
      await refresh(query);
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
    <AdminPageShell
      breadcrumbs={[{ label: "首页", href: "/" }, { label: "知识库管理", href: "/kbs" }, { label: kb.name, href: `/kbs/${id}` }, { label: "知识图谱" }]}
      title="知识图谱"
      subtitle="实体、关系和原文证据均由 Agenora 管理；无需打开 Neo4j Browser 或 LightRAG。"
      actions={
        <>
          {canRun ? (
            <Button type="button" onClick={() => void onRunScan()} disabled={running}>
              <Play className="h-4 w-4" />
              {running ? "提交中" : "立即扫描"}
            </Button>
          ) : null}
          <Button asChild variant="outline">
            <Link href={`/kbs/${id}`}><BookOpen className="h-4 w-4" />返回知识库</Link>
          </Button>
        </>
      }
    >
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <StatCard label="活跃实体" value={graph.stats.entities} />
        <StatCard label="活跃关系" value={graph.stats.relations} />
        <StatCard label="最近扫描" value={scans[0] ? localTime(scans[0].created_at) : "尚未扫描"} compact />
      </div>

      {!kb.kg_enabled ? (
        <StateView
          variant="notice"
          title="尚未开启知识图谱召回"
          description="请先在知识库的检索设置中开启知识图谱召回，再执行扫描与关系抽取。"
          action={<Button asChild variant="outline"><Link href={`/kbs/${id}`}>前往检索设置</Link></Button>}
          className="mb-4"
        />
      ) : null}

      <AdminPanel
        title="图谱画布"
        subtitle={graph.truncated ? "当前结果已限制在 120 个实体内；请搜索实体缩小范围。" : "选择实体查看关系及其原文证据。"}
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
            action={canRun ? <Button type="button" onClick={() => void onRunScan()} disabled={running}><Network className="h-4 w-4" />立即扫描</Button> : undefined}
          />
        ) : (
          <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_20rem]">
            <GraphCanvas nodes={graph.nodes} edges={graph.edges} points={points} selectedId={selected?.entity.id} onSelect={onSelectNode} />
            <EntityInspector kbId={id} detail={selected} onClear={() => setSelected(null)} />
          </div>
        )}
      </AdminPanel>

      <AdminSection id="scans" icon={Settings2} title="扫描与来源" description="扫描任务可恢复、可重试；只有 URL 文档支持定时重新抓取。" className="mt-7">
        <AdminPanel title="最近扫描" subtitle="关系抽取在扫描后异步执行，完成后画布会自动更新。">
          {scans.length === 0 ? <StateView variant="empty" density="compact" title="还没有扫描记录" description="提交一次扫描后可在这里查看进度和结果。" /> : (
            <div className="divide-y divide-surface-border/60">
              {scans.slice(0, 8).map((scan) => (
                <div key={scan.id} className="flex flex-col gap-2 px-5 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0"><p className="font-medium">{scan.trigger === "schedule" ? "定时扫描" : scan.trigger === "enable" ? "启用图谱后回填" : "手动扫描"}</p><p className="mt-1 text-xs text-muted tabular-nums">{localTime(scan.created_at)} · 已检查 {scan.documents_seen} · 变化 {scan.documents_changed} · 已抽取 {scan.documents_extracted}</p></div>
                  <span className={cn("chip shrink-0", scan.status === "done" ? "chip-success" : scan.status === "dead_letter" ? "chip-danger" : "chip-muted")}>{scan.status === "done" ? "完成" : scan.status === "running" ? "执行中" : scan.status === "pending" ? "等待中" : scan.status}</span>
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
    </AdminPageShell>
  );
}

function StatCard({ label, value, compact = false }: { label: string; value: number | string; compact?: boolean }) {
  return <section className="admin-panel px-5 py-4"><p className="text-xs text-muted">{label}</p><p className={cn("mt-1 font-semibold tabular-nums text-ink", compact ? "truncate text-sm" : "text-2xl")}>{value}</p></section>;
}

function GraphCanvas({ nodes, edges, points, selectedId, onSelect }: { nodes: GraphNode[]; edges: KnowledgeGraph["edges"]; points: Record<string, Point>; selectedId?: string; onSelect: (id: string) => void }) {
  return <div className="relative min-h-[34rem] overflow-hidden border-b border-surface-border/60 bg-surface sm:min-h-[38rem] lg:border-b-0 lg:border-r" aria-label="知识图谱画布">
    <svg className="absolute inset-0 size-full" viewBox="0 0 1000 600" preserveAspectRatio="xMidYMid meet" aria-hidden>
      {edges.map((edge) => {
        const source = points[edge.source]; const target = points[edge.target];
        return source && target ? <line key={edge.id} x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke="currentColor" className="text-surface-border" strokeWidth="2" /> : null;
      })}
    </svg>
    {nodes.map((node) => {
      const point = points[node.id];
      if (!point) return null;
      return <button key={node.id} type="button" onClick={() => onSelect(node.id)} className={cn("absolute max-w-32 -translate-x-1/2 -translate-y-1/2 rounded-lg border px-3 py-2 text-left text-xs shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30", selectedId === node.id ? "border-brand bg-brand text-on-brand" : "border-surface-border bg-surface text-ink hover:border-brand/50 hover:bg-surface-2")} style={{ left: `${point.x / 10}%`, top: `${point.y / 6}%` }}><span className="block truncate font-medium">{node.name}</span><span className={cn("mt-0.5 block truncate text-[10px]", selectedId === node.id ? "text-on-brand/75" : "text-muted")}>{node.type} · {node.evidence_count} 条证据</span></button>;
    })}
  </div>;
}

function EntityInspector({ kbId, detail, onClear }: { kbId: string; detail: GraphEntityDetail | null; onClear: () => void }) {
  if (!detail) return <aside className="bg-surface-2/30 p-5"><StateView variant="notice" density="compact" title="选择一个实体" description="查看它的关联关系与支持该关系的原文证据。" /></aside>;
  return <aside className="bg-surface-2/30 p-5"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="text-xs text-muted">{detail.entity.type}</p><h3 className="mt-1 truncate text-balance text-base font-semibold">{detail.entity.name}</h3></div><Button type="button" size="xs" variant="ghost" onClick={onClear}>关闭</Button></div>{detail.entity.summary ? <p className="mt-2 text-pretty text-xs leading-5 text-muted">{detail.entity.summary}</p> : null}<div className="mt-5 space-y-3">{detail.relations.length === 0 ? <p className="text-xs text-muted">暂无关系证据。</p> : detail.relations.map((relation) => <div key={relation.id} className="rounded-lg border border-surface-border/70 bg-surface p-3"><p className="text-xs font-medium text-ink">{relation.type} <span className="text-muted">· {relation.confidence.toFixed(2)}</span></p>{relation.evidence.slice(0, 2).map((evidence) => <div key={evidence.id} className="mt-2 border-l-2 border-brand/35 pl-2"><p className="line-clamp-3 text-pretty text-xs leading-5 text-muted">{evidence.quote}</p><Link href={`/kbs/${kbId}/documents/${evidence.document_id}`} className="mt-1 inline-block text-xs text-brand hover:underline">查看原文</Link></div>)}</div>)}</div></aside>;
}
