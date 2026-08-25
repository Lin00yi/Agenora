"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Code2, FileText, History, RefreshCw, Save, Send } from "lucide-react";

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
  type AdminPromptVersion,
} from "@/lib/admin-api";
import { toast } from "@/lib/toast";

export default function AdminPromptsPage() {
  const [templates, setTemplates] = useState<AdminPromptTemplateSummary[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminPromptTemplateDetail | null>(null);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);

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
    } catch (error) {
      toast.error((error as Error).message);
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
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setPublishing(false);
    }
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
                onClick={() => setSelectedKey(template.key)}
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
                <ul className="mt-3 divide-y divide-surface-border/70 overflow-hidden rounded-lg border border-surface-border/80">
                  {detail.versions.map((version) => (
                    <li key={version.id} className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                      <div className="flex min-w-0 items-center gap-2 text-sm">
                        <span className="font-semibold tabular-nums text-ink">v{version.version}</span>
                        <span className={cn("chip", version.status === "published" ? "chip-success" : version.status === "draft" ? "chip-warning" : "chip-muted")}>{version.status === "published" ? "已发布" : version.status === "draft" ? "草稿" : "已归档"}</span>
                        <span className="truncate font-mono text-xs text-muted">{version.digest.slice(0, 12)}</span>
                      </div>
                      <div className="flex shrink-0 flex-wrap gap-2">
                        {version.status === "draft" ? <Button type="button" size="sm" onClick={() => void publish(version)} disabled={publishing || saving}><Send className="h-3.5 w-3.5" />发布</Button> : null}
                        {version.status !== "published" ? <Button type="button" size="sm" variant="outline" onClick={() => void rollback(version)} disabled={publishing || saving}><CheckCircle2 className="h-3.5 w-3.5" />回滚至此</Button> : null}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
