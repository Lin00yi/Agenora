"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Bot, Globe2, KeyRound, Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";

import Select from "@/components/Select";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { getToken } from "@/lib/auth";
import {
  clearLLMSettings,
  getMySettings,
  probeLLM,
  saveKbOptions,
  saveLLMSettings,
  SettingsApiError,
  type LLMProvider,
  type MyKbOptions,
  type MyLLMSettings,
  type MySettings,
} from "@/lib/settings-api";
import { LoadingState, StateView } from "@/components/ui/state-view";
import ThemeToggle from "@/components/ThemeToggle";
import { Switch } from "@/components/ui/switch";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * /settings - LLM provider credentials (v3-M8 simplified).
 *
 * Embedding + Reranker config has been removed from this page (v3-M8) - both
 * are now configured per-KB at creation time. This page exists solely to:
 *   - Save LLM provider creds (provider + base_url + api_key + default_model)
 *   - Toggle KB-mode options (e.g. web_search opt-in)
 *
 * Long-term memory management lives at /memories.
 * The default LLM model saved here is the fallback for any conversation that
 * hasn't explicitly picked a model via the chat header Model selector (v3-M6).
 */
export default function SettingsPage() {
  const router = useRouter();
  const [settings, setSettings] = useState<MySettings | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    const s = await getMySettings();
    setSettings(s);
    return s;
  };

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    refresh()
      .catch((e) => toast.error((e as Error).message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  if (loading) {
    return (
      <div className="flex min-h-dvh items-center justify-center px-4">
        <LoadingState label="正在读取模型设置" description="正在检查已保存的模型和知识库偏好。" className="w-full max-w-md" />
      </div>
    );
  }

  return (
    <div className="app-page min-h-dvh text-ink">
      <header className="app-page-header border-b">
        <div className="mx-auto flex h-14 max-w-6xl items-center px-4 sm:px-6">
          <Link
            href="/"
            className="app-nav-link app-nav-link-compact"
          >
            <ArrowLeft className="h-4 w-4" />
            返回对话
          </Link>
          <div className="ml-auto flex items-center gap-3">
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main className="app-page-content mx-auto max-w-6xl px-4 py-7 sm:px-6 sm:py-10">
        <section className="admin-panel overflow-hidden">
          <div className="border-b border-surface-border/70 bg-surface-2/45 px-5 py-5 sm:px-6">
            <p className="text-xs font-semibold tracking-[0.16em] text-brand">模型设置</p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight">模型设置</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
              配置 LLM 提供商凭据与知识库兜底策略。Embedding / Reranker 在创建知识库时按 KB 单独配置。
              长期记忆请前往{" "}
              <Link href="/memories" className="text-brand underline-offset-2 hover:underline">
                记忆系统
              </Link>
              。
            </p>
          </div>
        </section>

        <div className="mt-8 space-y-6">
          <LLMCard
            initial={settings?.llm}
            onChanged={refresh}
          />
          <KbOptionsCard
            initial={settings?.kb_options}
            onChanged={refresh}
          />
        </div>
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// LLM card
// ---------------------------------------------------------------------------
function LLMCard({
  initial,
  onChanged,
}: {
  initial?: MyLLMSettings;
  onChanged: () => Promise<MySettings>;
}) {
  const [provider, setProvider] = useState<LLMProvider>(
    (initial?.provider as LLMProvider) || "openai-compat"
  );
  const [baseUrl, setBaseUrl] = useState(initial?.base_url || "");
  const [apiKey, setApiKey] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [defaultModel, setDefaultModel] = useState(initial?.default_model || "");
  const [complexModel, setComplexModel] = useState(initial?.complex_model || "");
  const [contextWindow, setContextWindow] = useState(initial?.context_window ?? 16000);
  const [probing, setProbing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const hasSavedKey = initial?.has_key ?? false;

  const placeholders = useMemo(() => {
    if (provider === "anthropic")
      return { url: "https://api.anthropic.com", key: "sk-ant-..." };
    return { url: "https://api.deepseek.com   或 OpenAI / vLLM / LMStudio", key: "sk-..." };
  }, [provider]);

  const canProbe = baseUrl.trim() && apiKey.trim() && !probing;
  const canSave =
    !!defaultModel &&
    Number.isInteger(contextWindow) &&
    contextWindow >= 4096 &&
    contextWindow <= 2_000_000 &&
    (apiKey.trim() || hasSavedKey) &&
    !!baseUrl.trim() &&
    !saving;

  async function handleProbe() {
    if (!canProbe) return;
    setProbing(true);
    try {
      const r = await probeLLM({
        provider,
        base_url: baseUrl.trim(),
        api_key: apiKey.trim(),
      });
      setModels(r.models);
      if (r.models.length === 0) {
        toast.warning("已连接，但服务端没返回任何模型");
      } else {
        toast.success(`发现 ${r.models.length} 个模型`);
      }
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setProbing(false);
    }
  }

  async function handleSave() {
    if (!canSave) return;
    setSaving(true);
    try {
      await saveLLMSettings({
        provider,
        base_url: baseUrl.trim(),
        api_key: apiKey,
        default_model: defaultModel,
        complex_model: complexModel,
        context_window: contextWindow,
      });
      toast.success("LLM 配置已保存");
      setApiKey("");
      await onChanged();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function handleClear() {
    setClearing(true);
    try {
      await clearLLMSettings();
      toast.success("已清除");
      setApiKey("");
      setModels([]);
      setDefaultModel("");
      setComplexModel("");
      setContextWindow(16000);
      await onChanged();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setClearing(false);
    }
  }

  // Pre-fill model options with the saved model so the user can submit
  // without re-probing (e.g. they just want to update the URL).
  const modelOptions = useMemo(() => {
    const merged = new Set(models);
    if (defaultModel) merged.add(defaultModel);
    if (complexModel) merged.add(complexModel);
    return Array.from(merged)
      .sort()
      .map((m) => ({ value: m, label: m }));
  }, [models, defaultModel, complexModel]);

  return (
    <section className="admin-panel overflow-hidden">
      <header className="flex flex-col gap-3 border-b border-surface-border/70 bg-surface-2/35 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <span className="admin-icon-tile admin-icon-tile-brand">
            <Bot className="h-4 w-4" />
          </span>
          <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            LLM 提供商
          </h2>
          <p className="mt-1 text-xs text-muted">
            {initial?.configured
              ? `当前：${initial.provider} · ${initial.default_model}`
              : "未配置，使用系统默认"}
          </p>
          </div>
        </div>
        {initial?.configured && (
          <Button
            onClick={() => setClearOpen(true)}
            variant="outline"
            className="w-full shrink-0 sm:w-auto"
            type="button"
          >
            <Trash2 className="h-4 w-4" />
            清除
          </Button>
        )}
      </header>

      <div className="grid gap-5 px-5 py-5 text-sm lg:grid-cols-2">
        <Field label="Provider">
          <Select
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value as LLMProvider);
              setModels([]);
            }}
            options={[
              { value: "anthropic", label: "anthropic（Claude）" },
              { value: "openai-compat", label: "openai-compat（OpenAI / DeepSeek / vLLM / 任意）" },
            ]}
          />
        </Field>

        <Field label="Base URL">
          <input
            type="url"
            name="llm-base-url"
            autoComplete="off"
            inputMode="url"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={placeholders.url}
            className={inputClass}
          />
        </Field>

        <Field label="API Key">
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
            <div className="relative min-w-0 flex-1">
              <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
              <input
                type="password"
                name="llm-api-key"
                autoComplete="new-password"
                data-lpignore="true"
                data-1p-ignore="true"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={
                  hasSavedKey ? "已保存（留空保持现有）" : placeholders.key
                }
                className={cn(inputClass, "pl-9")}
              />
            </div>
            <Button
              onClick={handleProbe}
              disabled={!canProbe}
              variant="outline"
              className="h-[var(--control-h)] w-full shrink-0 sm:w-auto"
              type="button"
            >
              {probing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                "测试连接"
              )}
            </Button>
          </div>
        </Field>

        <Field label="Default Model">
          <Select
            value={defaultModel}
            onChange={(e) => setDefaultModel(e.target.value)}
            options={modelOptions}
            disabled={modelOptions.length === 0}
            placeholderOption={
              modelOptions.length === 0
                ? { value: "", label: "请先点击测试连接" }
                : { value: "", label: "请选择" }
            }
            className="min-w-0 sm:min-w-[16rem]"
          />
        </Field>

        <Field label="Complex Model（可选，用于复杂任务）">
          <Select
            value={complexModel}
            onChange={(e) => setComplexModel(e.target.value)}
            options={modelOptions}
            disabled={modelOptions.length === 0}
            placeholderOption={{ value: "", label: "与 Default 相同" }}
            className="min-w-0 sm:min-w-[16rem]"
          />
        </Field>

        <Field label="Context Window（tokens）">
          <input
            type="number"
            min={4096}
            max={2000000}
            step={1024}
            value={contextWindow}
            onChange={(e) => setContextWindow(Number(e.target.value))}
            className={inputClass}
          />
          <p className="mt-1 text-xs text-muted">
            填写该模型的最大上下文窗口；不确定时请使用提供商文档中的输入窗口值。
          </p>
        </Field>
      </div>

      <div className="flex flex-col gap-3 border-t border-surface-border/70 bg-surface-2/35 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <span className="min-w-0 flex-1 text-xs text-muted">
          {canSave ? "配置校验通过，可以保存" : "补全 Base URL、API Key、模型和上下文窗口后保存"}
        </span>
        <Button
          type="button"
          className={primaryActionClass}
          onClick={handleSave}
          disabled={!canSave}
        >
          {saving ? "保存中..." : "保存 LLM 配置"}
        </Button>
      </div>
      <ConfirmDialog
        open={clearOpen}
        onOpenChange={setClearOpen}
        title="清除 LLM 配置？"
        description="清除后会回落到系统默认配置。"
        confirmLabel="清除"
        variant="danger"
        busy={clearing}
        onConfirm={async () => {
          await handleClear();
          setClearOpen(false);
        }}
      />
    </section>
  );
}

// ---------------------------------------------------------------------------
// KbOptions card (v2-M6) - KB-mode toggles
// ---------------------------------------------------------------------------
function KbOptionsCard({
  initial,
  onChanged,
}: {
  initial?: MyKbOptions;
  onChanged: () => Promise<MySettings>;
}) {
  const [webEnabled, setWebEnabled] = useState<boolean>(
    initial?.kb_web_search_enabled ?? false
  );
  const [saving, setSaving] = useState(false);

  // Sync from server state if parent refetches.
  useEffect(() => {
    setWebEnabled(initial?.kb_web_search_enabled ?? false);
  }, [initial?.kb_web_search_enabled]);

  const dirty = webEnabled !== (initial?.kb_web_search_enabled ?? false);

  const onSave = async () => {
    setSaving(true);
    try {
      await saveKbOptions({ kb_web_search_enabled: webEnabled });
      await onChanged();
      toast.success("已保存");
    } catch (e) {
      toast.error((e as Error).message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="admin-panel overflow-hidden">
      <header className="flex items-start gap-3 border-b border-surface-border/70 bg-surface-2/35 px-5 py-4">
        <span className="admin-icon-tile admin-icon-tile-brand">
          <Globe2 className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <h2 className="text-base font-semibold">KB 模式选项</h2>
          <p className="mt-1 text-xs text-muted">控制知识库回答不足时是否允许网络检索兜底。</p>
        </div>
      </header>

      <div className="px-5 py-5">
      <div className="flex items-start gap-4 rounded-lg border border-surface-border/80 bg-surface p-4 shadow-sm transition-[background-color,border-color,box-shadow] hover:border-brand/30 hover:bg-surface-2/60 hover:shadow-md">
        <Switch
          checked={webEnabled}
          onCheckedChange={setWebEnabled}
          disabled={saving}
          aria-label="允许 KB 对话调用网络搜索作为兜底"
          className="mt-1"
        />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">KB 对话允许调用网络搜索作为兜底</div>
          <p className="mt-1 text-xs text-muted leading-relaxed">
            开启后，绑定 KB 的对话里 agent 仍然优先 <code className="rounded bg-surface px-1">search_kb</code>{" "}
            检索你的文档；只在 KB 没有相关分块（相关度 &lt; 0.4）时最多调一次{" "}
            <code className="rounded bg-surface px-1">web_search</code> 兜底补充。
            答案会按【KB】【Web】分段标注来源。默认关闭以保持答案严格基于知识库。
          </p>
        </div>
      </div>
      </div>

      <div className="flex flex-col gap-3 border-t border-surface-border/70 bg-surface-2/35 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <span className="min-w-0 flex-1 text-xs text-muted">
          {dirty ? "选项已变更，保存后会影响后续 KB 对话" : "当前选项与服务器配置一致"}
        </span>
        <Button
          type="button"
          onClick={onSave}
          disabled={saving || !dirty}
          className={primaryActionClass}
        >
          {saving ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              保存中...
            </>
          ) : (
            "保存 KB 选项"
          )}
        </Button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block min-w-0">
      <div className="mb-1.5 text-xs font-medium text-muted">{label}</div>
      {children}
    </label>
  );
}

const inputClass =
  "admin-input";

const primaryActionClass = cn(
  buttonVariants({ variant: "default" }),
  "w-full shrink-0 sm:w-auto"
);

const secondaryActionClass = cn(
  buttonVariants({ variant: "outline" }),
  "w-full shrink-0 sm:w-auto"
);
