"use client";

import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Database,
  Gauge,
  Play,
  RefreshCw,
  Timer,
  TriangleAlert,
  Upload,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import Select from "@/components/Select";
import { AdminPanel, AdminSection } from "@/components/kb/AdminPageShell";
import { formatAdminDate } from "@/components/kb/admin-utils";
import { usePreviewPanel } from "@/components/preview/PreviewPanelProvider";
import { Button } from "@/components/ui/button";
import { StateView } from "@/components/ui/state-view";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FileUploadSurface } from "@/components/upload/FileUploadSurface";
import { toastApiError } from "@/lib/byok-toast";
import { cn } from "@/lib/cn";
import {
  getKbEvalConfig,
  getKbEvalMonitor,
  getKbEvalRun,
  listKbEvalRuns,
  listKbEvalTemplates,
  putKbEvalConfig,
  replayKbEval,
  runKbEvalRegression,
  type KbEvalConfig,
  type KbEvalMonitorSnapshot,
  type KbEvalPerCase,
  type KbEvalReport,
  type KbEvalRun,
  type KbEvalTemplate,
} from "@/lib/kb-api";
import { toast } from "@/lib/toast";

function metricPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toFixed(3);
}

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function KbEvalSection({ kbId }: { kbId: string }) {
  const router = useRouter();
  const push = (path: string) => router.push(path);
  const { openPreview } = usePreviewPanel();
  const [config, setConfig] = useState<KbEvalConfig | null>(null);
  const [templates, setTemplates] = useState<KbEvalTemplate[]>([]);
  const [runs, setRuns] = useState<KbEvalRun[]>([]);
  const [latest, setLatest] = useState<KbEvalRun | null>(null);
  const [monitor, setMonitor] = useState<KbEvalMonitorSnapshot | null>(null);
  const [hours, setHours] = useState("24");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const [monitorBusy, setMonitorBusy] = useState(false);
  const [replayRunId, setReplayRunId] = useState("");
  const [goldenFile, setGoldenFile] = useState<File | null>(null);
  const [gateFile, setGateFile] = useState<File | null>(null);
  const [replayFile, setReplayFile] = useState<File | null>(null);

  type EvalTab = "config" | "regression" | "replay" | "monitor";
  const [activeTab, setActiveTab] = useState<EvalTab>("config");

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [cfg, runList, tpls, snap] = await Promise.all([
        getKbEvalConfig(kbId),
        listKbEvalRuns(kbId),
        listKbEvalTemplates(kbId),
        getKbEvalMonitor(kbId, Number(hours)),
      ]);
      setConfig(cfg);
      setRuns(runList.runs);
      setTemplates(tpls.templates);
      setMonitor(snap);
      if (runList.runs[0]) {
        setLatest(await getKbEvalRun(kbId, runList.runs[0].id));
        if (!replayRunId) setReplayRunId(runList.runs[0].id);
      } else {
        setLatest(null);
      }
    } catch (error) {
      toastApiError(error, push);
    } finally {
      setLoading(false);
    }
  }, [hours, kbId, replayRunId]);

  useEffect(() => {
    void loadAll();
    // Initial load only; subsequent refreshes are explicit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kbId]);

  async function refreshMonitor(nextHours = hours) {
    setMonitorBusy(true);
    try {
      setMonitor(await getKbEvalMonitor(kbId, Number(nextHours)));
    } catch (error) {
      toastApiError(error, push);
    } finally {
      setMonitorBusy(false);
    }
  }

  async function refreshRuns(preferred?: KbEvalRun) {
    const runList = await listKbEvalRuns(kbId);
    setRuns(runList.runs);
    if (preferred) {
      setLatest(preferred);
    } else if (runList.runs[0]) {
      setLatest(await getKbEvalRun(kbId, runList.runs[0].id));
    } else {
      setLatest(null);
    }
    if (runList.runs[0] && !runList.runs.some((row) => row.id === replayRunId)) {
      setReplayRunId(runList.runs[0].id);
    }
  }

  async function onImportTemplate(templateId: "roogoo") {
    setSaving(true);
    try {
      const next = await putKbEvalConfig(kbId, { template: templateId });
      setConfig(next);
      toast.success("已导入黄金集模板");
    } catch (error) {
      toastApiError(error, push);
    } finally {
      setSaving(false);
    }
  }

  async function onUploadConfig() {
    if (!goldenFile) {
      toast.error("请先选择黄金集 JSONL 文件");
      return;
    }
    setSaving(true);
    try {
      const golden_set_jsonl = await goldenFile.text();
      const body: { golden_set_jsonl: string; gate_json?: string } = { golden_set_jsonl };
      if (gateFile) body.gate_json = await gateFile.text();
      const next = await putKbEvalConfig(kbId, body);
      setConfig(next);
      setGoldenFile(null);
      setGateFile(null);
      toast.success("黄金集已更新");
    } catch (error) {
      toastApiError(error, push);
    } finally {
      setSaving(false);
    }
  }

  async function onRunRegression() {
    setRunning(true);
    try {
      const run = await runKbEvalRegression(kbId);
      await refreshRuns(run);
      if (run.gate_passed) toast.success("检索回归完成，门禁通过");
      else toast.error(run.report?.gate_error || "检索回归完成，门禁未通过");
    } catch (error) {
      toastApiError(error, push);
    } finally {
      setRunning(false);
    }
  }

  async function onReplayHistory() {
    if (!replayRunId) {
      toast.error("请选择一次历史运行");
      return;
    }
    setReplaying(true);
    try {
      const run = await replayKbEval(kbId, { runId: replayRunId });
      await refreshRuns(run);
      toast.success("离线回放完成");
    } catch (error) {
      toastApiError(error, push);
    } finally {
      setReplaying(false);
    }
  }

  async function onReplayUpload(file: File) {
    setReplaying(true);
    try {
      const run = await replayKbEval(kbId, { file });
      await refreshRuns(run);
      toast.success("离线回放完成");
    } catch (error) {
      toastApiError(error, push);
    } finally {
      setReplaying(false);
    }
  }

  async function previewEvalFile(file: File, title: string, language: "json" | "jsonl") {
    const content = await file.text();
    openPreview({
      kind: "text",
      title,
      subtitle: file.name,
      language,
      content,
    });
  }

  const report = latest?.report;
  const configured = Boolean(config?.configured);

  return (
    <AdminSection
      id="evaluation"
      icon={ClipboardList}
      title="测评"
      description="黄金集检索回归会查询当前索引；离线回放只重算分数；线上监控看真实对话里的检索健康。"
      className="mt-0"
    >
      {loading || !config ? (
        <StateView
          variant="loading"
          title="正在加载测评配置"
          description="读取黄金集、历史运行和监控快照。"
        />
      ) : (
        <Tabs
          value={activeTab}
          onValueChange={(value) => setActiveTab(value as EvalTab)}
          className="space-y-4"
        >
          <TabsList>
            <TabsTrigger value="config">黄金集配置</TabsTrigger>
            <TabsTrigger value="regression">检索回归</TabsTrigger>
            <TabsTrigger value="replay">离线回放</TabsTrigger>
            <TabsTrigger value="monitor">线上监控</TabsTrigger>
          </TabsList>

          {activeTab === "config" ? (
            <TabsContent value="config">
            <AdminPanel
              title="黄金集配置"
              subtitle="每个知识库绑定一份 JSONL 问题集和可选门禁阈值。"
              toolbar={
                <div className="flex flex-wrap items-center gap-2">
                  {templates.map((tpl) => (
                    <Button
                      key={tpl.id}
                      type="button"
                      variant="outline"
                      disabled={saving}
                      onClick={() => void onImportTemplate(tpl.id as "roogoo")}
                    >
                      导入 {tpl.name}
                    </Button>
                  ))}
                </div>
              }
            >
              <div className="space-y-3 p-4 text-sm">
                {configured ? (
                  <p className="text-muted">
                    {config.case_count} 条用例 · K={config.k}
                    {config.updated_at ? ` · 更新于 ${formatAdminDate(config.updated_at)}` : ""}
                  </p>
                ) : (
                  <p className="text-muted">尚未配置黄金集。上传 JSONL，或从 Roogoo 模板导入。</p>
                )}
                {configured && (
                  <dl className="grid gap-2 sm:grid-cols-3">
                    <MetricChip label="Recall@K 门禁" value={metricPct(config.minimums.recall_at_k ?? null)} />
                    <MetricChip label="MRR 门禁" value={metricPct(config.minimums.mrr ?? null)} />
                    <MetricChip label="nDCG@K 门禁" value={metricPct(config.minimums.ndcg_at_k ?? null)} />
                  </dl>
                )}
                <div className="grid gap-3 sm:grid-cols-2">
                  <FileUploadSurface
                    accept=".jsonl,.json,text/plain"
                    busy={saving}
                    label="黄金集 JSONL"
                    title="点击选择文件"
                    description="支持 .jsonl / .json"
                    selectedNames={goldenFile ? [goldenFile.name] : []}
                    onPick={(files) => setGoldenFile(files[0] ?? null)}
                    onPreview={
                      goldenFile
                        ? () => void previewEvalFile(goldenFile, "黄金集 JSONL", "jsonl")
                        : undefined
                    }
                  />
                  <FileUploadSurface
                    accept=".json,text/plain"
                    busy={saving}
                    label="门禁 JSON（可选）"
                    title="点击选择文件"
                    description="支持 .json"
                    selectedNames={gateFile ? [gateFile.name] : []}
                    onPick={(files) => setGateFile(files[0] ?? null)}
                    onPreview={
                      gateFile
                        ? () => void previewEvalFile(gateFile, "门禁 JSON", "json")
                        : undefined
                    }
                  />
                </div>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  <Button type="button" variant="outline" disabled={saving} onClick={() => void onUploadConfig()}>
                    <Upload className="h-4 w-4" />
                    保存配置
                  </Button>
                </div>
              </div>
            </AdminPanel>
            </TabsContent>
          ) : null}

          {activeTab === "regression" ? (
            <TabsContent value="regression">
            <AdminPanel
              title="黄金集检索回归"
              subtitle="对当前索引重新执行 search_kb，再按文档 ID 计算 Recall@K / MRR / nDCG。"
              toolbar={
                <Button type="button" disabled={!configured || running} onClick={() => void onRunRegression()}>
                  {running ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                  {running ? "正在检索…" : "运行回归"}
                </Button>
              }
            >
              <EvalReportBlock
                emptyTitle="还没有回归结果"
                emptyDescription="配置黄金集后点击「运行回归」。这会查询当前向量索引，不是离线回放。"
                run={latest}
                report={report}
              />
            </AdminPanel>
            </TabsContent>
          ) : null}

          {activeTab === "replay" ? (
            <TabsContent value="replay">
            <AdminPanel
              title="离线回放"
              subtitle="不重新检索，只用已保存的 retrieval.jsonl 对照当前黄金集重算分数。"
              toolbar={
                <div className="flex flex-wrap items-center gap-2">
                  <Select
                    value={replayRunId}
                    onChange={(e) => setReplayRunId(e.target.value)}
                    options={[
                      { value: "", label: "选择历史运行" },
                      ...runs.map((run) => ({
                        value: run.id,
                        label: `${run.run_type === "replay" ? "回放" : "回归"} · ${formatAdminDate(run.created_at)}`,
                      })),
                    ]}
                    className="h-[var(--control-h)] min-w-[12rem] admin-select-trigger"
                    contentAlign="end"
                    contentPosition="popper"
                  />
                  <Button type="button" variant="outline" disabled={!configured || replaying || !replayRunId} onClick={() => void onReplayHistory()}>
                    回放选中运行
                  </Button>
                </div>
              }
            >
              <div className="space-y-3 p-4">
                <FileUploadSurface
                  accept=".jsonl,.json,text/plain"
                  busy={replaying}
                  disabled={!configured}
                  label="retrieval.jsonl"
                  title="点击选择文件"
                  busyTitle="正在回放…"
                  description="按当前黄金集对齐并立即回放"
                  selectedNames={replayFile ? [replayFile.name] : []}
                  onPick={(files) => {
                    const file = files[0];
                    if (!file) return;
                    setReplayFile(file);
                    void onReplayUpload(file);
                  }}
                  onPreview={
                    replayFile
                      ? () => void previewEvalFile(replayFile, "retrieval.jsonl", "jsonl")
                      : undefined
                  }
                />
                {report?.missing_prediction_ids?.length ? (
                  <StateView
                    variant="notice"
                    density="compact"
                    title="黄金集已更新，部分用例缺少检索结果"
                    description={`${report.missing_prediction_ids.join("、")}。请重新运行检索回归。`}
                  />
                ) : null}
                <p className="text-xs text-muted">最近 {runs.length} 次运行会出现在上方列表；上传文件按当前黄金集的 case id 对齐，多余 id 会被忽略。</p>
              </div>
            </AdminPanel>
            </TabsContent>
          ) : null}

          {activeTab === "monitor" ? (
            <TabsContent value="monitor">
            <AdminPanel
              title="线上监控"
              subtitle="真实对话中的检索健康，不是黄金集分数。"
              busy={monitorBusy}
              busyTitle="正在刷新监控"
              toolbar={
                <div className="flex items-center gap-2">
                  <Select
                    value={hours}
                    onChange={(e) => {
                      setHours(e.target.value);
                      void refreshMonitor(e.target.value);
                    }}
                    options={[
                      { value: "24", label: "过去 24 小时" },
                      { value: "168", label: "过去 7 天" },
                    ]}
                    className="h-[var(--control-h)] admin-select-trigger"
                    contentAlign="end"
                    contentPosition="popper"
                  />
                  <Button type="button" variant="outline" disabled={monitorBusy} onClick={() => void refreshMonitor()}>
                    <RefreshCw className={cn("h-4 w-4", monitorBusy && "animate-spin")} />
                    刷新
                  </Button>
                </div>
              }
            >
              {monitor ? (
                <MonitorBlock snapshot={monitor} />
              ) : (
                <StateView
                  density="compact"
                  title="暂无监控数据"
                  description="完成对话后，这里会显示检索健康指标。"
                  className="m-4"
                />
              )}
            </AdminPanel>
            </TabsContent>
          ) : null}
        </Tabs>
      )}
    </AdminSection>
  );
}

function MetricChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-surface-border/80 bg-surface px-3 py-2">
      <div className="text-[11px] text-muted">{label}</div>
      <div className="mt-1 font-mono text-sm font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function EvalReportBlock({
  run,
  report,
  emptyTitle,
  emptyDescription,
}: {
  run: KbEvalRun | null;
  report: KbEvalReport | undefined;
  emptyTitle: string;
  emptyDescription: string;
}) {
  if (!run || !report) {
    return (
      <StateView
        density="compact"
        title={emptyTitle}
        description={emptyDescription}
        className="m-4"
      />
    );
  }
  const metrics = report.metrics;
  const allCases = report.per_case;
  const passedCount = allCases.filter((row) => row.recall >= 1).length;
  const failedCount = allCases.length - passedCount;
  return (
    <div className="space-y-4 p-4">
      <div className={cn("flex items-center gap-2 rounded-lg border p-3 text-sm", run.gate_passed ? "border-success/30 bg-success/10 text-success" : "border-danger/35 bg-danger/10 text-danger")}>
        {run.gate_passed ? <CheckCircle2 className="h-4 w-4" /> : <TriangleAlert className="h-4 w-4" />}
        {run.gate_passed ? "门禁通过" : report.gate_error || "门禁未通过"}
        <span className="ml-auto text-xs text-muted">
          {passedCount}/{allCases.length} 通过 · {formatAdminDate(run.created_at)}
        </span>
      </div>
      <div className="grid gap-2 sm:grid-cols-4">
        <MetricChip label="Recall@K" value={metricPct(metrics.recall_at_k)} />
        <MetricChip label="MRR" value={metricPct(metrics.mrr)} />
        <MetricChip label="nDCG@K" value={metricPct(metrics.ndcg_at_k)} />
        <MetricChip label="Precision@K" value={metricPct(metrics.precision_at_k)} />
      </div>
      {allCases.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-muted">
              <tr>
                <th className="py-2 pr-3 font-medium">用例</th>
                <th className="py-2 pr-3 font-medium">Recall</th>
                <th className="py-2 pr-3 font-medium">期望文档</th>
                <th className="py-2 font-medium">实际 Top-K</th>
              </tr>
            </thead>
            <tbody>
              {allCases.map((row) => (
                <CaseRow key={row.id} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CaseRow({ row }: { row: KbEvalPerCase }) {
  const hit = row.recall >= 1;
  return (
    <tr className={cn("border-t border-surface-border/60 align-top", hit ? "bg-success/5" : "bg-danger/5")}>
      <td className="py-2 pr-3 font-mono">
        <span className={cn("inline-block h-2 w-2 rounded-full mr-1.5", hit ? "bg-success" : "bg-danger")} />
        {row.id}
      </td>
      <td className={cn("py-2 pr-3 tabular-nums font-semibold", hit ? "text-success" : "text-danger")}>{metricPct(row.recall)}</td>
      <td className="py-2 pr-3 font-mono text-[11px]">{row.expected_document_ids.join(", ") || "—"}</td>
      <td className="py-2 font-mono text-[11px]">{row.retrieved_document_ids.join(", ") || "—"}</td>
    </tr>
  );
}

function MonitorBlock({ snapshot }: { snapshot: KbEvalMonitorSnapshot }) {
  const { metrics } = snapshot;
  return (
    <div className="space-y-3 p-4">
      {snapshot.scope_note ? <p className="text-xs text-muted">{snapshot.scope_note}</p> : null}
      {!snapshot.sample_sufficient ? (
        <StateView
          variant="notice"
          density="compact"
          title="样本尚不足以触发告警"
          description={`当前 ${metrics.retrieval_calls} 次检索；至少 ${snapshot.min_calls} 次后才会按阈值判断。`}
        />
      ) : snapshot.alerts.length ? (
        <div className="space-y-1 rounded-lg border border-danger/35 bg-danger/10 p-3 text-sm text-danger" role="alert">
          <div className="flex items-center gap-2 font-semibold">
            <TriangleAlert className="h-4 w-4" />
            发现 {snapshot.alerts.length} 项告警
          </div>
          {snapshot.alerts.map((alert) => (
            <p key={alert.code}>
              {alert.message}：{alert.value <= 1 ? percent(alert.value) : String(alert.value)}（阈值{" "}
              {alert.threshold <= 1 ? percent(alert.threshold) : String(alert.threshold)}）
            </p>
          ))}
        </div>
      ) : (
        <div className="flex items-center gap-2 rounded-lg border border-success/30 bg-success/10 p-3 text-sm text-success">
          <CheckCircle2 className="h-4 w-4" />
          当前样本内的检索指标均在阈值范围内。
        </div>
      )}
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <MonitorChip icon={Database} label="检索调用" value={metrics.retrieval_calls.toLocaleString()} detail={`${metrics.kb_calls} KB · ${metrics.kg_calls} KG`} />
        <MonitorChip icon={AlertTriangle} label="工具错误率" value={percent(metrics.error_rate)} detail={`${metrics.error_calls} 次失败`} />
        <MonitorChip icon={Gauge} label="空检索率" value={metrics.empty_rate == null ? "—" : percent(metrics.empty_rate)} detail={metrics.empty_rate == null ? "等待新 Trace 字段" : `${metrics.empty_calls}/${metrics.measurable_empty_calls} 次`} />
        <MonitorChip icon={Timer} label="P95 延迟" value={metrics.p95_latency_ms == null ? "—" : `${metrics.p95_latency_ms} ms`} detail={`相关度 ${metrics.avg_top_score == null ? "—" : metrics.avg_top_score.toFixed(3)}`} />
      </div>
    </div>
  );
}

function MonitorChip({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: typeof Database;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-lg border border-surface-border/80 bg-surface p-3">
      <div className="flex items-center justify-between gap-2 text-xs text-muted">
        {label}
        <Icon className="h-3.5 w-3.5" />
      </div>
      <div className="mt-2 text-lg font-semibold tabular-nums">{value}</div>
      <p className="mt-1 text-[11px] text-muted">{detail}</p>
    </div>
  );
}
