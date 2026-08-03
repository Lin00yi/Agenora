"use client";

import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Plus,
  Trash2,
  BookOpen,
  ChevronLeft,
  Lock,
  Sparkles,
  FileText,
  Hash,
  Users,
  Eye,
  X,
  ChevronDown,
  ChevronRight,
  KeyRound,
  AlertCircle,
} from "lucide-react";
import { toast } from "sonner";

import { getToken } from "@/lib/auth";
import { listKbs, createKb, deleteKb, type KB, type CreateKbBody } from "@/lib/kb-api";
import {
  getMySettings,
  probeEmbedding,
  probeReranker,
  saveEmbeddingSettings,
  saveRerankerSettings,
  type MySettings,
  type EmbeddingProvider,
  type RerankerProvider,
} from "@/lib/settings-api";
import { toastApiError } from "@/lib/byok-toast";
import { cn } from "@/lib/cn";
import Dialog from "@/components/Dialog";
import Select from "@/components/Select";
import ThemeToggle from "@/components/ThemeToggle";
import { LoadingState, StateView } from "@/components/ui/state-view";

export default function KbsPage() {
  const router = useRouter();
  const [kbs, setKbs] = useState<KB[]>([]);
  const [loading, setLoading] = useState(true);

  const [createOpen, setCreateOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<KB | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    listKbs()
      .then(setKbs)
      .catch((e) => toast.error((e as Error).message))
      .finally(() => setLoading(false));
  }, [router]);

  const onCreated = (kb: KB) => {
    setKbs((prev) => [kb, ...prev]);
    setCreateOpen(false);
    toast.success(`已创建：${kb.name}`);
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteKb(pendingDelete.id);
      setKbs((prev) => prev.filter((k) => k.id !== pendingDelete.id));
      toast.success(`已删除：${pendingDelete.name}`);
      setPendingDelete(null);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="app-page min-h-dvh text-fg">
      <header className="app-page-header border-b">
        <div className="mx-auto flex h-14 max-w-5xl items-center gap-3 px-4 sm:px-6">
          <Link
            href="/"
            className="app-nav-link app-nav-link-compact"
          >
            <ChevronLeft className="h-4 w-4" />
            <span>返回对话</span>
          </Link>
          <div className="flex-1" />
          <ThemeToggle compact />
        </div>
      </header>

      <main className="app-page-content mx-auto max-w-5xl px-4 py-7 sm:px-6 sm:py-10">
        <div className="mb-6 flex flex-col gap-3 border-b border-surface-border/70 pb-5 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-2xl font-semibold tracking-tight text-fg">
              <span className="admin-icon-tile admin-icon-tile-brand rounded-md">
                <BookOpen className="h-5 w-5" />
              </span>
              我的知识库
            </h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
              创建与管理资料库；新建时可单独配置 embedding / reranker。
            </p>
          </div>
          <button
            onClick={() => setCreateOpen(true)}
            className="admin-btn-primary w-full sm:w-auto"
            type="button"
          >
            <Plus className="h-4 w-4" />
            新建知识库
          </button>
        </div>

        {loading ? (
          <LoadingState label="正在读取知识库" description="正在同步文档、分块和成员信息。" />
        ) : kbs.length === 0 ? (
          <StateView
            title="还没有知识库"
            description="从一个资料库开始，把文档变成可追问、可引用的答案。"
            action={
              <button onClick={() => setCreateOpen(true)} className="admin-btn-primary" type="button">
                <Plus className="h-4 w-4" />
                新建知识库
              </button>
            }
          />
        ) : (
          <ul className="grid min-w-0 gap-2">
            {kbs.map((kb) => {
              const isOwner = kb.my_role === "owner";
              const isEditor = kb.my_role === "editor";
              const isViewer = kb.my_role === "viewer" && !kb.is_system;
              return (
                <li
                  key={kb.id}
                  className="group min-w-0 overflow-hidden rounded-lg border border-surface-border/80 bg-surface transition-[background-color,border-color] hover:border-brand/30 hover:bg-surface-2/40"
                >
                  <div className="flex min-w-0 items-start gap-3 px-4 py-3.5 sm:gap-3.5 sm:px-5">
                    <span className="admin-icon-tile admin-icon-tile-muted mt-0.5 shrink-0 transition group-hover:border-brand/25 group-hover:bg-brand/10 group-hover:text-brand">
                        {kb.is_system ? (
                          <Lock className="h-4 w-4 text-warning" />
                        ) : isEditor ? (
                          <Users className="h-4 w-4 text-info" />
                        ) : isViewer ? (
                          <Eye className="h-4 w-4 text-muted" />
                        ) : (
                          <BookOpen className="h-4 w-4 opacity-60" />
                        )}
                    </span>
                    <Link href={`/kbs/${kb.id}`} className="min-w-0 flex-1 overflow-hidden rounded-md outline-none focus-visible:ring-2 focus-visible:ring-brand/25">
                      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                        <span className="min-w-0 break-words text-[15px] font-medium">{kb.name}</span>
                        {kb.is_system && (
                          <span className="chip chip-warning">示例</span>
                        )}
                        {kb.is_system && (
                          <span className="chip chip-muted">只读</span>
                        )}
                        {isEditor && (
                          <span className="chip chip-info">协作</span>
                        )}
                        {isViewer && (
                          <span className="chip chip-muted">只读</span>
                        )}
                      </div>
                      <div className="mt-1 line-clamp-2 break-words text-sm text-muted">
                        {kb.description || (
                          <span className="italic opacity-60">无描述</span>
                        )}
                      </div>
                      <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                        <span className="inline-flex items-center gap-1">
                          <FileText className="h-3 w-3" />
                          {kb.documents_count} 文档
                        </span>
                        <span aria-hidden className="text-surface-border">·</span>
                        <span className="inline-flex items-center gap-1">
                          <Hash className="h-3 w-3" />
                          {kb.chunks_count} 分块
                        </span>
                        {kb.embedding_model ? (
                          <>
                            <span aria-hidden className="text-surface-border">·</span>
                            <span className="max-w-[16rem] truncate font-mono text-[11px]">
                              {kb.embedding_model}
                            </span>
                          </>
                        ) : null}
                      </div>
                    </Link>
                    {isOwner && (
                      <button
                        onClick={() => setPendingDelete(kb)}
                        className={cn(
                          "admin-icon-action size-8 shrink-0 text-muted/70 opacity-100 sm:opacity-0 sm:transition-opacity sm:group-hover:opacity-100 sm:group-focus-within:opacity-100",
                          "hover:bg-danger/15 hover:text-danger"
                        )}
                        aria-label="删除知识库"
                        title="删除知识库"
                        type="button"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </main>

      <CreateKbDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={onCreated}
        onByokRedirect={(p) => router.push(p)}
      />

      <Dialog
        open={pendingDelete != null}
        onOpenChange={(o) => !o && setPendingDelete(null)}
        title={`删除知识库「${pendingDelete?.name ?? ""}」？`}
        description="这个 KB 下所有文档和向量都会一并清除。该操作不可逆。"
        variant="danger"
        confirmLabel="确认删除"
        onConfirm={confirmDelete}
        busy={deleting}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// v3-M7: KB creation dialog with optional per-KB embedding + reranker config
// ---------------------------------------------------------------------------
function CreateKbDialog({
  open,
  onClose,
  onCreated,
  onByokRedirect,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (kb: KB) => void;
  onByokRedirect: (path: string) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);

  // v3-M8: embedding section — no more "inherit/custom" toggle. Form is the
  // single source of truth; on open we prefill from user-saved cfg (provider /
  // base_url / model) and leave api_key blank with a "已保存" placeholder
  // when the user has previously saved a key. The backend transparently
  // reuses the saved decrypted key when api_key arrives empty.
  const [embedProvider, setEmbedProvider] =
    useState<EmbeddingProvider>("openai-compat");
  const [embedBaseUrl, setEmbedBaseUrl] = useState(
    "https://api.siliconflow.cn/v1"
  );
  const [embedApiKey, setEmbedApiKey] = useState("");
  const [embedModel, setEmbedModel] = useState("BAAI/bge-m3");
  const [embedDim, setEmbedDim] = useState<number | null>(null);
  const [embedProbing, setEmbedProbing] = useState(false);
  const [embedKeySaved, setEmbedKeySaved] = useState(false);
  // v3-M8.1: probe → models list → Select dropdown (mirror /settings LLMCard).
  const [embedModels, setEmbedModels] = useState<string[]>([]);
  // v3-M8.2: must successfully test the connection before "创建" enables.
  // Prefilled cfg from user-level settings counts as already-verified (the
  // user must have probed before saving it to /settings). Any edit to
  // base_url / api_key / model resets this flag, forcing a re-test. Backend
  // also probes as a second line of defense (502 on connection failure).
  const [embedVerified, setEmbedVerified] = useState(false);
  // v3-M8.3: when user has a saved api_key (has_key=true), default to a
  // compact "已使用保存的密钥（修改）" chip instead of the empty password
  // input — the "已保存（留空保持现有）" placeholder confused users into
  // thinking they had to retype the key. Toggled to input mode when they
  // explicitly click "修改" or when cfg fields drift away from the user's
  // saved cfg (so a new provider/base_url forces re-entry).
  const [embedKeyEditing, setEmbedKeyEditing] = useState(false);

  // Reranker section: "off" (default) | "custom". Same prefill behavior.
  const [rerankerMode, setRerankerMode] = useState<"off" | "custom">("off");
  const [rerankerExpanded, setRerankerExpanded] = useState(false);
  const [rerankerProvider, setRerankerProvider] =
    useState<RerankerProvider>("siliconflow");
  const [rerankerBaseUrl, setRerankerBaseUrl] = useState(
    "https://api.siliconflow.cn/v1"
  );
  const [rerankerApiKey, setRerankerApiKey] = useState("");
  const [rerankerModel, setRerankerModel] = useState(
    "BAAI/bge-reranker-v2-m3"
  );
  const [rerankerProbing, setRerankerProbing] = useState(false);
  const [rerankerKeySaved, setRerankerKeySaved] = useState(false);
  const [rerankerModels, setRerankerModels] = useState<string[]>([]);
  const [rerankerVerified, setRerankerVerified] = useState(false);
  const [rerankerKeyEditing, setRerankerKeyEditing] = useState(false);

  useEffect(() => {
    if (!open) return;
    // Reset form on open
    setName("");
    setDescription("");
    setRerankerMode("off");
    setRerankerExpanded(false);
    setEmbedApiKey("");
    setRerankerApiKey("");
    setEmbedDim(null);
    setEmbedModels([]);
    setRerankerModels([]);
    setEmbedVerified(false);
    setRerankerVerified(false);
    setEmbedKeyEditing(false);
    setRerankerKeyEditing(false);
    // v3-M8: prefill embedding/reranker form from user's saved cfg ("暗中记忆").
    // Provider + base_url + model carry over; api_key stays blank with a
    // "已保存（留空保持现有）" placeholder when has_key is true.
    getMySettings()
      .then((s) => {
        if (s.embedding.provider) {
          setEmbedProvider(s.embedding.provider as EmbeddingProvider);
        }
        if (s.embedding.base_url) setEmbedBaseUrl(s.embedding.base_url);
        if (s.embedding.model) setEmbedModel(s.embedding.model);
        if (s.embedding.dim) setEmbedDim(s.embedding.dim);
        setEmbedKeySaved(Boolean(s.embedding.has_key));
        // v3-M8.2: if user has a complete saved embedding cfg, treat the
        // prefilled form as already-verified — they must have probed before
        // saving it to /settings. Changing any field will reset this.
        if (
          s.embedding.has_key &&
          s.embedding.provider &&
          s.embedding.base_url &&
          s.embedding.model &&
          s.embedding.dim
        ) {
          setEmbedVerified(true);
        }

        if (s.reranker.provider) {
          setRerankerProvider(s.reranker.provider as RerankerProvider);
        }
        if (s.reranker.base_url) setRerankerBaseUrl(s.reranker.base_url);
        if (s.reranker.model) setRerankerModel(s.reranker.model);
        setRerankerKeySaved(Boolean(s.reranker.has_key));
        if (
          s.reranker.has_key &&
          s.reranker.provider &&
          s.reranker.base_url &&
          s.reranker.model
        ) {
          setRerankerVerified(true);
        }
      })
      .catch(() => {
        /* user has no saved cfg yet — defaults stay as-is */
      });
  }, [open]);

  // v3-M8.1: "测试连接" — probe provider; on success populate models dropdown
  // AND probe current model's dim. On failure surface the upstream error so
  // the user knows their api_key is wrong BEFORE ingest tries to use it.
  const onTestEmbedding = async () => {
    if (!embedBaseUrl) {
      toast.error("请填写 base_url");
      return;
    }
    setEmbedProbing(true);
    try {
      const r = await probeEmbedding({
        provider: embedProvider,
        base_url: embedBaseUrl,
        api_key: embedApiKey,  // backend falls back to saved key when empty
        model: embedModel || undefined,
      });
      setEmbedModels(r.models);
      if (r.dim) setEmbedDim(r.dim);
      setEmbedVerified(true);
      const dimMsg = r.dim ? ` · 当前模型 ${r.dim} 维` : "";
      toast.success(`连接成功：${r.models.length} 个模型${dimMsg}`);
    } catch (e) {
      setEmbedVerified(false);
      toast.error(e instanceof Error ? e.message : "连接失败");
    } finally {
      setEmbedProbing(false);
    }
  };

  const onTestReranker = async () => {
    if (!rerankerBaseUrl) {
      toast.error("请填写 base_url");
      return;
    }
    setRerankerProbing(true);
    try {
      const r = await probeReranker({
        provider: rerankerProvider,
        base_url: rerankerBaseUrl,
        api_key: rerankerApiKey,
      });
      setRerankerModels(r.models);
      setRerankerVerified(true);
      toast.success(`连接成功：${r.models.length} 个模型`);
    } catch (e) {
      setRerankerVerified(false);
      toast.error(e instanceof Error ? e.message : "连接失败");
    } finally {
      setRerankerProbing(false);
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    const body: CreateKbBody = {
      name: name.trim(),
      description: description.trim(),
    };

    // v3-M8: embedding is always required (per-KB). Validate before submit.
    if (!embedProvider || !embedBaseUrl || !embedModel) {
      toast.error("请补全 Embedding 配置");
      return;
    }
    if (embedDim == null) {
      toast.error("请先点「测试连接」探测向量维度");
      return;
    }
    // v3-M8.2: must have successfully tested the connection. Without this,
    // a wrong/empty api_key creates a "valid-looking" KB that 403s on first
    // upload — confusing and hard to recover from.
    if (!embedVerified) {
      toast.error("请先点「测试连接 / 拉取模型」验证 Embedding 可用");
      return;
    }
    body.embedding_provider = embedProvider;
    body.embedding_base_url = embedBaseUrl;
    body.embedding_api_key = embedApiKey;  // backend fills in saved key if empty
    body.embedding_model = embedModel;
    body.embedding_dim = embedDim;

    if (rerankerMode === "custom") {
      if (!rerankerProvider || !rerankerBaseUrl || !rerankerModel) {
        toast.error("请补全 Reranker 配置");
        return;
      }
      if (!rerankerVerified) {
        toast.error("请先点「测试连接 / 拉取模型」验证 Reranker 可用");
        return;
      }
      body.reranker_provider = rerankerProvider;
      body.reranker_base_url = rerankerBaseUrl;
      body.reranker_api_key = rerankerApiKey;
      body.reranker_model = rerankerModel;
      body.reranker_enabled = true;
    }

    setCreating(true);
    try {
      const kb = await createKb(body);

      // v3-M8: "暗中记忆" — fire-and-forget save the embedding/reranker cfg
      // to the user record so the next KB creation form prefills from it.
      // Silent on failure (cfg sync is a convenience, not a critical path).
      try {
        await saveEmbeddingSettings({
          provider: embedProvider,
          base_url: embedBaseUrl,
          api_key: embedApiKey,  // empty = keep existing (backend semantics)
          model: embedModel,
          dim: embedDim,
        });
      } catch {
        /* ignore — likely a dim conflict 409 against other un-cfg'd KBs */
      }
      if (rerankerMode === "custom") {
        try {
          await saveRerankerSettings({
            provider: rerankerProvider,
            base_url: rerankerBaseUrl,
            api_key: rerankerApiKey,
            model: rerankerModel,
            enabled: true,
          });
        } catch {
          /* ignore */
        }
      }

      onCreated(kb);
    } catch (err) {
      toastApiError(err, onByokRedirect);
    } finally {
      setCreating(false);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="presentation"
      onClick={() => !creating && onClose()}
    >
      <div className="app-modal-overlay absolute inset-0" />
      <div
        onClick={(e) => e.stopPropagation()}
        className="relative flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-surface-border/80 bg-surface shadow-[0_24px_70px_rgb(15_23_42/0.22)]"
        role="dialog"
        aria-modal="true"
      >
        <header className="flex min-h-14 shrink-0 items-center justify-between border-b border-surface-border/70 bg-surface px-5">
          <h2 className="text-base font-semibold">新建知识库</h2>
          <button
            onClick={onClose}
            disabled={creating}
            className="admin-icon-action admin-icon-action-lg"
            aria-label="关闭"
            type="button"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <form
          onSubmit={submit}
          className="min-h-0 flex-1 space-y-4 overflow-y-auto bg-surface px-5 py-5"
        >
          <FormField label="名称" required>
            <input
              required
              maxLength={128}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如：我的笔记"
              className={inputClass}
            />
          </FormField>

          <FormField label="描述（可选）">
            <input
              maxLength={512}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="一句话说明这个 KB 的用途"
              className={inputClass}
            />
          </FormField>

          {/* v3-M8: embedding always required, no inherit/custom toggle */}
          <section className="space-y-3 rounded-lg border border-surface-border/80 bg-surface-2/35 p-4 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-medium">Embedding 配置</h3>
              {embedDim != null && (
                <span className="chip chip-muted text-xs">
                  {embedModel} · {embedDim}d
                </span>
              )}
            </div>
            <p className="text-xs text-muted">
              每个 KB 独立配置 embedding 提供商。第一次填后，后续建 KB 会自动预填上次的设置。
            </p>
            <div className="grid gap-2 pt-1 sm:grid-cols-[0.9fr_1.1fr]">
              <Select
                value={embedProvider}
                onChange={(e) => {
                  setEmbedProvider(e.target.value as EmbeddingProvider);
                  setEmbedVerified(false);
                  // v3-M8.3: provider drift → backend fall-back no longer
                  // applies, force the user to re-enter (or keep typing) a key.
                  setEmbedKeyEditing(true);
                }}
                options={[
                  { value: "openai-compat", label: "OpenAI-compat" },
                  { value: "ollama", label: "Ollama" },
                ]}
                className={inputClass}
                contentAlign="start"
                contentPosition="popper"
              />
              <input
                name="embedding-base-url"
                autoComplete="off"
                inputMode="url"
                placeholder="https://api.siliconflow.cn/v1"
                value={embedBaseUrl}
                onChange={(e) => {
                  setEmbedBaseUrl(e.target.value);
                  setEmbedVerified(false);
                  // v3-M8.3: same — base_url drift breaks backend fall-back.
                  setEmbedKeyEditing(true);
                }}
                className={inputClass}
              />
            </div>
            {/* v3-M8.3: saved-key chip vs input toggle. When the user already
                saved an api_key in a prior KB creation, we show a compact
                read-only chip instead of an empty password field — the
                "已保存（留空保持现有）" placeholder was misleading. Click
                "修改" to swap to input mode for a new key. */}
            {embedKeySaved && !embedKeyEditing ? (
              <div className="flex min-h-[44px] items-center gap-3 rounded-lg border border-surface-border/80 bg-surface-2/45 px-3 py-2 text-sm shadow-sm">
                <KeyRound className="h-4 w-4 text-success" />
                <span className="min-w-0 flex-1">已使用保存的 API Key</span>
                <button
                  type="button"
                  onClick={() => {
                    setEmbedKeyEditing(true);
                    setEmbedVerified(false);
                  }}
                  className="app-mini-link app-mini-link-brand"
                >
                  修改
                </button>
              </div>
            ) : (
              <div className="relative">
                <KeyRound className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <input
                  type="password"
                  name="embedding-api-key"
                  autoComplete="new-password"
                  data-lpignore="true"
                  data-1p-ignore="true"
                  placeholder={
                    embedProvider === "ollama"
                      ? "API Key（ollama 可留空）"
                      : "API Key"
                  }
                  value={embedApiKey}
                  onChange={(e) => {
                    setEmbedApiKey(e.target.value);
                    setEmbedVerified(false);
                  }}
                  className={cn(inputClass, "pl-8 pr-16")}
                  autoFocus={embedKeyEditing && embedKeySaved}
                />
                {embedKeySaved && (
                  <button
                    type="button"
                    onClick={() => {
                      setEmbedKeyEditing(false);
                      setEmbedApiKey("");
                      setEmbedVerified(true);  // back to using saved key
                    }}
                    className="app-mini-link app-mini-link-muted absolute right-2 top-1/2 -translate-y-1/2"
                  >
                    取消
                  </button>
                )}
              </div>
            )}
            {/* v3-M8.1: 测试连接 — must succeed before model dropdown populates */}
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <span className="text-xs text-muted">
                {embedVerified ? "Embedding 已验证。" : "先验证连接，再选择或确认模型。"}
              </span>
              <button
                type="button"
                onClick={onTestEmbedding}
                disabled={embedProbing || !embedBaseUrl}
                className={secondaryActionClass}
              >
                {embedProbing ? "测试中…" : "测试连接 / 拉取模型"}
              </button>
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted">模型</label>
              {embedModels.length > 0 ? (
                <Select
                  value={embedModel}
                  onChange={(e) => {
                    setEmbedModel(e.target.value);
                    setEmbedDim(null);  // model changed → invalidate dim, re-test
                    setEmbedVerified(false);
                  }}
                  options={[
                    ...(!embedModels.includes(embedModel) && embedModel
                      ? [{ value: embedModel, label: `${embedModel}（自定义）` }]
                      : []),
                    ...embedModels.map((m) => ({ value: m, label: m })),
                  ]}
                  className={inputClass}
                  contentAlign="start"
                  contentPosition="popper"
                />
              ) : (
                <input
                  placeholder="先点「测试连接」拉模型列表 — 或手输 model id"
                  value={embedModel}
                  onChange={(e) => {
                    setEmbedModel(e.target.value);
                    setEmbedDim(null);
                    setEmbedVerified(false);
                  }}
                  className={inputClass}
                />
              )}
              {embedDim != null && (
                <p className="mt-1 text-xs text-muted">
                  向量维度：<span className="text-fg">{embedDim}</span>
                </p>
              )}
              {embedDim == null && embedModels.length > 0 && (
                <p className="mt-1 text-xs text-warning">
                  请再次点「测试连接」探测当前模型的向量维度
                </p>
              )}
            </div>
          </section>

          {/* Reranker section — keep as "off / custom" collapsible */}
          <CollapsibleSection
            title="Reranker（重排序，可选）"
            badge={rerankerMode === "off" ? "不启用" : rerankerModel}
            badgeVariant="default"
            expanded={rerankerExpanded}
            onToggle={() => setRerankerExpanded((v) => !v)}
          >
            <div className="space-y-3">
              <RadioRow
                checked={rerankerMode === "off"}
                onChange={() => setRerankerMode("off")}
                label="不启用"
                hint="默认。embedding + 检索通常已经够用。"
              />
              <RadioRow
                checked={rerankerMode === "custom"}
                onChange={() => setRerankerMode("custom")}
                label="为这个 KB 启用 reranker"
                hint="开启后这个 KB 的检索结果会经过 cross-encoder 重排（额外 100-300ms / 次）。"
              />

              {rerankerMode === "custom" && (
                <div className="space-y-2 rounded-lg border border-surface-border/80 bg-surface/50 p-3 shadow-sm">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <Select
                      value={rerankerProvider}
                      onChange={(e) => {
                        setRerankerProvider(
                          e.target.value as RerankerProvider
                        );
                        setRerankerVerified(false);
                        setRerankerKeyEditing(true);
                      }}
                      options={[
                        { value: "siliconflow", label: "SiliconFlow" },
                        { value: "cohere", label: "Cohere" },
                        { value: "openai-compat", label: "OpenAI-compat" },
                      ]}
                      className={inputClass}
                      contentAlign="start"
                      contentPosition="popper"
                    />
                    <input
                      name="reranker-base-url"
                      autoComplete="off"
                      inputMode="url"
                      placeholder="https://api.siliconflow.cn/v1"
                      value={rerankerBaseUrl}
                      onChange={(e) => {
                        setRerankerBaseUrl(e.target.value);
                        setRerankerVerified(false);
                        setRerankerKeyEditing(true);
                      }}
                      className={inputClass}
                    />
                  </div>
                  {/* v3-M8.3: same saved-key chip vs input pattern as embedding. */}
                  {rerankerKeySaved && !rerankerKeyEditing ? (
                    <div className="flex min-h-[44px] items-center gap-3 rounded-lg border border-surface-border/80 bg-surface-2/45 px-3 py-2 text-sm shadow-sm">
                      <KeyRound className="h-4 w-4 text-success" />
                      <span className="min-w-0 flex-1">已使用保存的 API Key</span>
                      <button
                        type="button"
                        onClick={() => {
                          setRerankerKeyEditing(true);
                          setRerankerVerified(false);
                        }}
                        className="app-mini-link app-mini-link-brand"
                      >
                        修改
                      </button>
                    </div>
                  ) : (
                    <div className="relative">
                      <KeyRound className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                      <input
                        type="password"
                        name="reranker-api-key"
                        autoComplete="new-password"
                        data-lpignore="true"
                        data-1p-ignore="true"
                        placeholder="API Key（自托管可留空）"
                        value={rerankerApiKey}
                        onChange={(e) => {
                          setRerankerApiKey(e.target.value);
                          setRerankerVerified(false);
                        }}
                        className={cn(inputClass, "pl-8 pr-16")}
                        autoFocus={rerankerKeyEditing && rerankerKeySaved}
                      />
                      {rerankerKeySaved && (
                        <button
                          type="button"
                          onClick={() => {
                            setRerankerKeyEditing(false);
                            setRerankerApiKey("");
                            setRerankerVerified(true);
                          }}
                          className="app-mini-link app-mini-link-muted absolute right-2 top-1/2 -translate-y-1/2"
                        >
                          取消
                        </button>
                      )}
                    </div>
                  )}
                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={onTestReranker}
                      disabled={rerankerProbing || !rerankerBaseUrl}
                      className={secondaryActionClass}
                    >
                      {rerankerProbing ? "测试中…" : "测试连接 / 拉取模型"}
                    </button>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-muted">模型</label>
                    {rerankerModels.length > 0 ? (
                      <Select
                        value={rerankerModel}
                        onChange={(e) => {
                          setRerankerModel(e.target.value);
                          setRerankerVerified(false);
                        }}
                        options={[
                          ...(!rerankerModels.includes(rerankerModel) && rerankerModel
                            ? [{ value: rerankerModel, label: `${rerankerModel}（自定义）` }]
                            : []),
                          ...rerankerModels.map((m) => ({ value: m, label: m })),
                        ]}
                        className={inputClass}
                        contentAlign="start"
                        contentPosition="popper"
                      />
                    ) : (
                      <input
                        placeholder="先点「测试连接」拉模型列表 — 或手输 model id"
                        value={rerankerModel}
                        onChange={(e) => {
                          setRerankerModel(e.target.value);
                          setRerankerVerified(false);
                        }}
                        className={inputClass}
                      />
                    )}
                  </div>
                </div>
              )}
            </div>
          </CollapsibleSection>

          <div className="sticky bottom-0 -mx-5 -mb-5 flex flex-col gap-3 border-t border-surface-border/70 bg-surface/95 px-5 py-4 backdrop-blur sm:flex-row sm:items-center sm:justify-between">
            {!embedVerified ? (
              <span className="inline-flex items-center gap-1.5 text-xs text-warning">
                <AlertCircle className="h-3.5 w-3.5" />
                请先点「测试连接 / 拉取模型」验证 Embedding 可用
              </span>
            ) : rerankerMode === "custom" && !rerankerVerified ? (
              <span className="inline-flex items-center gap-1.5 text-xs text-warning">
                <AlertCircle className="h-3.5 w-3.5" />
                请先验证 Reranker 连接
              </span>
            ) : (
              <span />
            )}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center">
              <button
                type="button"
                onClick={onClose}
                disabled={creating}
                className={secondaryActionClass}
              >
                取消
              </button>
              <button
                type="submit"
                disabled={
                  creating ||
                  !name.trim() ||
                  !embedVerified ||
                  (rerankerMode === "custom" && !rerankerVerified)
                }
                className={primaryActionClass}
              >
                <Plus className="h-4 w-4" />
                {creating ? "创建中…" : "创建知识库"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small UI helpers
// ---------------------------------------------------------------------------
const inputClass =
  "admin-input";

const primaryActionClass =
  "admin-btn-primary w-full shrink-0 sm:w-auto";

const secondaryActionClass =
  "admin-btn-secondary w-full shrink-0 sm:w-auto";

function FormField({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <label className="mb-1.5 block text-xs font-medium text-muted">
        {label}
        {required && <span className="ml-1 text-danger">*</span>}
      </label>
      {children}
    </div>
  );
}

function CollapsibleSection({
  title,
  badge,
  badgeVariant = "default",
  expanded,
  onToggle,
  children,
}: {
  title: string;
  badge?: string;
  badgeVariant?: "default" | "warning";
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-surface-border/80 bg-surface/60 shadow-sm">
      <button
        type="button"
        onClick={onToggle}
        className="flex min-h-[44px] w-full cursor-pointer items-center justify-between gap-2 px-4 py-3 text-left outline-none transition hover:bg-surface-2/60 focus-visible:ring-2 focus-visible:ring-brand/20"
      >
        <span className="text-sm font-medium">{title}</span>
        <span className="flex items-center gap-2">
          {badge && (
            <span
              className={cn(
                "chip text-xs",
                badgeVariant === "warning"
                  ? "chip-warning"
                  : "chip-muted"
              )}
            >
              {badge}
            </span>
          )}
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-muted" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted" />
          )}
        </span>
      </button>
      {expanded && <div className="border-t border-surface-border/70 px-4 py-3">{children}</div>}
    </section>
  );
}

function RadioRow({
  checked,
  onChange,
  disabled,
  label,
  hint,
}: {
  checked: boolean;
  onChange: () => void;
  disabled?: boolean;
  label: string;
  hint?: string;
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition-[background-color,border-color,box-shadow]",
        checked ? "border-brand/30 bg-brand/10 shadow-sm" : "border-transparent hover:border-surface-border hover:bg-surface-2",
        disabled && "cursor-not-allowed opacity-50"
      )}
    >
      <input
        type="radio"
        checked={checked}
        onChange={onChange}
        disabled={disabled}
        className="mt-1"
      />
      <div className="flex-1 text-sm">
        <div>{label}</div>
        {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
      </div>
    </label>
  );
}
