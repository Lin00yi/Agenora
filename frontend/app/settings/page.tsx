"use client";

import {
  ArrowLeft,
  Bot,
  CheckCircle2,
  CircleAlert,
  Cloud,
  KeyRound,
  Loader2,
  Plus,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import Select from "@/components/Select";
import ThemeToggle from "@/components/ThemeToggle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { LoadingState } from "@/components/ui/state-view";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getToken } from "@/lib/auth";
import {
  clearLLMSettings,
  createLLMConnection,
  createLLMModelProfile,
  deleteLLMConnection,
  deleteLLMModelProfile,
  getMySettings,
  probeLLM,
  probeLLMConnection,
  saveLLMModelPolicy,
  saveLLMSettings,
  type LLMConnection,
  type LLMModelProfile,
  type LLMProvider,
  type MyLLMSettings,
  type MySettings,
} from "@/lib/settings-api";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";

type ProbeState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; count: number }
  | { kind: "empty" }
  | { kind: "error"; message: string };

type ServicePreset = {
  provider: LLMProvider;
  baseUrl: string;
};

const SERVICE_PRESETS = {
  anthropic: { provider: "anthropic", baseUrl: "https://api.anthropic.com" },
  openai: { provider: "openai-compat", baseUrl: "https://api.openai.com/v1" },
  deepseek: { provider: "openai-compat", baseUrl: "https://api.deepseek.com" },
} satisfies Record<string, ServicePreset>;

function generatedConnectionName(provider: LLMProvider, baseUrl: string) {
  const endpoint = baseUrl.toLowerCase();
  if (endpoint.includes("deepseek")) return "DeepSeek";
  if (endpoint.includes("openai")) return "OpenAI";
  if (endpoint.includes("anthropic")) return "Anthropic";
  return provider === "anthropic" ? "Anthropic 服务" : "OpenAI 兼容服务";
}

