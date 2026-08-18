"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Database, Gauge, RefreshCw, Timer, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { StateView } from "@/components/ui/state-view";
import { toast } from "@/lib/toast";
import { getRagMonitor, type RagMonitorSnapshot } from "@/lib/admin-api";

export default function RagMonitorPage() {
  const [snapshot, setSnapshot] = useState<RagMonitorSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (initial = false) => {
    if (initial) setLoading(true);
    else setRefreshing(true);
    try {
      setSnapshot(await getRagMonitor());
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load(true);
  }, [load]);

  if (loading) {
    return (
      <StateView
        variant="loading"
        title="正在汇总 RAG 指标"
        description="正在读取检索调用与健康阈值。"
      />
    );
  }
  if (!snapshot) return <StateView title="暂时无法读取 RAG 监控" description="请稍后刷新，确认 Trace 已开启且已有知识库检索请求。" />;

  const { metrics } = snapshot;
  return (
    <div className="relative space-y-6" aria-busy={refreshing}>
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-surface-border/70 pb-6">
        <div>
          <p className="text-xs font-semibold tracking-[0.16em] text-brand">RAG 监控</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight">检索质量与运行健康</h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
            过去 {snapshot.window_hours} 小时的真实检索调用。统计只读取调用元数据，不展示用户问题或文档正文。
          </p>
        </div>
        <Button variant="outline" onClick={() => void load()} disabled={refreshing}>
          <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </header>

      {!snapshot.sample_sufficient ? (
        <StateView
          title="样本尚不足以触发告警"
          description={`当前 ${metrics.retrieval_calls} 次检索调用；至少 ${snapshot.min_calls} 次后才会按阈值判断健康状态。`}
          variant="notice"
        />
      ) : snapshot.alerts.length ? (
        <section className="space-y-2 rounded-lg border border-danger/35 bg-danger/10 p-4" role="alert">
          <div className="flex items-center gap-2 text-sm font-semibold text-danger"><TriangleAlert className="h-4 w-4" />发现 {snapshot.alerts.length} 项 RAG 告警</div>
          {snapshot.alerts.map((alert) => <p key={alert.code} className="text-sm text-danger">{alert.message}：{formatValue(alert.value)}（阈值 {formatValue(alert.threshold)}）</p>)}
        </section>
      ) : (
        <section className="flex items-center gap-2 rounded-lg border border-success/30 bg-success/10 p-4 text-sm text-success"><CheckCircle2 className="h-4 w-4" />当前样本内的 RAG 指标均在阈值范围内。</section>
      )}

      <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(12rem,1fr))]">
        <Metric icon={Database} label="检索调用" value={metrics.retrieval_calls.toLocaleString()} detail={`${metrics.kb_calls} KB · ${metrics.kg_calls} KG`} />
        <Metric icon={AlertTriangle} label="工具错误率" value={percent(metrics.error_rate)} detail={`${metrics.error_calls} 次失败`} tone={metrics.error_rate > 0 ? "danger" : "success"} />
        <Metric icon={Gauge} label="空检索率" value={metrics.empty_rate === null ? "—" : percent(metrics.empty_rate)} detail={metrics.empty_rate === null ? "等待新 Trace 字段" : `${metrics.empty_calls}/${metrics.measurable_empty_calls} 次`} />
        <Metric icon={Timer} label="P95 检索延迟" value={metrics.p95_latency_ms === null ? "—" : `${metrics.p95_latency_ms} ms`} detail={`${metrics.retrieval_traces} 条对话 Trace`} />
        <Metric icon={Gauge} label="平均最高相关度" value={metrics.avg_top_score === null ? "—" : metrics.avg_top_score.toFixed(3)} detail="仅 KB 返回的密集相似度" />
      </div>

      <section className="admin-panel p-5">
        <h3 className="text-sm font-semibold">使用说明</h3>
        <p className="mt-2 text-sm leading-6 text-muted">线上健康指标用于发现异常；准确率、MRR 和引用正确率的发布门禁请使用仓库中的版本化黄金评测集运行离线评测。</p>
      </section>
      {refreshing ? (
        <StateView variant="loading" overlay density="compact" title="正在刷新监控" />
      ) : null}
    </div>
  );
}

function percent(value: number) { return `${(value * 100).toFixed(1)}%`; }
function formatValue(value: number) { return value <= 1 ? percent(value) : String(value); }

function Metric({ icon: Icon, label, value, detail, tone = "default" }: { icon: typeof Database; label: string; value: string; detail: string; tone?: "default" | "danger" | "success" }) {
  const color = tone === "danger" ? "text-danger" : tone === "success" ? "text-success" : "text-ink";
  return <section className="rounded-lg border border-surface-border/80 bg-surface p-4 shadow-sm"><div className="flex items-center justify-between gap-3"><span className="text-xs font-medium text-muted">{label}</span><Icon className={`h-4 w-4 ${color}`} /></div><div className={`mt-4 text-2xl font-semibold tracking-tight ${color}`}>{value}</div><p className="mt-1 text-xs text-muted">{detail}</p></section>;
}
