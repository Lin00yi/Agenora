"use client";

import { CheckCircle2, Globe2, KeyRound, Loader2, RotateCcw, Save } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { SettingsModuleSkeleton } from "@/components/settings/SettingsModuleSkeleton";
import { cn } from "@/lib/cn";
import {
  clearWebSearchSettings,
  getMySettings,
  saveWebSearchSettings,
  SettingsApiError,
  type MyWebSearchSettings,
  type WebSearchProvider,
} from "@/lib/settings-api";
import { toast } from "@/lib/toast";

const PROVIDERS: Array<{ value: WebSearchProvider; label: string; description: string }> = [
  { value: "duckduckgo", label: "DuckDuckGo", description: "无需 API Key，适合默认公共检索。" },
  { value: "brave", label: "Brave Search", description: "需要 Brave Search API Key。" },
  { value: "bing", label: "Bing Search", description: "需要 Bing Search API Key。" },
  { value: "tavily", label: "Tavily", description: "面向 AI Agent 的网页搜索 API，需要 Key。" },
];

const LEGACY_WEB_SEARCH_SETTINGS: MyWebSearchSettings = {
  provider: null,
  has_key: false,
  configured: false,
  effective_provider: "duckduckgo",
};

function providerLabel(value: WebSearchProvider) {
  return PROVIDERS.find((item) => item.value === value)?.label ?? value;
}

function settingsErrorMessage(error: unknown, fallback: string) {
  if (
    error instanceof SettingsApiError &&
    typeof error.detail === "object" &&
    error.detail !== null &&
    typeof (error.detail as { message?: unknown }).message === "string"
  ) {
    return (error.detail as { message: string }).message;
  }
  return error instanceof Error ? error.message : fallback;
}

