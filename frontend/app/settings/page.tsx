"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Cloud,
  Globe2,
  KeyRound,
  Loader2,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
} from "lucide-react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import Select from "@/components/Select";
import ThemeToggle from "@/components/ThemeToggle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { LoadingState } from "@/components/ui/state-view";
import { Switch } from "@/components/ui/switch";
import { getToken } from "@/lib/auth";
import { cn } from "@/lib/utils";
import {
  clearLLMSettings,
  getMySettings,
  probeLLM,
  saveKbOptions,
  saveLLMSettings,
  type LLMProvider,
  type MyKbOptions,
  type MyLLMSettings,
  type MySettings,
} from "@/lib/settings-api";
import { toast } from "@/lib/toast";

type ProbeState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; count: number }
  | { kind: "empty" }
  | { kind: "error"; message: string };

type ProviderPreset = {
  label: string;
  caption: string;
  provider: LLMProvider;
  baseUrl: string;
};

const PROVIDER_PRESETS: ProviderPreset[] = [
  { label: "DeepSeek", caption: "OpenAI Compatible", provider: "openai-compat", baseUrl: "https://api.deepseek.com" },
  { label: "OpenAI", caption: "官方 /v1 接口", provider: "openai-compat", baseUrl: "https://api.openai.com/v1" },
  { label: "Anthropic", caption: "Messages API", provider: "anthropic", baseUrl: "https://api.anthropic.com" },
];

/** User-level LLM configuration. KB retrieval options remain a separate region below. */
export default function SettingsPage() {
  const router = useRouter();
  const [settings, setSettings] = useState<MySettings | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    const next = await getMySettings();
    setSettings(next);
    return next;
  };

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    refresh()
      .catch((error) => toast.error(error instanceof Error ? error.message : "读取设置失败"))
      .finally(() => setLoading(false));
    // refresh is intentionally created per render; this boot request runs once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  if (loading) {
    return (
      <div className="flex min-h-dvh items-center justify-center px-4">
        <LoadingState
          label="正在读取模型设置"
          description="正在检查当前生效的模型与个人配置。"
          className="w-full max-w-md"
        />
      </div>
    );
  }

  return (
    <div className="app-page min-h-dvh text-ink">
      <header className="app-page-header border-b">
        <div className="mx-auto flex h-14 max-w-6xl items-center px-4 sm:px-6">
          <Link href="/" className="app-nav-link app-nav-link-compact">
            <ArrowLeft className="h-4 w-4" />
            返回对话
          </Link>
          <div className="ml-auto flex items-center gap-3">
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="app-page-content mx-auto max-w-6xl px-4 py-7 sm:px-6 sm:py-10">
        <header className="max-w-3xl">
          <p className="text-xs font-semibold tracking-[0.16em] text-brand">模型与运行策略</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-ink">模型设置</h1>
          <p className="mt-2 text-sm leading-6 text-muted">
            连接你的 LLM 服务，选择默认模型，并明确它在对话中的实际使用方式。
            知识库的 Embedding 与 Reranker 仍在创建知识库时按库配置。
          </p>
        </header>

        <div className="mt-8 space-y-10">
          <LLMSettingsPanel initial={settings?.llm} onChanged={refresh} />

          <section aria-labelledby="kb-preferences-heading" className="space-y-3">
            <div className="max-w-2xl">
              <p className="text-xs font-semibold tracking-[0.14em] text-muted">知识库</p>
              <h2 id="kb-preferences-heading" className="mt-1 text-lg font-semibold tracking-tight">
                检索偏好
              </h2>
              <p className="mt-1 text-sm leading-6 text-muted">
                此选项只影响绑定知识库的对话，与模型凭据和路由策略分开管理。
              </p>
            </div>
            <KbOptionsPanel initial={settings?.kb_options} onChanged={refresh} />
          </section>
        </div>
      </main>
    </div>
  );
}

