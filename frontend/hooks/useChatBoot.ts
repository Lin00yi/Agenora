"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "@/lib/toast";

import { getToken, getUser, type User } from "@/lib/auth";
import {
  listConversations,
  migrateFromLocalStorage,
  type ConversationSummary,
} from "@/lib/conversations-api";
import { listKbs, type KB } from "@/lib/kb-api";
import type { LlmSource } from "@/components/chat";
import type { LLMModelProfile } from "@/lib/settings-api";
import {
  CHAT_PANE_FADE_MS,
  CONVERSATION_PAGE_SIZE,
  conversationHref,
  prefersReducedMotion,
  uniqueStrings,
} from "@/lib/chatPageHelpers";

type BootPhase = "loading" | "leaving" | "gone";

/**
 * Auth check, local migration, LLM probe, first conversation page load,
 * boot overlay fade, KB list, and `?account=1` deep-link into settings.
 */
export function useChatBoot({
  routeConversationId,
  startBlank,
  loadConversation,
  clearActiveConversation,
  setSummaries,
  setConversationTotal,
  setConversationPage,
  setConversationHasMore,
}: {
  routeConversationId: string | null;
  startBlank: boolean;
  loadConversation: (id: string) => Promise<boolean>;
  clearActiveConversation: () => void;
  setSummaries: (next: ConversationSummary[] | ((prev: ConversationSummary[]) => ConversationSummary[])) => void;
  setConversationTotal: (next: number | ((prev: number) => number)) => void;
  setConversationPage: (next: number | ((prev: number) => number)) => void;
  setConversationHasMore: (next: boolean | ((prev: boolean) => boolean)) => void;
}) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [initialLoadDone, setInitialLoadDone] = useState(false);
  const [bootPhase, setBootPhase] = useState<BootPhase>("loading");
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [modelLabels, setModelLabels] = useState<Record<string, string>>({});
  const [modelProfiles, setModelProfiles] = useState<LLMModelProfile[]>([]);
  const [llmReady, setLlmReady] = useState(false);
  const [llmSource, setLlmSource] = useState<LlmSource>("missing");
  const [kbs, setKbs] = useState<KB[]>([]);
  const [systemSettingsOpen, setSystemSettingsOpen] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("account") !== "1") return;
    setSystemSettingsOpen(true);
    params.delete("account");
    const next = `${window.location.pathname}${params.toString() ? `?${params}` : ""}${window.location.hash}`;
    window.history.replaceState(null, "", next);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!getToken()) {
        router.replace("/welcome");
        return;
      }

      const u = getUser();
      if (cancelled) return;
      setUser(u);
      setAuthChecked(true);

      if (u) {
        try {
          const imported = await migrateFromLocalStorage(u.id);
          if (!cancelled && imported > 0) {
            toast.success(`已从本地恢复 ${imported} 条历史对话`);
          }
        } catch (e) {
          console.warn("conversation migration failed", e);
        }

        try {
          const { getMySettings, probeLLM } = await import("@/lib/settings-api");
          const settings = await getMySettings();
          const effectiveSource =
            settings.llm.effective_source ?? (settings.llm.configured ? "user" : "missing");
          const effectiveReady = settings.llm.effective_configured ?? settings.llm.configured;
          const enabledProfiles = (settings.llm.model_profiles ?? []).filter((profile) => {
            if (!profile.enabled) return false;
            const connection = (settings.llm.connections ?? []).find(
              (item) => item.id === profile.connection_id
            );
            return Boolean(connection?.enabled && connection.has_key);
          });
          const profileModels = enabledProfiles.map((profile) => profile.model_id);
          const labels = Object.fromEntries(
            enabledProfiles.flatMap((profile) => {
              const connection = (settings.llm.connections ?? []).find(
                (item) => item.id === profile.connection_id
              );
              return [
                [profile.model_id, profile.display_name],
                [profile.id, `${connection?.display_name ?? "默认连接"} / ${profile.display_name}`],
              ];
            })
          );
          let discoveredModels: string[] = [];
          if (settings.llm.provider && settings.llm.base_url) {
            let models: string[] = [];
            try {
              ({ models } = await probeLLM({
                provider: settings.llm.provider,
                base_url: settings.llm.base_url,
                api_key: "",
              }));
            } catch (error) {
              console.warn("LLM model probe failed; using saved model profiles", error);
            }
            discoveredModels = models;
          }
          if (!cancelled) {
            setModelLabels(labels);
            setModelProfiles(enabledProfiles);
            setModelOptions(
              uniqueStrings([
                ...discoveredModels,
                ...profileModels,
                ...(effectiveSource === "system"
                  ? [settings.llm.effective_model, settings.llm.effective_complex_model]
                  : []),
              ])
            );
            setLlmReady(effectiveReady);
            setLlmSource(effectiveReady ? effectiveSource : "missing");
          }
        } catch (e) {
          console.warn("LLM model probe failed", e);
          if (!cancelled) {
            setLlmReady(false);
            setLlmSource("missing");
            setModelOptions([]);
            setModelLabels({});
            setModelProfiles([]);
          }
        }
      }

      try {
        const page = await listConversations({ page: 1, pageSize: CONVERSATION_PAGE_SIZE });
        if (cancelled) return;
        const list = page.items;
        setSummaries(list);
        setConversationTotal(page.total);
        setConversationPage(page.page);
        setConversationHasMore(page.has_more);
        const fallbackId = list[0]?.id ?? null;
        const targetId = routeConversationId ?? (startBlank ? null : fallbackId);
        if (targetId) {
          const ok = await loadConversation(targetId);
          if (cancelled) return;
          if (ok && !routeConversationId) {
            window.history.replaceState(null, "", conversationHref(targetId));
          } else if (!ok) {
            if (routeConversationId) {
              return;
            }
            const nextId = fallbackId && fallbackId !== targetId ? fallbackId : null;
            if (nextId) {
              window.history.replaceState(null, "", conversationHref(nextId));
              await loadConversation(nextId);
            } else {
              window.history.replaceState(null, "", "/");
            }
          }
        } else {
          clearActiveConversation();
        }
      } catch (e) {
        if (!cancelled) {
          console.error("list conversations failed", e);
          toast.error((e as Error)?.message ?? "加载会话历史失败");
        }
      } finally {
        if (!cancelled) setInitialLoadDone(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    clearActiveConversation,
    loadConversation,
    routeConversationId,
    router,
    setConversationHasMore,
    setConversationPage,
    setConversationTotal,
    setSummaries,
    startBlank,
  ]);

  useEffect(() => {
    if (!authChecked) return;
    listKbs().then(setKbs).catch(() => {});
  }, [authChecked]);

  useEffect(() => {
    if (!authChecked || !initialLoadDone) return;
    if (bootPhase !== "loading") return;
    setBootPhase("leaving");
    const timer = window.setTimeout(
      () => setBootPhase("gone"),
      prefersReducedMotion() ? 0 : CHAT_PANE_FADE_MS
    );
    return () => window.clearTimeout(timer);
  }, [authChecked, bootPhase, initialLoadDone]);

  return {
    user,
    setUser,
    authChecked,
    initialLoadDone,
    bootPhase,
    modelOptions,
    modelLabels,
    modelProfiles,
    setModelOptions,
    llmReady,
    llmSource,
    kbs,
    systemSettingsOpen,
    setSystemSettingsOpen,
  };
}
