"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Code2, FileText, GitCompareArrows, History, RefreshCw, Save, Send, ShieldCheck, X } from "lucide-react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { PageSkeleton, StateView } from "@/components/ui/state-view";
import { cn } from "@/lib/cn";
import {
  getPromptTemplate,
  listPromptTemplates,
  publishPromptVersion,
  rollbackPromptVersion,
  savePromptDraft,
  type AdminPromptTemplateDetail,
  type AdminPromptTemplateSummary,
  type AdminPromptAuditEvent,
  type AdminPromptVersion,
} from "@/lib/admin-api";
import { toast } from "@/lib/toast";

type PendingPromptAction = {
  kind: "publish" | "rollback";
  version: AdminPromptVersion;
};

type PromptBaseline = {
  label: string;
  content: string;
};

function getChangeSummary(before: string, after: string) {
  const beforeLines = before.split("\n");
  const afterLines = after.split("\n");
  const remaining = new Map<string, number>();
  for (const line of beforeLines) remaining.set(line, (remaining.get(line) ?? 0) + 1);

  let added = 0;
  for (const line of afterLines) {
    const count = remaining.get(line) ?? 0;
    if (count > 0) remaining.set(line, count - 1);
    else added += 1;
  }
  const removedLines: string[] = [];
  for (const line of beforeLines) {
    const count = remaining.get(line) ?? 0;
    if (count > 0) {
      removedLines.push(line);
      remaining.set(line, count - 1);
    }
  }
  const addedLines: string[] = [];
  const original = new Map<string, number>();
  for (const line of beforeLines) original.set(line, (original.get(line) ?? 0) + 1);
  for (const line of afterLines) {
    const count = original.get(line) ?? 0;
    if (count > 0) original.set(line, count - 1);
    else addedLines.push(line);
  }
  return {
    beforeLines: beforeLines.length,
    afterLines: afterLines.length,
    added,
    removed: removedLines.length,
    addedLines,
    removedLines,
    reordered: before !== after && added === 0 && removedLines.length === 0,
  };
}

function changedLinesPreview(lines: string[]) {
  if (lines.length === 0) return "（没有独有文本行）";
  const preview = lines.slice(0, 14).map((line) => line || "（空行）").join("\n");
  return lines.length > 14 ? `${preview}\n…（其余 ${lines.length - 14} 行）` : preview;
}