function LLMSettingsPanel({
  initial,
  onChanged,
}: {
  initial?: MyLLMSettings;
  onChanged: () => Promise<MySettings>;
}) {
  const modelListId = useId();
  const [provider, setProvider] = useState<LLMProvider>((initial?.provider as LLMProvider) || "openai-compat");
  const [baseUrl, setBaseUrl] = useState(initial?.base_url || "");
  const [apiKey, setApiKey] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [defaultModel, setDefaultModel] = useState(initial?.default_model || "");
  const [complexModel, setComplexModel] = useState(initial?.complex_model || "");
  const [useComplexModel, setUseComplexModel] = useState(
    Boolean(initial?.complex_model && initial.complex_model !== initial.default_model)
  );
  const [contextWindow, setContextWindow] = useState<number | null>(initial?.context_window ?? null);
  const [probeState, setProbeState] = useState<ProbeState>({ kind: "idle" });
  const [saving, setSaving] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [clearing, setClearing] = useState(false);

  const hasSavedKey = initial?.has_key ?? false;
  const effectiveSource = initial?.effective_source ?? (initial?.configured ? "user" : "missing");
  const effectiveModel =
    effectiveSource === "user" ? initial?.default_model : initial?.effective_model;
  const contextWindowLabel = formatContextSummary(
    initial?.effective_context_window,
    initial?.effective_context_window_source
  );
  const savedModelChanged = defaultModel.trim() !== (initial?.default_model || "");
  const automaticContextLabel = savedModelChanged
    ? "保存后自动识别"
    : formatContextSummary(initial?.context_window_resolved, initial?.context_window_source);
  const canProbe = Boolean(baseUrl.trim() && (apiKey.trim() || hasSavedKey) && probeState.kind !== "loading");
  const canSave =
    Boolean(defaultModel.trim()) &&
    (!useComplexModel || Boolean(complexModel.trim())) &&
    (contextWindow === null ||
      (Number.isInteger(contextWindow) && contextWindow >= 4_096 && contextWindow <= 2_000_000)) &&
    Boolean(baseUrl.trim()) &&
    Boolean(apiKey.trim() || hasSavedKey) &&
    !saving;

  const modelOptions = useMemo(() => {
    const merged = new Set(models);
    if (defaultModel.trim()) merged.add(defaultModel.trim());
    if (useComplexModel && complexModel.trim()) merged.add(complexModel.trim());
    return [...merged].sort();
  }, [complexModel, defaultModel, models, useComplexModel]);

  useEffect(() => {
    setProvider((initial?.provider as LLMProvider) || "openai-compat");
    setBaseUrl(initial?.base_url || "");
    setApiKey("");
    setDefaultModel(initial?.default_model || "");
    setComplexModel(initial?.complex_model || "");
    setUseComplexModel(Boolean(initial?.complex_model && initial.complex_model !== initial.default_model));
    setContextWindow(initial?.context_window ?? null);
    setModels([]);
    setProbeState({ kind: "idle" });
  }, [
    initial?.base_url,
    initial?.complex_model,
    initial?.context_window,
    initial?.default_model,
    initial?.provider,
  ]);

  const providerHelp =
    provider === "anthropic"
      ? "使用 Anthropic 的 Messages API。"
      : "兼容 OpenAI API 的服务，如 DeepSeek、OpenAI、vLLM 或 LM Studio。";

  const handleProbe = async () => {
    if (!canProbe) return;
    setProbeState({ kind: "loading" });
    try {
      const result = await probeLLM({
        provider,
        base_url: baseUrl.trim(),
        api_key: apiKey.trim(),
      });
      setModels(result.models);
      setProbeState(result.models.length ? { kind: "success", count: result.models.length } : { kind: "empty" });
    } catch (error) {
      setModels([]);
      setProbeState({
        kind: "error",
        message: error instanceof Error ? error.message : "无法测试连接，请检查配置后重试。",
      });
    }
  };

  const handleSave = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      await saveLLMSettings({
        provider,
        base_url: baseUrl.trim(),
        api_key: apiKey,
        default_model: defaultModel.trim(),
        complex_model: useComplexModel ? complexModel.trim() : "",
        context_window: contextWindow,
      });
      toast.success("模型设置已保存并应用到后续对话");
      await onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存模型设置失败");
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    setClearing(true);
    try {
      await clearLLMSettings();
      toast.success("个人模型配置已清除");
      setClearOpen(false);
      await onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "清除模型配置失败");
    } finally {
      setClearing(false);
    }
  };

  const applyPreset = (preset: ProviderPreset) => {
    setProvider(preset.provider);
    setBaseUrl(preset.baseUrl);
    setModels([]);
    setProbeState({ kind: "idle" });
  };

  return (
    <section className="admin-panel overflow-hidden" aria-labelledby="llm-settings-heading">
      <div className="border-b border-surface-border/70 px-5 py-5 sm:px-6">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <span className="admin-icon-tile admin-icon-tile-brand" aria-hidden>
              <Bot className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <p className="text-xs font-semibold tracking-[0.14em] text-muted">当前运行配置</p>
              <h2 id="llm-settings-heading" className="mt-1 text-lg font-semibold tracking-tight">
                你的对话正在使用什么模型
              </h2>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-muted">
                {effectiveSource === "user"
                  ? "个人配置会作为未指定模型会话的默认值。"
                  : effectiveSource === "system"
                    ? "当前使用平台默认配置。保存个人配置后会优先使用你的服务。"
                    : "当前没有可用的模型配置。完成下方设置后即可开始对话。"}
              </p>
            </div>
          </div>
          <EffectiveStatus source={effectiveSource} />
        </div>

        <dl className="mt-6 grid divide-y divide-surface-border/70 border-y border-surface-border/70 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          <SummaryItem label="来源" value={sourceLabel(effectiveSource)} />
          <SummaryItem label="默认模型" value={effectiveModel || "尚未设置"} mono />
          <SummaryItem label="上下文窗口" value={contextWindowLabel} />
        </dl>
      </div>

      <div className="px-5 py-6 sm:px-6">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold tracking-[0.14em] text-brand">连接服务</p>
          <h3 className="mt-1 text-base font-semibold">选择提供商并验证连接</h3>
          <p className="mt-1 text-sm leading-6 text-muted">
            先测试连接，再从返回的模型中选择。兼容接口未返回模型列表时，也可以手动填写模型 ID。
          </p>
        </div>

        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          <Field label="提供商" htmlFor="llm-provider" description={providerHelp}>
            <Select
              id="llm-provider"
              value={provider}
              onChange={(event) => {
                setProvider(event.target.value as LLMProvider);
                setModels([]);
                setProbeState({ kind: "idle" });
              }}
              options={[
                { value: "anthropic", label: "Anthropic" },
                { value: "openai-compat", label: "OpenAI Compatible" },
              ]}
            />
          </Field>

          <Field label="快速填充" description="选择官方预设后，仍可改为你的代理或自托管地址。">
            <div className="grid gap-2 sm:grid-cols-3" role="group" aria-label="选择服务商预设">
              {PROVIDER_PRESETS.map((preset) => {
                const selected = provider === preset.provider && baseUrl === preset.baseUrl;
                return (
                  <button
                    key={preset.label}
                    type="button"
                    onClick={() => applyPreset(preset)}
                    aria-pressed={selected}
                    className={cn(
                      "group flex min-h-[68px] items-center gap-2.5 rounded-lg border px-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30",
                      selected
                        ? "border-brand/45 bg-brand/10 text-ink shadow-sm"
                        : "border-surface-border/80 bg-surface hover:border-brand/35 hover:bg-surface-2"
                    )}
                  >
                    <span
                      className={cn(
                        "flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold transition-colors",
                        selected
                          ? "border-brand/30 bg-brand/15 text-brand"
                          : "border-surface-border bg-surface-2 text-muted group-hover:border-brand/25 group-hover:text-brand"
                      )}
                      aria-hidden
                    >
                      {selected ? <Check className="size-3.5" /> : preset.label.slice(0, 1)}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-medium leading-5">{preset.label}</span>
                      <span className="block truncate text-[11px] leading-4 text-muted">{preset.caption}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </Field>

          <Field
            label="Base URL"
            htmlFor="llm-base-url"
            description="填写 API 根地址，不确定时使用服务商文档中的 API 地址。"
          >
            <input
              id="llm-base-url"
              type="url"
              name="llm-base-url"
              autoComplete="off"
              inputMode="url"
              value={baseUrl}
              onChange={(event) => {
                setBaseUrl(event.target.value);
                setProbeState({ kind: "idle" });
              }}
              placeholder={provider === "anthropic" ? "https://api.anthropic.com" : "https://api.example.com/v1"}
              className="admin-input"
            />
          </Field>

          <Field
            label="API Key"
            htmlFor="llm-api-key"
            description={hasSavedKey ? "已安全保存。留空会保留现有 Key，并可直接重新测试。" : "Key 仅用于当前连接与加密保存，不会在此页回显。"}
          >
            <div className="flex flex-col gap-2 sm:flex-row">
              <div className="relative min-w-0 flex-1">
                <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
                <input
                  id="llm-api-key"
                  type="password"
                  name="llm-api-key"
                  autoComplete="new-password"
                  data-lpignore="true"
                  data-1p-ignore="true"
                  value={apiKey}
                  onChange={(event) => {
                    setApiKey(event.target.value);
                    setProbeState({ kind: "idle" });
                  }}
                  placeholder={hasSavedKey ? "已保存，留空保持不变" : provider === "anthropic" ? "sk-ant-..." : "sk-..."}
                  className={cn("admin-input pl-9", probeState.kind === "error" && "border-danger focus:border-danger focus:ring-danger/20")}
                />
              </div>
              <Button type="button" variant="outline" onClick={handleProbe} disabled={!canProbe} className="w-full sm:w-auto">
                {probeState.kind === "loading" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Cloud className="h-4 w-4" />}
                {probeState.kind === "loading" ? "正在测试" : "测试连接"}
              </Button>
            </div>
          </Field>
        </div>

        <ProbeFeedback state={probeState} />
      </div>

      <div className="border-t border-surface-border/70 px-5 py-6 sm:px-6">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold tracking-[0.14em] text-brand">模型策略</p>
          <h3 className="mt-1 text-base font-semibold">设定默认使用方式</h3>
          <p className="mt-1 text-sm leading-6 text-muted">
            默认模型用于没有会话级选择的对话。已在聊天框中单独选择的模型不会被这里的保存操作覆盖。
          </p>
        </div>

        <div className="mt-5 max-w-2xl">
          <Field
            label="默认模型"
            htmlFor="llm-default-model"
            description={modelOptions.length ? "可从测试结果选择，也可填写服务商要求的精确模型 ID。" : "可直接填写模型 ID；测试连接后会自动提供可选模型。"}
          >
            <input
              id="llm-default-model"
              name="llm-default-model"
              value={defaultModel}
              onChange={(event) => setDefaultModel(event.target.value)}
              list={modelListId}
              placeholder="例如 deepseek-chat"
              className="admin-input font-mono"
              autoComplete="off"
            />
          </Field>
          <datalist id={modelListId}>
            {modelOptions.map((model) => <option key={model} value={model} />)}
          </datalist>
        </div>

        <details className="group mt-6 border-t border-surface-border/70 pt-5">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-sm font-medium text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30">
            <span className="flex items-center gap-2">
              <SlidersHorizontal className="h-4 w-4 text-muted" aria-hidden />
              高级模型策略
            </span>
            <ChevronDown className="h-4 w-4 text-muted transition-transform duration-200 group-open:rotate-180" aria-hidden />
          </summary>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
            主流模型会由服务端能力库自动识别上下文窗口。只有自托管、别名或需要特殊限制的模型才需要手动覆盖。
          </p>

          <div className="mt-5 max-w-2xl divide-y divide-surface-border/70 border-y border-surface-border/70">
            <div className="py-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium text-ink">复杂任务模型</p>
                    <Badge variant="outline" className={useComplexModel ? "border-brand/25 bg-brand/10 text-brand" : "border-surface-border bg-surface-2 text-muted"}>
                      {useComplexModel ? "已单独指定" : "跟随默认模型"}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-muted">
                    工具数超过 5 个或用户输入超过 2,000 个字符时使用。只在需要时单独指定，避免维护两套常规模型配置。
                  </p>
                </div>
                <Switch
                  checked={useComplexModel}
                  onCheckedChange={setUseComplexModel}
                  aria-label="为复杂任务单独指定模型"
                  className="shrink-0"
                />
              </div>

              {useComplexModel && (
                <div className="mt-4 max-w-xl">
                  <Field
                    label="复杂任务模型 ID"
                    htmlFor="llm-complex-model"
                    description="保存后仅在复杂任务场景优先使用此模型。"
                  >
                    <input
                      id="llm-complex-model"
                      name="llm-complex-model"
                      value={complexModel}
                      onChange={(event) => setComplexModel(event.target.value)}
                      list={modelListId}
                      placeholder="例如 deepseek-reasoner"
                      className="admin-input font-mono"
                      autoComplete="off"
                    />
                  </Field>
                </div>
              )}
            </div>

            <div className="py-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium text-ink">上下文窗口</p>
                    <Badge
                      variant="outline"
                      className={cn(
                        contextWindow === null
                          ? "border-brand/25 bg-brand/10 text-brand"
                          : "border-warning/30 bg-warning/10 text-warning"
                      )}
                    >
                      {contextWindow === null ? "自动识别" : "手动覆盖"}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-muted">
                    {contextWindow === null
                      ? `${automaticContextLabel}。它决定历史保留、摘要触发与输出预算。`
                      : "手动值优先于模型能力库，适合服务商别名或自托管模型。"}
                  </p>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setContextWindow(contextWindow === null ? initial?.context_window_resolved ?? 16_000 : null)}
                >
                  {contextWindow === null ? "手动覆盖" : "恢复自动识别"}
                </Button>
              </div>

              {contextWindow !== null && (
                <div className="mt-4 max-w-sm">
                  <Field
                    label="覆盖值（tokens）"
                    htmlFor="llm-context-window"
                    description="范围 4,096 到 2,000,000。恢复自动识别会移除此覆盖值。"
                  >
                    <input
                      id="llm-context-window"
                      type="number"
                      min={4096}
                      max={2000000}
                      step={1024}
                      value={contextWindow}
                      onChange={(event) => setContextWindow(Number(event.target.value))}
                      className="admin-input font-mono"
                      aria-invalid={!Number.isInteger(contextWindow) || contextWindow < 4096 || contextWindow > 2000000}
                    />
                  </Field>
                </div>
              )}
            </div>
          </div>
        </details>
      </div>

      <footer className="flex flex-col gap-4 border-t border-surface-border/70 bg-surface-2/35 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div className="min-w-0 text-sm text-muted" aria-live="polite">
          {canSave
            ? "保存后会应用到后续未指定模型的对话。"
            : useComplexModel && !complexModel.trim()
              ? "已启用复杂任务模型，请填写对应的模型 ID。"
              : "请补全 Base URL、API Key、默认模型；手动覆盖时还需填写有效窗口。"}
        </div>
        <div className="flex w-full flex-col-reverse gap-2 sm:w-auto sm:flex-row">
          {initial?.configured && (
            <Button type="button" variant="destructive" onClick={() => setClearOpen(true)} disabled={saving}>
              <Trash2 className="h-4 w-4" />
              清除个人配置
            </Button>
          )}
          <Button type="button" onClick={handleSave} disabled={!canSave}>
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            {saving ? "正在保存" : "保存并应用"}
          </Button>
        </div>
      </footer>

      <ConfirmDialog
        open={clearOpen}
        onOpenChange={setClearOpen}
        title="清除个人模型配置？"
        description="清除后会回到平台默认模型；如果部署启用了 BYOK，你将无法继续对话，直到重新配置。"
        confirmLabel="清除个人配置"
        variant="danger"
        busy={clearing}
        onConfirm={handleClear}
      />
    </section>
  );
}

function KbOptionsPanel({
  initial,
  onChanged,
}: {
  initial?: MyKbOptions;
  onChanged: () => Promise<MySettings>;
}) {
  const [webEnabled, setWebEnabled] = useState(initial?.kb_web_search_enabled ?? false);
  const [saving, setSaving] = useState(false);
  const dirty = webEnabled !== (initial?.kb_web_search_enabled ?? false);

  useEffect(() => setWebEnabled(initial?.kb_web_search_enabled ?? false), [initial?.kb_web_search_enabled]);

  const onSave = async () => {
    setSaving(true);
    try {
      await saveKbOptions({ kb_web_search_enabled: webEnabled });
      await onChanged();
      toast.success("知识库检索偏好已保存");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存知识库偏好失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="admin-panel">
      <div className="flex flex-col gap-5 px-5 py-5 sm:flex-row sm:items-start sm:justify-between sm:px-6">
        <div className="flex min-w-0 items-start gap-3">
          <span className="admin-icon-tile admin-icon-tile-muted" aria-hidden>
            <Globe2 className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <h3 className="text-base font-semibold">知识库回答不足时允许网络检索</h3>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-muted">
              开启后，Agent 会优先检索你的文档；仅在没有相关分块时最多补充一次网络搜索，并在回答中区分来源。默认关闭以保持回答严格基于知识库。
            </p>
          </div>
        </div>
        <Switch
          checked={webEnabled}
          onCheckedChange={setWebEnabled}
          disabled={saving}
          aria-label="允许知识库对话调用网络搜索作为兜底"
          className="shrink-0"
        />
      </div>
      <footer className="flex flex-col gap-3 border-t border-surface-border/70 bg-surface-2/35 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <span className="text-sm text-muted">{dirty ? "偏好已变更，保存后影响后续知识库对话。" : "当前偏好已保存。"}</span>
        <Button type="button" variant="outline" onClick={onSave} disabled={saving || !dirty}>
          {saving && <Loader2 className="h-4 w-4 animate-spin" />}
          {saving ? "正在保存" : "保存检索偏好"}
        </Button>
      </footer>
    </section>
  );
}

function EffectiveStatus({ source }: { source: "user" | "system" | "missing" }) {
  if (source === "user") {
    return (
      <Badge variant="outline" className="border-success/30 bg-success/10 text-success">
        <CheckCircle2 className="h-3.5 w-3.5" />
        个人配置生效
      </Badge>
    );
  }
  if (source === "system") {
    return (
      <Badge variant="outline" className="border-info/25 bg-info/10 text-info">
        <ShieldCheck className="h-3.5 w-3.5" />
        正在使用系统默认
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="border-warning/30 bg-warning/10 text-warning">
      <CircleAlert className="h-3.5 w-3.5" />
      需要配置模型
    </Badge>
  );
}

function SummaryItem({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0 px-0 py-3 first:pt-0 last:pb-0 sm:px-4 sm:py-0 sm:first:pl-0 sm:last:pr-0">
      <dt className="text-xs font-medium text-muted">{label}</dt>
      <dd className={cn("mt-1 truncate text-sm font-medium text-ink", mono && "font-mono text-[13px]")} title={value}>
        {value}
      </dd>
    </div>
  );
}

function ProbeFeedback({ state }: { state: ProbeState }) {
  if (state.kind === "idle") return null;
  if (state.kind === "loading") {
    return <p className="mt-4 flex items-center gap-2 text-sm text-muted" role="status"><Loader2 className="h-4 w-4 animate-spin" />正在验证服务与模型列表…</p>;
  }
  if (state.kind === "success") {
    return <InlineNotice icon={<CheckCircle2 className="h-4 w-4" />} tone="success">连接成功，发现 {state.count} 个模型。你可以从下方输入框选择或填写模型 ID。</InlineNotice>;
  }
  if (state.kind === "empty") {
    return <InlineNotice icon={<CircleAlert className="h-4 w-4" />} tone="warning">服务可以连接，但没有返回模型列表。请根据服务商文档手动填写模型 ID。</InlineNotice>;
  }
  return <InlineNotice icon={<CircleAlert className="h-4 w-4" />} tone="danger" role="alert">测试未通过：{state.message}</InlineNotice>;
}

function InlineNotice({
  children,
  icon,
  tone,
  role,
}: {
  children: ReactNode;
  icon: ReactNode;
  tone: "success" | "warning" | "danger";
  role?: "alert";
}) {
  const toneClass = {
    success: "border-success/25 bg-success/10 text-success",
    warning: "border-warning/25 bg-warning/10 text-warning",
    danger: "border-danger/25 bg-danger/10 text-danger",
  }[tone];
  return <p role={role} className={cn("mt-4 flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm leading-5", toneClass)}>{icon}<span>{children}</span></p>;
}

function Field({
  label,
  description,
  children,
  htmlFor,
}: {
  label: string;
  description: string;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="min-w-0">
      {htmlFor ? (
        <label htmlFor={htmlFor} className="mb-1.5 block text-sm font-medium text-ink">{label}</label>
      ) : (
        <div className="mb-1.5 text-sm font-medium text-ink">{label}</div>
      )}
      {children}
      <p className="mt-1.5 text-xs leading-5 text-muted">{description}</p>
    </div>
  );
}

function sourceLabel(source: "user" | "system" | "missing") {
  return source === "user" ? "个人配置" : source === "system" ? "系统默认" : "未配置";
}

function formatContextSummary(
  value: number | null | undefined,
  source: "manual" | "registry" | "fallback" | null | undefined
) {
  if (!value) return "待模型识别";
  const label = value >= 1000 ? `${value / 1000}K` : String(value);
  if (source === "manual") return `${label} · 手动覆盖`;
  if (source === "registry") return `${label} · 自动识别`;
  return `${label} · 保守兜底`;
}