/** Independent settings surface for the engine behind the web_search tool. */
export function WebSearchSettingsModule({ embedded = false }: { embedded?: boolean }) {
  const [initial, setInitial] = useState<MyWebSearchSettings | null>(null);
  const [provider, setProvider] = useState<WebSearchProvider>("duckduckgo");
  const [apiKey, setApiKey] = useState("");
  const [keyEditing, setKeyEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);

  const refresh = async () => {
    const settings = await getMySettings();
    // A frontend can be deployed just before its backend. Keep this screen
    // usable during that short rollout window instead of dereferencing an
    // absent field in the legacy GET /api/settings/me response.
    const next = settings.web_search ?? LEGACY_WEB_SEARCH_SETTINGS;
    setInitial(next);
    setProvider(next.provider ?? next.effective_provider ?? "duckduckgo");
    setApiKey("");
    setKeyEditing(false);
    return next;
  };

  useEffect(() => {
    refresh()
      .catch((error) => toast.error(error instanceof Error ? error.message : "读取联网搜索设置失败"))
      .finally(() => setLoading(false));
    // Initial load only; refresh is intentionally recreated each render.
  }, []);

  const needsKey = provider !== "duckduckgo";
  const hasSavedKey = Boolean(initial?.provider === provider && initial?.has_key);
  const dirty = provider !== (initial?.provider ?? initial?.effective_provider) || Boolean(apiKey);
  const canSave = !saving && (!needsKey || Boolean(apiKey.trim() || hasSavedKey));

  const save = async () => {
    if (!canSave) {
      toast.error("请填写 API Key");
      return;
    }
    setSaving(true);
    try {
      await saveWebSearchSettings({ provider, api_key: apiKey });
      await refresh();
      toast.success(`连接成功，已切换为 ${providerLabel(provider)}`);
    } catch (error) {
      toast.error(settingsErrorMessage(error, "验证失败，未保存配置"));
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    setResetting(true);
    try {
      await clearWebSearchSettings();
      const next = await refresh();
      toast.success(`已恢复系统默认：${providerLabel(next.effective_provider)}`);
    } catch (error) {
      toast.error(settingsErrorMessage(error, "默认搜索引擎不可用，未恢复配置"));
    } finally {
      setResetting(false);
    }
  };

  if (loading) {
    return <SettingsModuleSkeleton className={cn(!embedded && "mx-auto max-w-3xl")} rows={3} />;
  }

  return (
    <main className={cn("text-ink", embedded ? "w-full px-5 py-5 sm:px-6" : "app-page-content mx-auto max-w-3xl px-4 py-6 sm:px-6 sm:py-8")}>
      {!embedded ? (
        <header>
        <p className="text-xs font-semibold tracking-[0.16em] text-brand">工具与外部数据</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">联网搜索</h1>
        <p className="mt-2 text-sm leading-6 text-muted">配置对话中 <code>web_search</code> 工具使用的搜索引擎。保存前会用当前 Key 发起真实搜索，验证失败不会替换现有配置。</p>
        </header>
      ) : null}

      <section className={cn("rounded-xl border border-surface-border bg-surface p-4 shadow-sm sm:p-5", !embedded && "mt-6")}>
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-brand/10 p-2 text-brand"><Globe2 className="h-5 w-5" /></div>
          <div>
            <h2 className="font-semibold">搜索引擎</h2>
            <p className="mt-1 text-sm text-muted">未单独保存时，继续使用部署者在环境变量中配置的默认引擎。</p>
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          {PROVIDERS.map((item) => {
            const selected = provider === item.value;
            return (
              <label key={item.value} className={cn("cursor-pointer rounded-lg border p-3 transition-colors", selected ? "border-brand bg-brand/5" : "border-surface-border hover:bg-surface-2/60")}>
                <input className="sr-only" type="radio" name="web-search-provider" value={item.value} checked={selected} onChange={() => { setProvider(item.value); setApiKey(""); setKeyEditing(false); }} />
                <span className="flex items-center gap-2 text-sm font-medium">
                  <span className={cn("flex h-4 w-4 items-center justify-center rounded-full border", selected ? "border-brand bg-brand text-on-brand" : "border-muted")}>
                    {selected && <CheckCircle2 className="h-3 w-3" />}
                  </span>
                  {item.label}
                </span>
                <span className="mt-1 block pl-6 text-xs leading-5 text-muted">{item.description}</span>
              </label>
            );
          })}
        </div>

        {needsKey && (
          <div className="mt-5">
            <label htmlFor="web-search-api-key" className="mb-1.5 block text-sm font-medium">API Key</label>
            {hasSavedKey && !keyEditing ? (
              <div className="flex min-h-[44px] items-center gap-3 rounded-lg border border-surface-border bg-surface-2/45 px-3 text-sm">
                <KeyRound className="h-4 w-4 text-success" />
                <span className="flex-1">已使用保存的 API Key</span>
                <button type="button" onClick={() => setKeyEditing(true)} className="app-mini-link app-mini-link-brand">修改</button>
              </div>
            ) : (
              <div className="relative">
                <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <input id="web-search-api-key" type="password" autoComplete="new-password" data-lpignore="true" data-1p-ignore="true" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="粘贴 API Key" className="admin-input pl-9" />
                {hasSavedKey && <button type="button" onClick={() => { setApiKey(""); setKeyEditing(false); }} className="app-mini-link app-mini-link-muted absolute right-3 top-1/2 -translate-y-1/2">取消</button>}
              </div>
            )}
            <p className="mt-1.5 text-xs text-muted">密钥会加密保存，不会再次展示或发送给浏览器以外的第三方。</p>
          </div>
        )}

        <div className="mt-6 flex flex-col-reverse gap-2 border-t border-surface-border pt-4 sm:flex-row sm:justify-end">
          {initial?.configured && <Button type="button" variant="ghost" onClick={reset} disabled={resetting || saving}><RotateCcw className="h-4 w-4" />{resetting ? "恢复中…" : "恢复系统默认"}</Button>}
          <Button type="button" onClick={save} disabled={!canSave || (!dirty && initial?.configured)}><Save className="h-4 w-4" />{saving ? <><Loader2 className="h-4 w-4 animate-spin" />验证中…</> : "验证并保存"}</Button>
        </div>
      </section>
    </main>
  );
}