function formatAuditTime(value: string | null) {
  if (!value) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function auditEventLabel(event: AdminPromptAuditEvent) {
  if (event.action === "draft_saved") return `保存草稿 v${event.version}`;
  if (event.action === "rollback_published") return `由 v${event.source_version ?? "?"} 回滚并发布为 v${event.version}`;
  return `发布 v${event.version}`;
}

export default function AdminPromptsPage() {
  const [templates, setTemplates] = useState<AdminPromptTemplateSummary[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminPromptTemplateDetail | null>(null);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingPromptAction | null>(null);
  const [compareVersion, setCompareVersion] = useState<AdminPromptVersion | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadList = useCallback(async () => {
    const response = await listPromptTemplates();
    setTemplates(response.templates);
    setSelectedKey((current) => current ?? response.templates[0]?.key ?? null);
  }, []);

  const loadDetail = useCallback(async (key: string) => {
    setDetailLoading(true);
    try {
      const next = await getPromptTemplate(key);
      setDetail(next);
      setContent(next.versions[0]?.content ?? next.fallback_content);
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadList().catch((error) => toast.error((error as Error).message)).finally(() => setLoading(false));
  }, [loadList]);

  useEffect(() => {
    if (selectedKey) void loadDetail(selectedKey);
  }, [loadDetail, selectedKey]);

  const newest = detail?.versions[0] ?? null;
  const dirty = content.trim() !== (newest?.content ?? detail?.fallback_content ?? "").trim();
  const refresh = async () => {
    setLoading(true);
    try {
      await loadList();
      if (selectedKey) await loadDetail(selectedKey);
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const saveDraft = async () => {
    if (!detail) return;
    setSaving(true);
    try {
      const saved = await savePromptDraft(detail.key, content);
      toast.success(`已保存草稿 v${saved.version}`);
      await loadList();
      await loadDetail(detail.key);
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const publish = async (version: AdminPromptVersion) => {
    if (!detail) return;
    setPublishing(true);
    try {
      await publishPromptVersion(detail.key, version.version);
      toast.success(`已发布 v${version.version}，新会话将使用此版本。`);
      await loadList();
      await loadDetail(detail.key);
      setPendingAction(null);
    } catch (error) {
      const message = (error as Error).message;
      setActionError(message);
      toast.error(message);
    } finally {
      setPublishing(false);
    }
  };

  const rollback = async (version: AdminPromptVersion) => {
    if (!detail) return;
    setPublishing(true);
    try {
      const published = await rollbackPromptVersion(detail.key, version.version);
      toast.success(`已基于 v${version.version} 发布回滚版本 v${published.version}。`);
      await loadList();
      await loadDetail(detail.key);
      setPendingAction(null);
    } catch (error) {
      const message = (error as Error).message;
      setActionError(message);
      toast.error(message);
    } finally {
      setPublishing(false);
    }
  };

  const publishedBaseline = useMemo<PromptBaseline | null>(() => {
    if (!detail) return null;
    const published = detail.versions.find((version) => version.status === "published");
    return published
      ? { label: `当前已发布 v${published.version}`, content: published.content }
      : { label: "当前代码默认", content: detail.fallback_content };
  }, [detail]);
  const compareSummary = pendingAction && publishedBaseline
    ? getChangeSummary(publishedBaseline.content, pendingAction.version.content)
    : null;
  const selectedComparison = compareVersion && publishedBaseline
    ? getChangeSummary(publishedBaseline.content, compareVersion.content)
    : null;

  const requestAction = (kind: PendingPromptAction["kind"], version: AdminPromptVersion) => {
    setActionError(null);
    setPendingAction({ kind, version });
  };

  const confirmAction = async () => {
    if (!pendingAction) return;
    if (pendingAction.kind === "publish") await publish(pendingAction.version);
    else await rollback(pendingAction.version);
  };

  if (loading && templates.length === 0) {
    return <PageSkeleton />;
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-col gap-4 border-b border-surface-border/70 pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium text-brand">平台控制面</p>
          <h2 className="mt-2 text-balance text-2xl font-semibold text-ink">提示词管理</h2>
          <p className="mt-2 max-w-3xl text-pretty text-sm leading-6 text-muted">
            编辑业务回答规则，保存为草稿后再发布。安全防护、工具权限和检索证据边界仍由运行时强制追加。
          </p>
        </div>
        <Button type="button" variant="outline" onClick={() => void refresh()} disabled={loading}>
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          刷新
        </Button>
      </header>

      <div className="grid gap-5 xl:grid-cols-[17rem_minmax(0,1fr)]">
        <aside className="space-y-2" aria-label="提示词模板列表">
          {templates.map((template) => {
            const active = template.key === selectedKey;
            return (
              <button
                key={template.key}
                type="button"
                onClick={() => {
                  setSelectedKey(template.key);
                  setCompareVersion(null);
                  setPendingAction(null);
                  setActionError(null);
                }}
                className={cn(
                  "w-full rounded-lg border px-4 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30",
                  active ? "border-brand/35 bg-brand/10" : "border-surface-border/80 bg-surface hover:bg-surface-2/55"
                )}
                aria-current={active ? "page" : undefined}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-semibold text-ink">{template.display_name}</span>
                  {template.source === "registry" ? <span className="chip chip-success">v{template.published_version}</span> : <span className="chip chip-muted">代码默认</span>}
                </div>
                <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted">{template.description}</p>
              </button>
            );
          })}
        </aside>

        {detailLoading || !detail ? (
          <StateView variant="loading" title="正在读取模板" description="正在加载版本与变量约束。" />
        ) : (
          <section className="admin-panel overflow-hidden" aria-busy={saving || publishing}>
            <div className="flex flex-col gap-3 border-b border-surface-border/70 bg-surface-2/35 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Code2 className="h-4 w-4 text-brand" aria-hidden />
                  <h3 className="text-base font-semibold text-ink">{detail.display_name}</h3>
                  {detail.published_version ? <span className="chip chip-success">已发布 v{detail.published_version}</span> : <span className="chip chip-muted">使用代码默认</span>}
                </div>
                <p className="mt-1 text-sm leading-6 text-muted">{detail.description}</p>
                {detail.allowed_variables.length > 0 ? <p className="mt-2 text-xs text-muted">可用变量：{detail.allowed_variables.map((variable) => `{{${variable}}}`).join("、")}</p> : null}
              </div>
              <div className="flex shrink-0 flex-wrap gap-2">
                <Button type="button" variant="outline" onClick={() => setContent(detail.fallback_content)} disabled={saving || publishing}>
                  <FileText className="h-4 w-4" />
                  恢复代码默认
                </Button>
                <Button type="button" onClick={() => void saveDraft()} disabled={!dirty || saving || publishing}>
                  <Save className="h-4 w-4" />
                  {saving ? "保存中" : "保存草稿"}
                </Button>
              </div>
            </div>

            <div className="p-5">
              <label className="block text-sm font-medium text-ink" htmlFor="prompt-content">模板内容</label>
              <textarea
                id="prompt-content"
                className="admin-input mt-2 min-h-96 w-full resize-y font-mono text-xs leading-6"
                value={content}
                onChange={(event) => setContent(event.target.value)}
                spellCheck={false}
              />
              <p className="mt-2 text-xs text-muted">发布只影响之后开始的请求；历史会话与既有 Trace 不会被改写。</p>
            </div>

            <div className="border-t border-surface-border/70 px-5 py-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-ink"><History className="h-4 w-4 text-brand" />版本历史</div>
              {detail.versions.length === 0 ? (
                <StateView variant="notice" density="compact" title="尚未创建版本" description="当前使用代码默认模板。修改后先保存草稿，再选择发布。" className="mt-3" />
              ) : (
                <>
                  {compareVersion && publishedBaseline && selectedComparison ? (
                    <section className="mt-3 rounded-lg border border-brand/20 bg-brand/5 p-4" aria-label="版本内容对比">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold text-ink">与当前版本的差异</p>
                          <p className="mt-1 text-xs text-muted">{publishedBaseline.label} → v{compareVersion.version}：新增 {selectedComparison.added} 行，删除 {selectedComparison.removed} 行。{selectedComparison.reordered ? "文本行相同，但行顺序已调整。" : ""}</p>
                        </div>
                        <Button type="button" size="icon-sm" variant="ghost" onClick={() => setCompareVersion(null)} aria-label="关闭版本对比"><X className="h-4 w-4" /></Button>
                      </div>
                      <div className="mt-3 grid gap-3 lg:grid-cols-2">
                        <div className="min-w-0 rounded-md border border-surface-border/70 bg-surface p-3">
                          <p className="text-xs font-medium text-muted">当前版本中将移除的文本行</p>
                          <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5 text-ink">{changedLinesPreview(selectedComparison.removedLines)}</pre>
                        </div>
                        <div className="min-w-0 rounded-md border border-brand/20 bg-surface p-3">
                          <p className="text-xs font-medium text-brand">v{compareVersion.version} 中将新增的文本行</p>
                          <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5 text-ink">{changedLinesPreview(selectedComparison.addedLines)}</pre>
                        </div>
                      </div>
                    </section>
                  ) : null}
                  <ul className="mt-3 divide-y divide-surface-border/70 overflow-hidden rounded-lg border border-surface-border/80">
                    {detail.versions.map((version) => (
                    <li key={version.id} className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                      <div className="flex min-w-0 items-center gap-2 text-sm">
                        <span className="font-semibold tabular-nums text-ink">v{version.version}</span>
                        <span className={cn("chip", version.status === "published" ? "chip-success" : version.status === "draft" ? "chip-warning" : "chip-muted")}>{version.status === "published" ? "已发布" : version.status === "draft" ? "草稿" : "已归档"}</span>
                        <span className="truncate font-mono text-xs text-muted">{version.digest.slice(0, 12)}</span>
                      </div>
                      <div className="flex shrink-0 flex-wrap gap-2">
                        {version.status !== "published" ? <Button type="button" size="sm" variant="ghost" onClick={() => setCompareVersion(version)} disabled={publishing || saving}><GitCompareArrows className="h-3.5 w-3.5" />对比</Button> : null}
                        {version.status === "draft" ? <Button type="button" size="sm" onClick={() => requestAction("publish", version)} disabled={publishing || saving}><Send className="h-3.5 w-3.5" />发布</Button> : null}
                        {version.status !== "published" ? <Button type="button" size="sm" variant="outline" onClick={() => requestAction("rollback", version)} disabled={publishing || saving}><CheckCircle2 className="h-3.5 w-3.5" />回滚至此</Button> : null}
                      </div>
                    </li>
                    ))}
                  </ul>
                  {detail.audit_events.length > 0 ? (
                    <section className="mt-5" aria-label="发布审计记录">
                      <div className="flex items-center gap-2 text-sm font-semibold text-ink"><ShieldCheck className="h-4 w-4 text-brand" />发布审计</div>
                      <p className="mt-1 text-xs leading-5 text-muted">仅记录后台草稿、发布与回滚操作；历史记录不会因后续发布被覆盖。</p>
                      <ol className="mt-3 space-y-2">
                        {detail.audit_events.map((event) => (
                          <li key={event.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-md border border-surface-border/70 bg-surface-2/30 px-3 py-2 text-xs">
                            <span className="font-medium text-ink">{auditEventLabel(event)}</span>
                            <span className="text-muted">{event.actor_email ?? (event.actor_admin_id ? `管理员 ${event.actor_admin_id.slice(0, 8)}` : "系统/历史记录")} · <time dateTime={event.created_at ?? undefined}>{formatAuditTime(event.created_at)}</time></span>
                          </li>
                        ))}
                      </ol>
                    </section>
                  ) : null}
                </>
              )}
            </div>
          </section>
        )}
      </div>
      <ConfirmDialog
        open={pendingAction !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingAction(null);
            setActionError(null);
          }
        }}
        title={pendingAction?.kind === "rollback" ? `确认回滚至 v${pendingAction.version.version}` : `确认发布 v${pendingAction?.version.version ?? ""}`}
        confirmLabel={pendingAction?.kind === "rollback" ? "确认回滚并发布" : "确认发布"}
        busy={publishing}
        onConfirm={confirmAction}
        description={pendingAction && publishedBaseline && compareSummary ? (
          <div className="space-y-3">
            <p>{pendingAction.kind === "rollback" ? "系统会基于该历史版本创建一个新的发布版本；不会覆盖既有历史。" : "发布后，之后开始的请求会使用此版本；历史会话不受影响。"}</p>
            <div className="rounded-md border border-surface-border/80 bg-surface-2/50 px-3 py-2 text-xs leading-5 text-ink">
              <p className="font-medium">变更摘要：{publishedBaseline.label} → v{pendingAction.version.version}</p>
              <p className="mt-1 text-muted">{compareSummary.beforeLines} → {compareSummary.afterLines} 行，新增 {compareSummary.added} 行，删除 {compareSummary.removed} 行。</p>
            </div>
            {actionError ? <p className="text-xs font-medium text-danger" role="alert">操作未完成：{actionError}</p> : null}
          </div>
        ) : null}
      />
    </div>
  );
}