function connectionLabel(connection?: LLMConnection) {
  if (!connection) return "已保存的服务连接";
  const generatedNames = new Set(["OpenAI 兼容连接", "Anthropic 连接", "默认连接"]);
  return generatedNames.has(connection.display_name)
    ? generatedConnectionName(connection.provider, connection.base_url)
    : connection.display_name;
}

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
            创建可复用的模型配置，再在路由策略中选择默认模型和自动执行方式。
            知识库的 Embedding 与 Reranker 仍在创建知识库时按库配置。
          </p>
        </header>

        <div className="mt-8">
          <LLMSettingsPanel initial={settings?.llm} onChanged={refresh} />
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
  const [provider, setProvider] = useState<LLMProvider>((initial?.provider as LLMProvider) || "openai-compat");
  const [baseUrl, setBaseUrl] = useState(initial?.base_url || "");
  const [apiKey, setApiKey] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [modelContextWindows, setModelContextWindows] = useState<Record<string, number>>({});
  const [defaultModel, setDefaultModel] = useState(initial?.default_model || "");
  const [contextWindow, setContextWindow] = useState<number | null>(initial?.context_window ?? null);
  const [probeState, setProbeState] = useState<ProbeState>({ kind: "idle" });
  const [saving, setSaving] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [activeSection, setActiveSection] = useState<"connections" | "models" | "routing">("connections");
  const [connectionEditor, setConnectionEditor] = useState<"create" | "edit" | null>(null);

  const hasSavedKey = initial?.has_key ?? false;
  const hasProfiles = Boolean(initial?.model_profiles?.length);
  const connectionCount = initial?.connections?.filter((connection) => !connection.is_legacy_default).length ?? 0;
  const isCreatingFirstProfile = connectionEditor === "create" && !hasProfiles;
  const effectiveSource = initial?.effective_source ?? (initial?.configured ? "user" : "missing");
  const canProbe = Boolean(baseUrl.trim() && (apiKey.trim() || hasSavedKey) && probeState.kind !== "loading");
  const canSave =
    Boolean((isCreatingFirstProfile && defaultModel.trim()) || (!isCreatingFirstProfile && initial?.configured)) &&
    (contextWindow === null ||
      (Number.isInteger(contextWindow) && contextWindow >= 4_096 && contextWindow <= 2_000_000)) &&
    Boolean(baseUrl.trim()) &&
    Boolean(apiKey.trim() || (!isCreatingFirstProfile && hasSavedKey)) &&
    !saving;
  const hasVerifiedModels = probeState.kind === "success" && models.length > 0;
  const detectedContextWindow =
    modelContextWindows[defaultModel] ??
    (contextWindow === null && initial?.context_window_source === "registry"
      ? initial.context_window_resolved ?? undefined
      : undefined);
  const contextWindowIsAutomatic = contextWindow === null && Boolean(detectedContextWindow);
  const contextWindowValue = contextWindowIsAutomatic ? detectedContextWindow : contextWindow ?? "";
  const contextWindowDescription = contextWindowIsAutomatic
    ? "已由模型能力库自动识别，保存后会用于历史保留、摘要触发与输出预算。"
    : "未识别的模型可填写实际窗口；范围 4,096 到 2,000,000。";

  useEffect(() => {
    setProvider((initial?.provider as LLMProvider) || "openai-compat");
    setBaseUrl(initial?.base_url || "");
    setApiKey("");
    setDefaultModel(initial?.default_model || "");
    setContextWindow(initial?.context_window ?? null);
    setModels([]);
    setModelContextWindows({});
    setProbeState({ kind: "idle" });
  }, [
    initial?.base_url,
    initial?.context_window,
    initial?.default_model,
    initial?.provider,
  ]);

  useEffect(() => {
    if (hasProfiles && connectionEditor === "create") {
      setConnectionEditor(null);
    }
  }, [connectionEditor, hasProfiles]);

  useEffect(() => {
    if (!hasProfiles && activeSection === "routing") setActiveSection("models");
  }, [activeSection, hasProfiles]);

  const providerHelp =
    provider === "anthropic"
      ? "使用 Anthropic 的 Messages API。"
      : "兼容 OpenAI API 的服务，如 DeepSeek、OpenAI、vLLM 或 LM Studio。";
  const serviceProtocolValue =
    provider === "anthropic"
      ? "anthropic"
      : baseUrl === SERVICE_PRESETS.openai.baseUrl
        ? "openai"
        : baseUrl === SERVICE_PRESETS.deepseek.baseUrl
          ? "deepseek"
          : "custom-compatible";

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
      setModelContextWindows(
        Object.fromEntries(
          Object.entries(result.context_windows ?? {}).map(([model, context]) => [model, context.value])
        )
      );
      if (result.models.length) {
        setDefaultModel((current) =>
          result.models.includes(current) ? current : result.models[0]
        );
      }
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
      if (isCreatingFirstProfile) {
        const connection = await createLLMConnection({
          display_name: generatedConnectionName(provider, baseUrl.trim()),
          provider,
          base_url: baseUrl.trim(),
          api_key: apiKey.trim(),
          enabled: true,
        });
        await createLLMModelProfile({
          connection_id: connection.id,
          display_name: defaultModel.trim(),
          model_id: defaultModel.trim(),
          context_window: contextWindow,
          enabled: true,
          supports_tools: true,
        });
        toast.success("模型配置已创建，请在路由策略中选择默认模型");
      } else {
        await saveLLMSettings({
          provider,
          base_url: baseUrl.trim(),
          api_key: apiKey,
          context_window: contextWindow,
        });
        toast.success("默认连接已保存");
      }
      await onChanged();
      setConnectionEditor(null);
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

  const applyPreset = (preset: ServicePreset) => {
    setProvider(preset.provider);
    setBaseUrl(preset.baseUrl);
    setModels([]);
    setModelContextWindows({});
    setProbeState({ kind: "idle" });
  };

  const applyCustomConnection = () => {
    setProvider("openai-compat");
    setBaseUrl("");
    setModels([]);
    setModelContextWindows({});
    setProbeState({ kind: "idle" });
  };

  const handleServiceProtocolChange = (value: string) => {
    if (value === "anthropic") return applyPreset(SERVICE_PRESETS.anthropic);
    if (value === "openai") return applyPreset(SERVICE_PRESETS.openai);
    if (value === "deepseek") return applyPreset(SERVICE_PRESETS.deepseek);
    applyCustomConnection();
  };

  return (
    <section className="admin-panel overflow-hidden" aria-labelledby="llm-settings-heading">
      <div className="border-b border-surface-border/70 px-5 py-5 sm:px-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <span className="admin-icon-tile admin-icon-tile-brand" aria-hidden><Bot className="h-4 w-4" /></span>
            <div className="min-w-0">
              <p className="text-xs font-semibold text-brand">模型设置</p>
              <h2 id="llm-settings-heading" className="mt-1 text-balance text-xl font-semibold">管理模型配置与路由策略</h2>
              <p className="mt-1 max-w-2xl text-pretty text-sm leading-6 text-muted">模型配置是可复用资产。默认模型和自动路由在单独的策略中维护。</p>
            </div>
          </div>
          <EffectiveStatus
            source={effectiveSource}
            hasProfiles={hasProfiles}
            hasDefaultProfile={Boolean(initial?.default_profile_id)}
          />
        </div>
        <Tabs value={activeSection} onValueChange={(value) => setActiveSection(value as "connections" | "models" | "routing")} className="mt-6">
          <TabsList variant="line" aria-label="模型设置区域" className="w-full justify-start gap-0 rounded-none border-b border-surface-border/70 p-0">
            <TabsTrigger value="connections" className="flex-none rounded-none px-3.5">服务连接{connectionCount ? ` (${connectionCount})` : ""}</TabsTrigger>
            <TabsTrigger value="models" className="flex-none rounded-none px-3.5">模型配置{hasProfiles ? ` (${initial?.model_profiles?.length ?? 0})` : ""}</TabsTrigger>
            <TabsTrigger value="routing" disabled={!hasProfiles} className="flex-none rounded-none px-3.5">{!hasProfiles && <span aria-hidden>🔒</span>}路由策略</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {activeSection === "models" && connectionEditor && (
      <div id="model-connections" className="scroll-mt-5 px-5 py-5 sm:px-6">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold text-brand">{isCreatingFirstProfile ? "创建模型配置" : "默认连接"}</p>
          <h3 className="mt-1 text-balance text-lg font-semibold">{isCreatingFirstProfile ? "填写第一个模型配置" : "维护默认连接"}</h3>
          <p className="mt-1 text-pretty text-sm leading-6 text-muted">
            {initial?.configured ? "其他服务商可在模型目录中按需添加，不会覆盖这里已保存的凭据。" : "先连接一个可用模型。保存后，系统会自动创建首个模型档案。"}
          </p>
        </div>

        <div className="mt-5 grid gap-x-4 gap-y-4 lg:grid-cols-2">
          <Field
            label="服务协议"
            htmlFor="llm-provider"
            description={providerHelp}
          >
            <Select
              id="llm-provider"
              value={serviceProtocolValue}
              onChange={(event) => handleServiceProtocolChange(event.target.value)}
              options={[
                { value: "anthropic", label: "Anthropic Messages" },
                { value: "openai", label: "OpenAI" },
              ]}
              submenus={[
                {
                  label: "OpenAI Compatible",
                  options: [
                    { value: "deepseek", label: "DeepSeek" },
                    { value: "custom-compatible", label: "自定义兼容地址" },
                  ],
                },
              ]}
            />
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
                setModels([]);
                setModelContextWindows({});
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
                    setModels([]);
                    setModelContextWindows({});
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

          {!initial?.configured && (
            <div>
              <Field
                label="初始模型 ID"
                htmlFor="llm-default-model"
                description={hasVerifiedModels ? "已从当前连接读取模型目录。选择后会建立第一个模型配置。" : "例如 deepseek-v4-flash，也可填写服务商要求的精确模型 ID。"}
              >
                {hasVerifiedModels ? (
                  <Select
                    id="llm-default-model"
                    name="llm-default-model"
                    value={defaultModel}
                    onChange={(event) => setDefaultModel(event.target.value)}
                    options={models.map((model) => ({ value: model, label: model }))}
                    contentAlign="start"
                    contentClassName="w-[var(--radix-select-trigger-width)]"
                    contentPosition="popper"
                  />
                ) : (
                  <input
                    id="llm-default-model"
                    name="llm-default-model"
                    value={defaultModel}
                    onChange={(event) => setDefaultModel(event.target.value)}
                    placeholder="例如 deepseek-v4-flash"
                    className="admin-input font-mono"
                    autoComplete="off"
                  />
                )}
              </Field>
            </div>
          )}

          <div>
            <Field
              label="上下文窗口"
              htmlFor="llm-context-window"
              description={contextWindowDescription}
            >
              <input
                id="llm-context-window"
                type="number"
                min={4096}
                max={2000000}
                step={1024}
                value={contextWindowValue}
                onChange={(event) => setContextWindow(event.target.value ? Number(event.target.value) : null)}
                placeholder="例如 128000"
                disabled={contextWindowIsAutomatic}
                className="admin-input font-mono disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-muted"
                aria-invalid={contextWindow !== null && (!Number.isInteger(contextWindow) || contextWindow < 4096 || contextWindow > 2000000)}
              />
            </Field>
          </div>
        </div>

        <ProbeFeedback state={probeState} />
      </div>
      )}

      {activeSection === "connections" && !connectionEditor && (
      <div id="model-connections" className="scroll-mt-5 px-5 py-6 sm:px-6">
        <ModelProfilesManager initial={initial} onChanged={onChanged} view="connections" onManageConnections={() => setActiveSection("connections")} />
      </div>
      )}

      {activeSection === "models" && !connectionEditor && (
      <div id="model-catalog" className="scroll-mt-5 px-5 py-6 sm:px-6">
        <ModelProfilesManager initial={initial} onChanged={onChanged} view="models" onManageConnections={() => setActiveSection("connections")} />
      </div>
      )}

      {activeSection === "routing" && hasProfiles && (
      <div id="model-routing" className="scroll-mt-5 px-5 py-6 sm:px-6">
        <ModelProfilesManager initial={initial} onChanged={onChanged} view="routing" />
      </div>
      )}

      {connectionEditor && (
      <footer className="flex flex-col gap-4 border-t border-surface-border/70 bg-surface-2/35 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div className="min-w-0 text-sm text-muted" aria-live="polite">
          {canSave
            ? initial?.configured
              ? "保存默认连接不会改动自动路由或会话中的固定模型选择。"
              : "保存后会自动建立第一个模型档案，随后可添加模型并配置自动路由。"
            : "请补全 Base URL、API Key 和模型 ID。"}
        </div>
        <div className="flex w-full flex-col-reverse gap-2 sm:w-auto sm:flex-row">
          <Button type="button" variant="ghost" size="sm" onClick={() => setConnectionEditor(null)} disabled={saving}>取消</Button>
          {initial?.configured && <Button type="button" variant="destructive" size="sm" onClick={() => setClearOpen(true)} disabled={saving}><Trash2 className="h-4 w-4" />清除个人配置</Button>}
          <Button type="button" onClick={handleSave} disabled={!canSave}>
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            {saving ? "正在保存" : initial?.configured ? "保存并应用" : "保存并继续"}
          </Button>
        </div>
      </footer>
      )}

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

function ModelProfilesManager({
  initial,
  onChanged,
  view,
  onManageConnections,
}: {
  initial?: MyLLMSettings;
  onChanged: () => Promise<MySettings>;
  view: "connections" | "models" | "routing";
  onManageConnections?: () => void;
}) {
  const profiles = initial?.model_profiles ?? [];
  const connections = useMemo(() => initial?.connections ?? [], [initial?.connections]);
  const managedConnections = connections.filter((connection) => !connection.is_legacy_default);
  const assignableConnections = managedConnections.filter((connection) => connection.enabled);
  const legacyConnections = connections.filter((connection) => connection.is_legacy_default && connection.enabled);
  const profileConnectionOptions = assignableConnections.length > 0 ? assignableConnections : legacyConnections;
  const enabledProfiles = profiles.filter((profile) => profile.enabled);
  const [adding, setAdding] = useState(false);
  const [addingService, setAddingService] = useState(false);
  const [showProfileOverrides, setShowProfileOverrides] = useState(false);
  const [profileProbeState, setProfileProbeState] = useState<ProbeState>({ kind: "idle" });
  const [profileModels, setProfileModels] = useState<string[]>([]);
  const [profileModelContextWindows, setProfileModelContextWindows] = useState<Record<string, number>>({});
  const [manualProfileModelId, setManualProfileModelId] = useState(false);
  const [profileContextOverride, setProfileContextOverride] = useState(false);
  const [name, setName] = useState("");
  const [modelId, setModelId] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [windowValue, setWindowValue] = useState("");
  const [connectionProvider, setConnectionProvider] = useState<LLMProvider>("openai-compat");
  const [connectionUrl, setConnectionUrl] = useState("");
  const [connectionKey, setConnectionKey] = useState("");
  const [connectionProbeState, setConnectionProbeState] = useState<ProbeState>({ kind: "idle" });
  const [savingConnection, setSavingConnection] = useState(false);
  const [deletingConnectionId, setDeletingConnectionId] = useState<string | null>(null);
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [profilePendingRemoval, setProfilePendingRemoval] = useState<LLMModelProfile | null>(null);
  const [connectionPendingRemoval, setConnectionPendingRemoval] = useState<LLMConnection | null>(null);
  const [defaultModel, setDefaultModel] = useState(initial?.default_profile_id ?? "");
  const [complexEnabled, setComplexEnabled] = useState(initial?.complex_enabled ?? false);
  const [complexModel, setComplexModel] = useState(initial?.complex_profile_id ?? "");
  const [triageModel, setTriageModel] = useState(initial?.triage_profile_id ?? "");
  const [fallbackModel, setFallbackModel] = useState(initial?.fallback_profile_id ?? "");

  useEffect(() => {
    setDefaultModel(initial?.default_profile_id ?? "");
    setComplexEnabled(initial?.complex_enabled ?? false);
    setComplexModel(initial?.complex_profile_id ?? "");
    setTriageModel(initial?.triage_profile_id ?? "");
    setFallbackModel(initial?.fallback_profile_id ?? "");
  }, [
    initial?.complex_enabled,
    initial?.complex_profile_id,
    initial?.default_profile_id,
    initial?.fallback_profile_id,
    initial?.triage_profile_id,
  ]);

  useEffect(() => {
    if (connectionId || profileConnectionOptions.length === 0) return;
    setConnectionId(profileConnectionOptions[0].id);
  }, [connectionId, profileConnectionOptions]);

  const resetProfileProbe = () => {
    setProfileProbeState({ kind: "idle" });
    setProfileModels([]);
    setProfileModelContextWindows({});
    setManualProfileModelId(false);
    setProfileContextOverride(false);
    setWindowValue("");
  };

  const selectProfileConnection = (nextConnectionId: string) => {
    setConnectionId(nextConnectionId);
    setModelId("");
    resetProfileProbe();
  };

  const handleProfileProtocolChange = (nextValue: string) => {
    if (nextValue === "anthropic") {
      setConnectionProvider("anthropic");
      setConnectionUrl(SERVICE_PRESETS.anthropic.baseUrl);
    } else if (nextValue === "openai") {
      setConnectionProvider("openai-compat");
      setConnectionUrl(SERVICE_PRESETS.openai.baseUrl);
    } else if (nextValue === "deepseek") {
      setConnectionProvider("openai-compat");
      setConnectionUrl(SERVICE_PRESETS.deepseek.baseUrl);
    } else {
      setConnectionProvider("openai-compat");
      setConnectionUrl("");
    }
    setModelId("");
    resetProfileProbe();
  };

  const applyProfileProbeResult = (result: {
    models: string[];
    context_windows?: Record<string, { value: number; source: "registry" }>;
  }) => {
    setProfileModels(result.models);
    setProfileModelContextWindows(
      Object.fromEntries(
        Object.entries(result.context_windows ?? {}).map(([model, context]) => [model, context.value])
      )
    );
    setManualProfileModelId(false);
    setProfileContextOverride(false);
    setWindowValue("");
    setModelId((current) => result.models.includes(current) ? current : result.models[0] ?? "");
    setProfileProbeState(result.models.length ? { kind: "success", count: result.models.length } : { kind: "empty" });
  };

  const handleProfileProbe = async () => {
    if (!connectionId || profileProbeState.kind === "loading") return;
    setProfileProbeState({ kind: "loading" });
    try {
      const result = await probeLLMConnection(connectionId);
      applyProfileProbeResult(result);
    } catch (error) {
      setProfileModels([]);
      setProfileModelContextWindows({});
      setProfileProbeState({
        kind: "error",
        message: error instanceof Error ? error.message : "无法测试服务，请检查连接后重试。",
      });
    }
  };

  const resetServiceProbe = () => setConnectionProbeState({ kind: "idle" });

  const handleServiceProbe = async () => {
    if (!connectionUrl.trim() || !connectionKey.trim() || connectionProbeState.kind === "loading") return;
    setConnectionProbeState({ kind: "loading" });
    try {
      const result = await probeLLM({
        provider: connectionProvider,
        base_url: connectionUrl.trim(),
        api_key: connectionKey.trim(),
      });
      setConnectionProbeState(result.models.length ? { kind: "success", count: result.models.length } : { kind: "empty" });
    } catch (error) {
      setConnectionProbeState({
        kind: "error",
        message: error instanceof Error ? error.message : "无法测试服务，请检查配置后重试。",
      });
    }
  };

  const createServiceConnection = async () => {
    if (!connectionUrl.trim() || !connectionKey.trim()) return;
    const normalizedUrl = connectionUrl.trim().replace(/\/$/, "");
    const matchingConnection = managedConnections.find(
      (connection) =>
        connection.provider === connectionProvider &&
        connection.base_url.replace(/\/$/, "") === normalizedUrl
    );
    if (matchingConnection) {
      setConnectionId(matchingConnection.id);
      setAddingService(false);
      toast.info("已复用相同服务地址的已有连接。");
      return;
    }
    setSavingConnection(true);
    try {
      const created = await createLLMConnection({
        display_name: generatedConnectionName(connectionProvider, normalizedUrl),
        provider: connectionProvider,
        base_url: normalizedUrl,
        api_key: connectionKey.trim(),
        enabled: true,
      });
      setConnectionId(created.id);
      setConnectionKey("");
      setAddingService(false);
      resetServiceProbe();
      await onChanged();
      toast.success("服务连接已保存");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存服务连接失败");
    } finally {
      setSavingConnection(false);
    }
  };

  const profileDetectedContextWindow = profileModelContextWindows[modelId];
  const profileContextIsAutomatic = !profileContextOverride && Boolean(profileDetectedContextWindow);
  const profileContextValue = profileContextIsAutomatic ? profileDetectedContextWindow : windowValue;
  const selectedProfileConnection = profileConnectionOptions.find((connection) => connection.id === connectionId);
  const savedConnectionProtocol = selectedProfileConnection?.provider === "anthropic" ? "Anthropic Messages" : "OpenAI Compatible";
  const profileProtocolValue =
    connectionProvider === "anthropic"
      ? "anthropic"
      : connectionUrl === SERVICE_PRESETS.openai.baseUrl
        ? "openai"
        : connectionUrl === SERVICE_PRESETS.deepseek.baseUrl
          ? "deepseek"
          : "custom-compatible";

  const addProfile = async () => {
    const parsedWindow = windowValue.trim() ? Number(windowValue) : null;
    if (!modelId.trim()) return;
    if (parsedWindow !== null && (!Number.isInteger(parsedWindow) || parsedWindow < 4_096 || parsedWindow > 2_000_000)) {
      toast.error("上下文窗口需在 4,096 到 2,000,000 之间。");
      return;
    }
    setSavingProfile(true);
    try {
      const profileConnectionId = connectionId;
      if (!profileConnectionId) {
        toast.error("请选择或配置一个服务连接。" );
        return;
      }
      await createLLMModelProfile({
        connection_id: profileConnectionId,
        display_name: name.trim() || modelId.trim(),
        model_id: modelId.trim(),
        context_window: parsedWindow,
        enabled: true,
        supports_tools: true,
      });
      setName("");
      setModelId("");
      setWindowValue("");
      setShowProfileOverrides(false);
      resetProfileProbe();
      setAdding(false);
      await onChanged();
      toast.success("模型已加入可用列表");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "添加模型失败");
    } finally {
      setSavingProfile(false);
    }
  };

  const removeConnection = async (connection: LLMConnection) => {
    setDeletingConnectionId(connection.id);
    try {
      await deleteLLMConnection(connection.id);
      if (connection.id === connectionId) setConnectionId("");
      await onChanged();
      toast.success("连接已移除");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "移除连接失败");
    } finally {
      setDeletingConnectionId(null);
    }
  };

  const savePolicy = async () => {
    if (!defaultModel) {
      toast.error("请选择默认模型。");
      return;
    }
    if (complexEnabled && !complexModel) {
      toast.error("已开启复杂任务路由，请选择复杂模型。");
      return;
    }
    setSavingPolicy(true);
    try {
      await saveLLMModelPolicy({
        default_profile_id: defaultModel,
        complex_enabled: complexEnabled,
        complex_profile_id: complexEnabled ? complexModel : null,
        triage_profile_id: triageModel || null,
        fallback_profile_id: fallbackModel || null,
      });
      await onChanged();
      toast.success("模型路由策略已保存");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存路由策略失败");
    } finally {
      setSavingPolicy(false);
    }
  };

  const removeProfile = async (profile: LLMModelProfile) => {
    setDeletingId(profile.id);
    try {
      await deleteLLMModelProfile(profile.id);
      await onChanged();
      toast.success("模型已从可用列表移除");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "移除模型失败");
    } finally {
      setDeletingId(null);
    }
  };

  const selectOptions = enabledProfiles.map((profile) => ({
    value: profile.id,
    label: `${connectionLabel(connections.find((connection) => connection.id === profile.connection_id))} / ${profile.display_name} · ${profile.model_id}`,
  }));

  if (view === "connections") {
    return (
      <section aria-labelledby="service-connections-heading">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold text-brand">服务连接</p>
            <h3 id="service-connections-heading" className="mt-1 text-balance text-lg font-semibold">管理模型服务与凭据</h3>
            <p className="mt-1 text-pretty text-sm leading-6 text-muted">服务连接保存协议、地址和加密密钥。验证成功后，再到模型配置中选择该服务返回的模型。</p>
          </div>
          <Button type="button" size="sm" onClick={() => setAddingService((open) => !open)}><Plus className="h-4 w-4" />添加服务</Button>
        </div>

        {managedConnections.length === 0 ? (
          <div className="mt-5 flex min-h-52 flex-col items-center justify-center rounded-lg border border-dashed border-surface-border/90 bg-surface-2/35 px-5 py-8 text-center">
            <span className="admin-icon-tile admin-icon-tile-lg text-brand" aria-hidden><Cloud className="h-5 w-5" /></span>
            <p className="mt-3 text-balance text-base font-semibold text-ink">还没有服务连接</p>
            <p className="mt-1 max-w-lg text-pretty text-sm leading-6 text-muted">先添加并验证一个服务，再把它提供的模型加入可用列表。</p>
            <Button type="button" size="sm" className="mt-4" onClick={() => setAddingService(true)}><Plus className="h-4 w-4" />添加服务</Button>
          </div>
        ) : (
          <div className="mt-5 divide-y divide-surface-border/70 border-y border-surface-border/70">
            {managedConnections.map((connection) => {
              const usageCount = profiles.filter((profile) => profile.connection_id === connection.id).length;
              return (
                <div key={connection.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-medium text-ink">{connectionLabel(connection)}</p>
                      <Badge variant="outline" className="border-brand/25 bg-brand/10 text-brand">{connection.provider === "anthropic" ? "Anthropic Messages" : "OpenAI Compatible"}</Badge>
                      <span className="text-xs text-muted">{usageCount ? `供 ${usageCount} 个模型使用` : "尚未绑定模型"}</span>
                    </div>
                    <p className="mt-1 truncate font-mono text-xs text-muted">{connection.base_url}</p>
                  </div>
                  <Button type="button" variant="destructive" size="sm" className="disabled:border-surface-border/80 disabled:bg-surface-2 disabled:text-muted disabled:opacity-70" onClick={() => setConnectionPendingRemoval(connection)} disabled={Boolean(usageCount) || deletingConnectionId === connection.id} title={usageCount ? "请先移除或迁移使用此连接的模型" : "移除服务连接"}>{deletingConnectionId === connection.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}移除</Button>
                </div>
              );
            })}
          </div>
        )}

        {addingService && (
          <section className="mt-5 border-y border-surface-border/70 bg-surface-2/20 py-5" aria-labelledby="add-service-connection-heading">
            <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h4 id="add-service-connection-heading" className="text-base font-semibold text-ink">添加服务连接</h4>
                <p className="mt-1 text-xs leading-5 text-muted">填写服务协议、地址和密钥。模型会在下一步单独加入可用列表。</p>
              </div>
              <Button type="button" variant="outline" size="sm" onClick={() => setAddingService(false)} disabled={savingConnection}>取消</Button>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="服务协议" htmlFor="service-provider" description={connectionProvider === "anthropic" ? "使用 Anthropic 的 Messages API。" : "兼容 OpenAI API 的服务，如 DeepSeek、OpenAI、vLLM 或 LM Studio。"}>
                <Select id="service-provider" value={profileProtocolValue} onChange={(event) => { handleProfileProtocolChange(event.target.value); resetServiceProbe(); }} options={[{ value: "anthropic", label: "Anthropic Messages" }, { value: "openai", label: "OpenAI" }]} submenus={[{ label: "OpenAI Compatible", options: [{ value: "deepseek", label: "DeepSeek" }, { value: "custom-compatible", label: "自定义兼容地址" }] }]} />
              </Field>
              <Field label="Base URL" htmlFor="service-base-url" description="填写 API 根地址，不确定时使用服务商文档中的 API 地址。">
                <input id="service-base-url" type="url" value={connectionUrl} onChange={(event) => { setConnectionUrl(event.target.value); resetServiceProbe(); }} placeholder={connectionProvider === "anthropic" ? "https://api.anthropic.com" : "https://api.example.com/v1"} className="admin-input" autoComplete="off" />
              </Field>
              <Field label="API Key" htmlFor="service-api-key" description="Key 会加密保存，不会在此页回显。">
                <div className="flex flex-col gap-2 sm:flex-row">
                  <div className="relative min-w-0 flex-1">
                    <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
                    <input id="service-api-key" type="password" value={connectionKey} onChange={(event) => { setConnectionKey(event.target.value); resetServiceProbe(); }} placeholder={connectionProvider === "anthropic" ? "sk-ant-..." : "sk-..."} className="admin-input pl-9" autoComplete="new-password" />
                  </div>
                  <Button type="button" variant="outline" onClick={handleServiceProbe} disabled={!connectionUrl.trim() || !connectionKey.trim() || connectionProbeState.kind === "loading"} className="w-full sm:w-auto">
                    {connectionProbeState.kind === "loading" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Cloud className="h-4 w-4" />}
                    {connectionProbeState.kind === "loading" ? "正在测试" : "测试连接"}
                  </Button>
                </div>
              </Field>
            </div>
            <ProbeFeedback state={connectionProbeState} />
            <div className="mt-5 flex items-center gap-2">
              <Button type="button" onClick={createServiceConnection} disabled={savingConnection || !connectionUrl.trim() || !connectionKey.trim()}>{savingConnection && <Loader2 className="h-4 w-4 animate-spin" />}{savingConnection ? "正在保存" : "保存服务"}</Button>
            </div>
          </section>
        )}

        <ConfirmDialog
          open={Boolean(connectionPendingRemoval)}
          onOpenChange={(open) => {
            if (!open) setConnectionPendingRemoval(null);
          }}
          title={connectionPendingRemoval ? `移除服务“${connectionLabel(connectionPendingRemoval)}”？` : "移除服务连接？"}
          description="该服务连接会被永久移除，且无法恢复。仅未被模型使用的连接可以移除。"
          confirmLabel="移除服务"
          variant="danger"
          busy={Boolean(connectionPendingRemoval && deletingConnectionId === connectionPendingRemoval.id)}
          onConfirm={async () => {
            if (!connectionPendingRemoval) return;
            await removeConnection(connectionPendingRemoval);
            setConnectionPendingRemoval(null);
          }}
        />
      </section>
    );
  }

  if (view === "routing") {
    return (
      <section aria-labelledby="model-routing-heading">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold text-brand">路由策略</p>
          <h3 id="model-routing-heading" className="mt-1 text-balance text-lg font-semibold">选择未固定模型的会话如何执行</h3>
          <p className="mt-1 text-pretty text-sm leading-6 text-muted">模型配置不会自动改变会话行为。在这里选择默认、复杂任务、Flash 意图识别和备用模型。</p>
        </div>
        <div className="mt-6 grid gap-4 border-t border-surface-border/70 pt-5 sm:grid-cols-2">
          <Field label="默认模型" htmlFor="policy-default-model" description="未在会话中固定模型时使用。">
            <Select id="policy-default-model" value={defaultModel} onChange={(event) => setDefaultModel(event.target.value)} options={selectOptions} />
          </Field>
          <div className="flex min-h-[var(--control-h)] items-start justify-between gap-4 pt-6">
            <div>
              <p className="text-sm font-medium text-ink">复杂任务模型</p>
              <p className="mt-1 text-xs leading-5 text-muted">关闭时自动会话始终使用默认模型。</p>
            </div>
            <Switch checked={complexEnabled} onCheckedChange={setComplexEnabled} aria-label="开启复杂任务模型" />
          </div>
          {complexEnabled && (
            <Field label="复杂模型" htmlFor="policy-complex-model" description="多工具或超长输入时升级使用。">
              <Select id="policy-complex-model" value={complexModel} onChange={(event) => setComplexModel(event.target.value)} options={selectOptions} />
            </Field>
          )}
          <Field label="Flash 意图模型（可选）" htmlFor="policy-triage-model" description="只用于 KB 查询策略与意图判断，不承担最终回答。">
            <Select id="policy-triage-model" value={triageModel} onChange={(event) => setTriageModel(event.target.value)} options={selectOptions} placeholderOption={{ value: "", label: "不单独配置" }} />
          </Field>
          <Field label="备用模型（可选）" htmlFor="policy-fallback-model" description="首个输出前请求失败或空回答时才会接管。">
            <Select id="policy-fallback-model" value={fallbackModel} onChange={(event) => setFallbackModel(event.target.value)} options={selectOptions} placeholderOption={{ value: "", label: "不单独配置" }} />
          </Field>
          <div className="flex items-end">
            <Button type="button" onClick={savePolicy} disabled={savingPolicy}>
              {savingPolicy && <Loader2 className="h-4 w-4 animate-spin" />}
              {savingPolicy ? "正在保存" : "保存路由策略"}
            </Button>
          </div>
        </div>
      </section>
    );
  }

  if (profiles.length === 0 && !adding) {
    return (
      <section className="py-2" aria-labelledby="model-empty-heading">
        <div className="flex flex-col gap-4 border-b border-surface-border/70 pb-5 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold text-brand">模型配置</p>
            <h3 id="model-empty-heading" className="mt-1 text-balance text-lg font-semibold">还没有模型配置</h3>
          <p className="mt-1 text-pretty text-sm leading-6 text-muted">模型配置只绑定已验证的服务。创建后，才能在会话中选择模型或在路由策略中指定其职责。</p>
          </div>
        </div>
        <div className="mt-6 flex min-h-72 flex-col items-center justify-center rounded-lg border border-dashed border-surface-border/90 bg-surface-2/35 px-5 py-10 text-center">
          <span className="admin-icon-tile admin-icon-tile-lg text-brand" aria-hidden><Plus className="h-5 w-5" /></span>
          <p className="mt-4 text-balance text-base font-semibold text-ink">{profileConnectionOptions.length ? "从第一个模型配置开始" : "先添加一个服务连接"}</p>
          <p className="mt-2 max-w-lg text-pretty text-sm leading-6 text-muted">{profileConnectionOptions.length ? "选择一个已验证服务，再把它提供的模型加入可用列表。默认模型和自动路由将在下一步单独配置。" : "服务连接保存协议、地址和密钥。验证连接成功后，就可以在模型配置中选择模型。"}</p>
          <Button type="button" size="sm" className="mt-5" onClick={profileConnectionOptions.length ? () => setAdding(true) : onManageConnections}>
            <Plus className="h-4 w-4" />{profileConnectionOptions.length ? "添加模型" : "添加服务"}
          </Button>
        </div>
        <p className="mt-4 flex items-start gap-2 rounded-lg border border-surface-border/70 bg-surface-2/35 px-3 py-2.5 text-sm leading-5 text-muted"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-brand" aria-hidden />服务连接不会立即改变会话行为；路由策略将在模型配置创建后解锁。</p>
      </section>
    );
  }

  return (
    <section aria-labelledby="model-profiles-heading">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold text-brand">模型配置</p>
          <h3 id="model-profiles-heading" className="mt-1 text-balance text-lg font-semibold">可用模型配置</h3>
          <p className="mt-1 text-pretty text-sm leading-6 text-muted">
            每个配置绑定一个连接、模型 ID 和上下文窗口。会话固定选择与路由策略都使用这份列表。
          </p>
        </div>
        <Button type="button" size="sm" onClick={() => setAdding((open) => !open)}><Plus className="h-4 w-4" />添加模型</Button>
      </div>

      <div className="mt-5 divide-y divide-surface-border/70 border-y border-surface-border/70">
        {profiles.map((profile) => (
          <div key={profile.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-medium text-ink">{profile.display_name}</p>
                <Badge variant="outline" className={profile.enabled ? "border-brand/25 bg-brand/10 text-brand" : "border-surface-border bg-surface-2 text-muted"}>
                  {profile.enabled ? "可选" : "已停用"}
                </Badge>
                <span className="text-xs text-muted">{profile.context_window ? `${profile.context_window / 1000}K` : "上下文自动识别"}</span>
              </div>
              <p className="mt-1 flex flex-wrap gap-x-2 text-xs text-muted">
                {profile.display_name !== profile.model_id && <span className="font-mono" title={profile.model_id}>{profile.model_id}</span>}
                <span>服务：{connectionLabel(connections.find((connection) => connection.id === profile.connection_id))}</span>
              </p>
            </div>
            <Button type="button" variant="destructive" size="sm" onClick={() => setProfilePendingRemoval(profile)} disabled={deletingId === profile.id}>
              {deletingId === profile.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              移除
            </Button>
          </div>
        ))}
      </div>

      {adding && (
        <section className="mt-5 border-y border-surface-border/70 bg-surface-2/20 py-5" aria-labelledby="add-model-profile-heading">
          <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h4 id="add-model-profile-heading" className="text-base font-semibold text-ink">添加模型配置</h4>
              <p className="mt-1 text-xs leading-5 text-muted">先指定模型 ID 和调用服务，其他信息会自动采用安全默认值。</p>
            </div>
            <Button type="button" variant="outline" size="sm" onClick={() => setAdding(false)} disabled={savingProfile}>取消</Button>
          </div>
          <div className="mb-4 flex flex-col gap-3 border-b border-surface-border/70 pb-4 sm:flex-row sm:items-end sm:justify-between">
            <div className="w-full sm:max-w-sm">
              <Field label="使用已保存服务" htmlFor="profile-connection" description="凭据已加密保存，仍可重新测试。">
                <Select id="profile-connection" value={connectionId} onChange={(event) => selectProfileConnection(event.target.value)} options={profileConnectionOptions.map((connection) => ({ value: connection.id, label: connectionLabel(connection) }))} />
              </Field>
            </div>
            <Button type="button" variant="outline" size="sm" onClick={onManageConnections}>管理服务连接</Button>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="服务协议" htmlFor="profile-saved-provider" description="由已保存服务决定。">
              <Select id="profile-saved-provider" value={selectedProfileConnection?.provider ?? "openai-compat"} disabled options={[{ value: "openai-compat", label: savedConnectionProtocol }, { value: "anthropic", label: savedConnectionProtocol }]} />
            </Field>
            <Field label="Base URL" htmlFor="profile-saved-base-url" description="由已保存服务决定。">
              <input id="profile-saved-base-url" value={selectedProfileConnection?.base_url ?? ""} className="admin-input font-mono disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-muted" disabled />
            </Field>
            <Field label="API Key" htmlFor="profile-saved-api-key" description="已安全保存，测试时仅在服务端使用。">
              <div className="flex flex-col gap-2 sm:flex-row">
                <div className="relative min-w-0 flex-1">
                  <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
                  <input id="profile-saved-api-key" value="已安全保存" className="admin-input pl-9 disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-muted" disabled />
                </div>
                <Button type="button" variant="outline" onClick={handleProfileProbe} disabled={!connectionId || profileProbeState.kind === "loading"} className="w-full sm:w-auto">
                  {profileProbeState.kind === "loading" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Cloud className="h-4 w-4" />}
                  {profileProbeState.kind === "loading" ? "正在测试" : "测试连接"}
                </Button>
              </div>
            </Field>
            <Field
              label="模型 ID"
              htmlFor="profile-model-id"
              description={profileProbeState.kind === "success" && !manualProfileModelId ? "已从服务返回的模型中选择。" : "按服务商要求填写精确 ID，例如 deepseek-chat。"}
            >
              {profileProbeState.kind === "success" && profileModels.length > 0 && !manualProfileModelId ? (
                <>
                  <Select id="profile-model-id" value={modelId} onChange={(event) => { setModelId(event.target.value); setWindowValue(""); setProfileContextOverride(false); }} options={profileModels.map((model) => ({ value: model, label: model }))} />
                  <Button type="button" variant="link" size="xs" onClick={() => { setManualProfileModelId(true); setWindowValue(""); setProfileContextOverride(false); }} className="mt-2 h-auto px-0">手动填写模型 ID</Button>
                </>
              ) : (
                <>
                  <input id="profile-model-id" value={modelId} onChange={(event) => { setModelId(event.target.value); setWindowValue(""); setProfileContextOverride(false); }} className="admin-input font-mono" autoComplete="off" autoFocus />
                  {profileProbeState.kind === "success" && profileModels.length > 0 && (
                    <Button type="button" variant="link" size="xs" onClick={() => { setManualProfileModelId(false); setModelId(profileModels[0]); setWindowValue(""); setProfileContextOverride(false); }} className="mt-2 h-auto px-0">从服务列表选择</Button>
                  )}
                </>
              )}
            </Field>
            <Field
              label="上下文窗口"
              htmlFor="profile-context-window"
              description={profileContextIsAutomatic ? "已由模型能力库自动识别，将用于历史保留、摘要触发与输出预算。" : "未知模型可填写实际窗口，范围为 4,096 到 2,000,000。"}
            >
              <input id="profile-context-window" type="number" min={4096} max={2000000} step={1024} value={profileContextValue ?? ""} onChange={(event) => setWindowValue(event.target.value)} className="admin-input font-mono disabled:cursor-not-allowed disabled:opacity-70" disabled={profileContextIsAutomatic} />
              {profileDetectedContextWindow && (
                <Button type="button" variant="link" size="xs" onClick={() => {
                  if (profileContextOverride) {
                    setProfileContextOverride(false);
                    setWindowValue("");
                  } else {
                    setProfileContextOverride(true);
                    setWindowValue(String(profileDetectedContextWindow));
                  }
                }} className="mt-2 h-auto px-0">
                  {profileContextOverride ? "恢复自动识别" : "手动覆盖"}
                </Button>
              )}
            </Field>
          </div>
          <ProbeFeedback state={profileProbeState} />
          <details className="mt-4 border-t border-surface-border/70 pt-3" open={showProfileOverrides} onToggle={(event) => setShowProfileOverrides(event.currentTarget.open)}>
            <summary className="cursor-pointer text-xs font-medium text-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30">高级选项：自定义显示名称</summary>
            <div className="mt-4">
              <Field label="显示名称（可选）" htmlFor="profile-name" description="留空时直接使用模型 ID。">
                <input id="profile-name" value={name} onChange={(event) => setName(event.target.value)} className="admin-input" placeholder={modelId || "例如 长文分析"} autoComplete="off" />
              </Field>
            </div>
          </details>
          <div className="mt-5 flex items-center gap-2">
            <Button type="button" size="sm" onClick={addProfile} disabled={savingProfile || !modelId.trim() || !connectionId}>
              {savingProfile && <Loader2 className="h-4 w-4 animate-spin" />}
              {savingProfile ? "正在添加" : "加入可用列表"}
            </Button>
          </div>
        </section>
      )}

      <ConfirmDialog
        open={Boolean(profilePendingRemoval)}
        onOpenChange={(open) => {
          if (!open) setProfilePendingRemoval(null);
        }}
        title={profilePendingRemoval ? `移除“${profilePendingRemoval.display_name}”？` : "移除模型配置？"}
        description="模型会从会话选择和路由策略的可用列表中移除。已保存的服务连接不会被删除。"
        confirmLabel="移除模型"
        variant="danger"
        busy={Boolean(profilePendingRemoval && deletingId === profilePendingRemoval.id)}
        onConfirm={async () => {
          if (!profilePendingRemoval) return;
          await removeProfile(profilePendingRemoval);
          setProfilePendingRemoval(null);
        }}
      />

    </section>
  );
}

function EffectiveStatus({
  source,
  hasProfiles,
  hasDefaultProfile,
}: {
  source: "user" | "system" | "missing";
  hasProfiles: boolean;
  hasDefaultProfile: boolean;
}) {
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
  if (hasProfiles && !hasDefaultProfile) {
    return (
      <Badge variant="outline" className="border-warning/30 bg-warning/10 text-warning">
        <CircleAlert className="h-3.5 w-3.5" />
        尚未设置默认模型
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="border-warning/30 bg-warning/10 text-warning">
      <CircleAlert className="h-3.5 w-3.5" />
      {hasProfiles ? "模型尚未生效" : "添加第一个模型"}
    </Badge>
  );
}

function ProbeFeedback({ state }: { state: ProbeState }) {
  if (state.kind === "idle") return null;
  if (state.kind === "loading") {
    return <p className="mt-4 flex items-center gap-2 text-sm text-muted" role="status"><Loader2 className="h-4 w-4 animate-spin" />正在验证服务与模型列表…</p>;
  }
  if (state.kind === "success") {
    return <InlineNotice icon={<CheckCircle2 className="h-4 w-4" />} tone="success">连接成功，发现 {state.count} 个模型。</InlineNotice>;
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
