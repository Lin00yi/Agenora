"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Box,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Circle,
  Copy,
  Database,
  HelpCircle,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  MessageCircle,
  Paperclip,
  Plus,
  Search,
  Send,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Square,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";

import Brand, { APP_NAME } from "@/components/Brand";
import type { ToolEvent } from "@/components/ThinkingChain";
import { getToken, getUser, logout, type User } from "@/lib/auth";
import { cn } from "@/lib/cn";
import {
  appendAssistantMessage,
  appendUserMessage,
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  migrateFromLocalStorage,
  patchConversation,
  type ConversationSummary,
  type MessagePayload,
} from "@/lib/conversations-api";
import {
  deriveTitle,
  genMessageId,
  type Conversation,
  type Message,
} from "@/lib/conversationStore";
import { listKbs, type KB } from "@/lib/kb-api";
import { connectChat, type ChatEvent, type ChatMessage } from "@/lib/sseClient";

const DEFAULT_TITLE = "新对话";
const EMPTY_PROMPTS = [
  "AnyKB 如何保证数据的安全性？是否支持本地部署和私有化？",
  "总结这个知识库最近上传资料的核心结论",
  "帮我找出权限配置和 BYOK 相关说明",
];

type SourceRow = {
  title: string;
  meta: string;
  score: string;
};

type ProcessStep = {
  title: string;
  description: string;
  status: "done" | "running" | "pending";
  active: boolean;
  time?: string;
};

type LlmSource = "user" | "system" | "missing";

function conversationHref(id: string) {
  return `/c/${encodeURIComponent(id)}`;
}

function conversationIdFromPath(pathname: string) {
  const match = pathname.match(/^\/c\/([^/]+)$/);
  return match ? decodeURIComponent(match[1]) : null;
}

function serverMsgToLocal(m: MessagePayload): Message {
  const ts = m.created_at ? new Date(m.created_at).getTime() : Date.now();
  if (m.role === "user") {
    return { id: m.id, role: "user", content: m.content, created_at: ts };
  }
  return {
    id: m.id,
    role: "assistant",
    content: m.content,
    tools: m.tools ?? [],
    cost_usd: m.cost_usd ?? undefined,
    error: m.error ?? undefined,
    created_at: ts,
  };
}

function summaryToConv(s: ConversationSummary, messages: Message[] = []): Conversation {
  const createdMs = s.created_at ? new Date(s.created_at).getTime() : Date.now();
  const updatedMs = s.updated_at ? new Date(s.updated_at).getTime() : createdMs;
  return {
    id: s.id,
    title: s.title,
    messages,
    kb_id: s.kb_id,
    llm_model: s.llm_model,
    created_at: createdMs,
    updated_at: updatedMs,
  };
}

export function ChatPage({ routeConversationId = null }: { routeConversationId?: string | null }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  const [summaries, setSummaries] = useState<ConversationSummary[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [currentMessages, setCurrentMessages] = useState<Message[]>([]);
  const [currentKbId, setCurrentKbId] = useState<string | null>(null);
  const [currentModel, setCurrentModel] = useState<string | null>(null);
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [llmReady, setLlmReady] = useState(false);
  const [llmSource, setLlmSource] = useState<LlmSource>("missing");
  const [kbs, setKbs] = useState<KB[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [composerValue, setComposerValue] = useState("");

  const messagesCache = useRef<Map<string, Message[]>>(new Map());
  const cleanupRef = useRef<(() => void) | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const streamingRef = useRef<{
    convId: string;
    msgId: string;
    content: string;
    tools: ToolEvent[];
  } | null>(null);

  const sidebarConversations = useMemo(
    () => summaries.map((s) => summaryToConv(s, s.id === currentId ? currentMessages : [])),
    [summaries, currentId, currentMessages]
  );

  const currentConversation = sidebarConversations.find((c) => c.id === currentId) ?? null;
  const currentKb = kbs.find((kb) => kb.id === currentKbId) ?? null;
  const activeAssistant = [...currentMessages].reverse().find((m) => m.role === "assistant");
  const activeTools = activeAssistant?.role === "assistant" ? activeAssistant.tools : [];
  const hasConversationMessages = currentMessages.length > 0;

  const loadConversation = useCallback(async (id: string) => {
    setCurrentId(id);
    const cached = messagesCache.current.get(id);
    if (cached) {
      setCurrentMessages(cached);
      setSummaries((cur) => {
        const found = cur.find((c) => c.id === id);
        if (found) {
          setCurrentKbId(found.kb_id);
          setCurrentModel(found.llm_model ?? null);
        }
        return cur;
      });
      return true;
    }
    try {
      const detail = await getConversation(id);
      const msgs = detail.messages.map(serverMsgToLocal);
      messagesCache.current.set(id, msgs);
      setCurrentMessages(msgs);
      setCurrentKbId(detail.kb_id);
      setCurrentModel(detail.llm_model ?? null);
      return true;
    } catch (e) {
      setCurrentId(null);
      setCurrentMessages([]);
      setCurrentKbId(null);
      setCurrentModel(null);
      toast.error("加载会话失败");
      return false;
      toast.error((e as Error)?.message ?? "加载会话失败");
    }
  }, []);

  const setMessagesForCurrent = useCallback(
    (next: Message[] | ((prev: Message[]) => Message[])) => {
      setCurrentMessages((prev) => {
        const resolved =
          typeof next === "function" ? (next as (p: Message[]) => Message[])(prev) : next;
        if (currentId) messagesCache.current.set(currentId, resolved);
        return resolved;
      });
    },
    [currentId]
  );

  const updateLastAssistant = useCallback(
    (mutator: (m: Message) => Message) => {
      setMessagesForCurrent((prev) => {
        const next = [...prev];
        for (let i = next.length - 1; i >= 0; i--) {
          if (next[i].role === "assistant") {
            next[i] = mutator(next[i]);
            break;
          }
        }
        return next;
      });
    },
    [setMessagesForCurrent]
  );

  const bumpSummary = useCallback(
    (
      convId: string,
      patch: Partial<ConversationSummary>,
      messageCountDelta: number = 0,
      moveToTop = false
    ) => {
      setSummaries((prev) => {
        const idx = prev.findIndex((c) => c.id === convId);
        if (idx === -1) return prev;
        const updated: ConversationSummary = {
          ...prev[idx],
          ...patch,
          message_count: Math.max(0, prev[idx].message_count + messageCountDelta),
          updated_at: new Date().toISOString(),
        };
        if (!moveToTop) {
          const next = [...prev];
          next[idx] = updated;
          return next;
        }
        return [updated, ...prev.slice(0, idx), ...prev.slice(idx + 1)];
      });
    },
    []
  );

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
          if (
            !cancelled &&
            settings.llm.configured &&
            settings.llm.provider &&
            settings.llm.base_url
          ) {
            setLlmReady(true);
            setLlmSource("user");
            const { models } = await probeLLM({
              provider: settings.llm.provider,
              base_url: settings.llm.base_url,
              api_key: "",
            });
            if (!cancelled) setModelOptions(models);
          } else if (!cancelled && effectiveReady && effectiveSource === "system") {
            setLlmReady(true);
            setLlmSource("system");
            setModelOptions(settings.llm.effective_model ? [settings.llm.effective_model] : []);
          } else if (!cancelled) {
            setLlmReady(false);
            setLlmSource("missing");
            setModelOptions([]);
          }
        } catch (e) {
          console.warn("LLM model probe failed", e);
          if (!cancelled) {
            setLlmReady(false);
            setLlmSource("missing");
            setModelOptions([]);
          }
        }
      }

      try {
        const list = await listConversations();
        if (cancelled) return;
        setSummaries(list);
        const fallbackId = list[0]?.id ?? null;
        const targetId = routeConversationId ?? fallbackId;
        if (targetId) {
          const ok = await loadConversation(targetId);
          if (cancelled) return;
          if (ok && !routeConversationId) {
            window.history.replaceState(null, "", conversationHref(targetId));
          } else if (!ok) {
            const nextId = fallbackId && fallbackId !== targetId ? fallbackId : null;
            if (nextId) {
              window.history.replaceState(null, "", conversationHref(nextId));
              await loadConversation(nextId);
            } else {
              window.history.replaceState(null, "", "/");
            }
          }
        } else {
          setCurrentId(null);
          setCurrentMessages([]);
          setCurrentKbId(null);
          setCurrentModel(null);
        }
      } catch (e) {
        if (!cancelled) {
          console.error("list conversations failed", e);
          toast.error((e as Error)?.message ?? "加载会话历史失败");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadConversation, routeConversationId, router]);

  useEffect(() => {
    if (!authChecked) return;
    listKbs().then(setKbs).catch(() => {});
  }, [authChecked]);

  useEffect(() => {
    if (!authChecked) return;
    const handlePopState = () => {
      const id = conversationIdFromPath(window.location.pathname);
      if (id) {
        void loadConversation(id);
      } else {
        setCurrentId(null);
        setCurrentMessages([]);
        setCurrentKbId(null);
        setCurrentModel(null);
      }
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [authChecked, loadConversation]);

  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [
    currentMessages.length,
    currentMessages[currentMessages.length - 1]?.role === "assistant"
      ? (currentMessages[currentMessages.length - 1] as Message & { content: string })?.content
          ?.length
      : 0,
  ]);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 112)}px`;
  }, [composerValue]);

  const handleNew = useCallback(async (kbId: string | null = currentKbId) => {
    try {
      const created = await createConversation({ kb_id: kbId });
      const summary: ConversationSummary = {
        id: created.id,
        title: created.title,
        kb_id: created.kb_id,
        llm_model: created.llm_model,
        message_count: 0,
        created_at: created.created_at,
        updated_at: created.updated_at,
      };
      setSummaries((prev) => [summary, ...prev]);
      setCurrentId(created.id);
      messagesCache.current.set(created.id, []);
      setCurrentMessages([]);
      setCurrentKbId(created.kb_id);
      setCurrentModel(created.llm_model ?? null);
      setSidebarOpen(false);
      window.history.pushState(null, "", conversationHref(created.id));
    } catch (e) {
      toast.error((e as Error)?.message ?? "新建对话失败");
    }
  }, [currentKbId, router]);

  const handleSelect = useCallback(
    async (id: string) => {
      setSidebarOpen(false);
      const ok = await loadConversation(id);
      if (ok) window.history.pushState(null, "", conversationHref(id));
    },
    [loadConversation, router]
  );

  const handleKbChange = useCallback(
    async (kbId: string | null) => {
      if (currentId && currentMessages.length > 0) {
        toast.info("当前会话的知识库已锁定，请新建对话后再切换。");
        return;
      }
      setCurrentKbId(kbId);
      if (!currentId) return;
      try {
        await patchConversation(currentId, { kb_id: kbId });
        setSummaries((prev) =>
          prev.map((c) => (c.id === currentId ? { ...c, kb_id: kbId } : c))
        );
      } catch (e) {
        toast.error((e as Error)?.message ?? "保存知识库绑定失败");
      }
    },
    [currentId, currentMessages.length]
  );

  const handleModelChange = useCallback(
    async (model: string | null) => {
      const prevModel = currentModel;
      setCurrentModel(model);
      if (!currentId) return;
      try {
        await patchConversation(currentId, { llm_model: model });
        setSummaries((prev) =>
          prev.map((c) => (c.id === currentId ? { ...c, llm_model: model } : c))
        );
      } catch (e) {
        setCurrentModel(prevModel);
        toast.error((e as Error)?.message ?? "保存模型选择失败");
      }
    },
    [currentId, currentModel]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteConversation(id);
      } catch (e) {
        toast.error((e as Error)?.message ?? "删除会话失败");
        return;
      }
      messagesCache.current.delete(id);
      const next = summaries.filter((c) => c.id !== id);
      setSummaries(next);
      if (currentId === id) {
        const newId = next[0]?.id ?? null;
        setCurrentId(newId);
        if (newId) {
          window.history.replaceState(null, "", conversationHref(newId));
          void loadConversation(newId);
        } else {
          setCurrentMessages([]);
          setCurrentKbId(null);
          setCurrentModel(null);
          window.history.replaceState(null, "", "/");
        }
      }
    },
    [currentId, loadConversation, router, summaries]
  );

  const handleLogout = useCallback(() => {
    cleanupRef.current?.();
    logout();
    router.replace("/login");
  }, [router]);

  const handleSend = useCallback(
    async (q: string) => {
      const trimmed = q.trim();
      if (!trimmed || busy) return;

      let convId = currentId;
      let isFreshConv = false;
      if (!convId) {
        try {
          const created = await createConversation({ kb_id: currentKbId });
          convId = created.id;
          isFreshConv = true;
          const summary: ConversationSummary = {
            id: created.id,
            title: created.title,
            kb_id: created.kb_id,
            llm_model: created.llm_model,
            message_count: 0,
            created_at: created.created_at,
            updated_at: created.updated_at,
          };
          setSummaries((prev) => [summary, ...prev]);
          setCurrentId(created.id);
          messagesCache.current.set(created.id, []);
          setCurrentMessages([]);
          setCurrentKbId(created.kb_id);
          setCurrentModel(created.llm_model ?? null);
          window.history.replaceState(null, "", conversationHref(created.id));
        } catch (e) {
          toast.error((e as Error)?.message ?? "创建会话失败");
          return;
        }
      }

      let userMsg: Message;
      try {
        const persisted = await appendUserMessage(convId!, trimmed);
        userMsg = serverMsgToLocal(persisted) as Message;
      } catch (e) {
        toast.error((e as Error)?.message ?? "保存消息失败");
        return;
      }

      const priorHistory: ChatMessage[] = currentMessages
        .filter((m) => {
          if (m.role === "user") return true;
          return !!m.content && !m.error && !m.streaming;
        })
        .map((m) => ({ role: m.role, content: m.content }));
      const messagesForBackend: ChatMessage[] = [
        ...priorHistory,
        { role: "user", content: trimmed },
      ];

      const aiId = genMessageId();
      const aiMsg: Message = {
        id: aiId,
        role: "assistant",
        content: "",
        tools: [],
        streaming: true,
        created_at: Date.now(),
      };
      setMessagesForCurrent((prev) => [...prev, userMsg, aiMsg]);
      streamingRef.current = {
        convId: convId!,
        msgId: aiId,
        content: "",
        tools: [],
      };

      const existing = summaries.find((c) => c.id === convId);
      bumpSummary(
        convId!,
        {
          title:
            isFreshConv || (existing?.message_count ?? 0) === 0
              ? deriveTitle(trimmed)
              : existing?.title ?? DEFAULT_TITLE,
        },
        1,
        true
      );

      setBusy(true);
      setComposerValue("");

      const persistFinal = async (opts: { error?: string; costUsd?: number }) => {
        const snap = streamingRef.current;
        streamingRef.current = null;
        if (!snap || snap.convId !== convId) return;
        try {
          const result = await appendAssistantMessage(snap.convId, {
            content: snap.content,
            tools: snap.tools,
            cost_usd: opts.costUsd,
            error: opts.error,
          });
          setMessagesForCurrent((prev) =>
            prev.map((m) => (m.id === snap.msgId ? { ...m, id: result.id } : m))
          );
          bumpSummary(snap.convId, {}, 1, true);
        } catch (e) {
          console.error("persist assistant failed", e);
          toast.error("助手回复保存失败，刷新后可能丢失");
        }
      };

      const cleanup = connectChat(
        messagesForBackend,
        (evt: ChatEvent) => {
          switch (evt.event) {
            case "tool_start": {
              const newTool: ToolEvent = {
                name: evt.name!,
                input: evt.input,
                status: "running",
                t0: Date.now(),
              };
              if (streamingRef.current) {
                streamingRef.current.tools = [...streamingRef.current.tools, newTool];
              }
              updateLastAssistant((m) =>
                m.role === "assistant" ? { ...m, tools: [...m.tools, newTool] } : m
              );
              break;
            }
            case "tool_end": {
              if (streamingRef.current) {
                const tools = [...streamingRef.current.tools];
                for (let i = tools.length - 1; i >= 0; i--) {
                  if (tools[i].name === evt.name && tools[i].status === "running") {
                    tools[i] = {
                      ...tools[i],
                      status: evt.ok ? "ok" : "error",
                      latency_ms: evt.latency_ms ?? null,
                      error: evt.error ?? null,
                    };
                    break;
                  }
                }
                streamingRef.current.tools = tools;
              }
              updateLastAssistant((m) => {
                if (m.role !== "assistant") return m;
                const tools = [...m.tools];
                for (let i = tools.length - 1; i >= 0; i--) {
                  if (tools[i].name === evt.name && tools[i].status === "running") {
                    tools[i] = {
                      ...tools[i],
                      status: evt.ok ? "ok" : "error",
                      latency_ms: evt.latency_ms ?? null,
                      error: evt.error ?? null,
                    };
                    break;
                  }
                }
                return { ...m, tools };
              });
              break;
            }
            case "tool_blocked": {
              const newTool: ToolEvent = {
                name: evt.name!,
                status: "blocked",
                reason: evt.reason ?? "",
              };
              if (streamingRef.current) {
                streamingRef.current.tools = [...streamingRef.current.tools, newTool];
              }
              updateLastAssistant((m) =>
                m.role === "assistant" ? { ...m, tools: [...m.tools, newTool] } : m
              );
              break;
            }
            case "token": {
              if (streamingRef.current) streamingRef.current.content += evt.text ?? "";
              updateLastAssistant((m) =>
                m.role === "assistant" ? { ...m, content: m.content + (evt.text ?? "") } : m
              );
              break;
            }
            case "error": {
              const errMsg = evt.message ?? "生成失败";
              updateLastAssistant((m) =>
                m.role === "assistant" ? { ...m, error: errMsg, streaming: false } : m
              );
              if (evt.code === "llm_not_configured" || evt.code === "embedding_not_configured") {
                toast.error(errMsg, {
                  action: {
                    label: "去配置",
                    onClick: () => router.push(evt.settings_url ?? "/settings"),
                  },
                });
              }
              void persistFinal({ error: errMsg });
              setBusy(false);
              cleanupRef.current = null;
              break;
            }
            case "done": {
              const costUsd = typeof evt.cost_usd === "number" ? evt.cost_usd : undefined;
              updateLastAssistant((m) =>
                m.role === "assistant" ? { ...m, streaming: false, cost_usd: costUsd } : m
              );
              void persistFinal({ costUsd });
              setBusy(false);
              cleanupRef.current = null;
              break;
            }
            default:
              break;
          }
        },
        { kbId: currentKbId, model: currentModel }
      );

      cleanupRef.current = cleanup;
    },
    [
      busy,
      currentId,
      currentKbId,
      currentMessages,
      currentModel,
      summaries,
      setMessagesForCurrent,
      updateLastAssistant,
      bumpSummary,
      router,
    ]
  );

  const handleStop = useCallback(() => {
    cleanupRef.current?.();
    cleanupRef.current = null;
    setBusy(false);
    updateLastAssistant((m) =>
      m.role === "assistant" && m.streaming
        ? { ...m, streaming: false, error: m.error ?? "用户已停止生成" }
        : m
    );
    const snap = streamingRef.current;
    if (snap) {
      streamingRef.current = null;
      void appendAssistantMessage(snap.convId, {
        content: snap.content,
        tools: snap.tools,
        error: "用户已停止生成",
      })
        .then((result) => {
          setMessagesForCurrent((prev) =>
            prev.map((m) => (m.id === snap.msgId ? { ...m, id: result.id } : m))
          );
          bumpSummary(snap.convId, {}, 1, true);
        })
        .catch((e) => console.error("persist stopped turn failed", e));
    }
  }, [updateLastAssistant, setMessagesForCurrent, bumpSummary]);

  const submitComposer = useCallback(() => {
    void handleSend(composerValue);
  }, [composerValue, handleSend]);

  if (!authChecked) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0b111b] text-slate-400">
        <div className="flex items-center gap-3 rounded-lg border border-white/10 bg-white/[0.03] px-4 py-3">
          <LoaderCircle className="h-4 w-4 animate-spin text-emerald-400" />
          正在加载 {APP_NAME}
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen w-screen overflow-hidden bg-[#08101c] text-slate-100">
      {sidebarOpen && (
        <button
          aria-label="关闭侧栏"
          className="fixed inset-0 z-30 bg-black/60 lg:hidden"
          onClick={() => setSidebarOpen(false)}
          type="button"
        />
      )}

      <div className="grid h-full grid-cols-1 lg:grid-cols-[286px_minmax(0,1fr)]">
        <DarkSidebar
          open={sidebarOpen}
          conversations={sidebarConversations}
          currentId={currentId}
          kbs={kbs}
          currentKbId={currentKbId}
          user={user}
          kbLocked={!!currentId && hasConversationMessages}
          onClose={() => setSidebarOpen(false)}
          onNew={handleNew}
          onSelectConversation={handleSelect}
          onDeleteConversation={handleDelete}
          onSelectKb={handleKbChange}
          onLogout={handleLogout}
        />

        <div className="flex h-[100dvh] max-h-[100dvh] min-h-0 min-w-0 flex-col overflow-hidden">
          <TopBar
            currentKb={currentKb}
            llmReady={llmReady}
            llmSource={llmSource}
            onOpenSidebar={() => setSidebarOpen(true)}
          />

          <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_338px]">
            <main className="flex min-h-0 min-w-0 flex-col border-r border-white/10 bg-[radial-gradient(circle_at_50%_0%,rgba(16,185,129,0.10),transparent_32%),linear-gradient(180deg,#0d1624,#08101c)]">
              <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
                <div className="mx-auto flex w-full max-w-[820px] flex-col gap-7">
                  {currentMessages.length === 0 ? (
                    <EmptyWorkbench
                      currentKbName={currentKb?.name ?? "通用对话"}
                      onPick={handleSend}
                    />
                  ) : (
                    currentMessages.map((message) => (
                      <DarkMessage key={message.id} message={message} user={user} />
                    ))
                  )}
                </div>
              </div>

              <Composer
                value={composerValue}
                textareaRef={textareaRef}
                busy={busy}
                currentKbName={currentKb?.name ?? "通用对话"}
                currentKbId={currentKbId}
                currentModel={currentModel}
                modelOptions={modelOptions}
                llmReady={llmReady}
                llmSource={llmSource}
                kbLocked={!!currentId && hasConversationMessages}
                onChange={setComposerValue}
                onSubmit={submitComposer}
                onStop={handleStop}
                onModelChange={handleModelChange}
              />
            </main>

            <RightInsightPanel
              currentKbName={currentKb?.name ?? "通用对话"}
              currentConversation={currentConversation}
              currentModel={currentModel}
              llmSource={llmSource}
              messages={currentMessages}
              tools={activeTools}
              busy={busy}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Page() {
  return <ChatPage />;
}

function DarkSidebar({
  open,
  conversations,
  currentId,
  kbs,
  currentKbId,
  user,
  kbLocked,
  onClose,
  onNew,
  onSelectConversation,
  onDeleteConversation,
  onSelectKb,
  onLogout,
}: {
  open: boolean;
  conversations: Conversation[];
  currentId: string | null;
  kbs: KB[];
  currentKbId: string | null;
  user: User | null;
  kbLocked: boolean;
  onClose: () => void;
  onNew: (kbId?: string | null) => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  onSelectKb: (id: string | null) => void;
  onLogout: () => void;
}) {
  const visibleKbs = kbs.length > 0 ? kbs.slice(0, 5) : [];
  const [searchTerm, setSearchTerm] = useState("");
  const [newMenuOpen, setNewMenuOpen] = useState(false);
  const filteredConversations = conversations.filter((conversation) =>
    conversation.title.toLowerCase().includes(searchTerm.trim().toLowerCase())
  );

  return (
    <aside
      className={cn(
        "fixed inset-y-0 left-0 z-40 flex w-[286px] flex-col border-r border-white/10 bg-[#0a121f]/98 px-3 py-4 shadow-2xl transition-transform lg:relative lg:z-auto lg:translate-x-0 lg:shadow-none",
        open ? "translate-x-0" : "-translate-x-full"
      )}
    >
      <div className="flex items-center justify-between px-2">
        <Brand className="text-white" size="md" />
        <button
          aria-label="关闭侧栏"
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-white/10 lg:hidden"
          onClick={onClose}
          type="button"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="relative mt-7">
        <div className="flex overflow-hidden rounded-lg border border-emerald-300/20 bg-emerald-400 text-sm font-medium text-white shadow-[0_10px_30px_rgba(16,185,129,0.22)]">
          <button
            className="flex h-11 flex-1 items-center justify-center gap-2 bg-gradient-to-r from-emerald-400 to-emerald-500"
            onClick={() => onNew(currentKbId)}
            type="button"
          >
            <Plus className="h-4 w-4" />
            新建对话
          </button>
          <button
            aria-expanded={newMenuOpen}
            aria-label="新建菜单"
            className="flex w-10 items-center justify-center border-l border-white/20 transition hover:bg-emerald-500"
            onClick={() => setNewMenuOpen((open) => !open)}
            type="button"
          >
            <ChevronDown className={cn("h-4 w-4 transition", newMenuOpen && "rotate-180")} />
          </button>
        </div>
        {newMenuOpen && (
          <div className="absolute left-0 right-0 top-12 z-20 overflow-hidden rounded-lg border border-white/10 bg-[#111c2b] p-1 text-sm text-slate-200 shadow-2xl">
            <button
              className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left transition hover:bg-white/[0.06]"
              onClick={() => {
                setNewMenuOpen(false);
                onNew(null);
              }}
              type="button"
            >
              <MessageCircle className="h-4 w-4 text-slate-400" />
              新建通用对话
            </button>
            <button
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left transition hover:bg-white/[0.06]",
                !currentKbId && "cursor-not-allowed opacity-45 hover:bg-transparent"
              )}
              disabled={!currentKbId}
              onClick={() => {
                if (!currentKbId) return;
                setNewMenuOpen(false);
                onNew(currentKbId);
              }}
              title={currentKbId ? "使用当前知识库新建对话" : "当前未绑定知识库"}
              type="button"
            >
              <Database className="h-4 w-4 text-emerald-300" />
              基于当前知识库新建
            </button>
          </div>
        )}
      </div>

      <div className="mt-4 flex h-9 items-center gap-2 rounded-lg border border-white/10 bg-black/20 px-3 text-sm text-slate-400 focus-within:border-emerald-300/35">
        <Search className="h-4 w-4" />
        <input
          className="min-w-0 flex-1 bg-transparent text-sm text-slate-200 outline-none placeholder:text-slate-500"
          value={searchTerm}
          onChange={(event) => setSearchTerm(event.target.value)}
          placeholder="搜索对话"
        />
        <kbd className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-slate-500">
          Ctrl K
        </kbd>
      </div>

      <button
        className="mt-2 flex h-10 w-full items-center gap-3 rounded-lg bg-white/[0.06] px-3 text-sm text-slate-100"
        onClick={() => setSearchTerm("")}
        type="button"
      >
        <MessageCircle className="h-4 w-4" />
        <span className="flex-1 text-left">全部对话</span>
        <span className="tabular-nums text-slate-500">{conversations.length}</span>
      </button>

      <div className="my-4 h-px bg-white/10" />

      <div className="flex items-center justify-between px-2 text-sm text-slate-400">
        <span>知识库</span>
        <Link
          href="/kbs"
          aria-label="添加知识库"
          className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-white/10"
        >
          <Plus className="h-4 w-4" />
        </Link>
      </div>

      <div className="mt-2 space-y-1">
        {visibleKbs.length > 0 ? (
          visibleKbs.map((item) => {
            const active = item.id === currentKbId;
            const locked = kbLocked;
            const count =
              item.chunks_count > 0
                ? item.chunks_count.toLocaleString()
                : item.documents_count.toLocaleString();
            return (
              <button
                key={item.id}
                disabled={locked}
                onClick={() => {
                  if (!locked) onSelectKb(item.id);
                }}
                title={locked ? "当前会话已锁定知识库，请新建对话后切换" : item.name}
                className={cn(
                  "flex h-10 w-full items-center gap-3 rounded-lg px-3 text-sm transition",
                  active
                    ? cn(
                        "bg-emerald-400/16 text-emerald-200 ring-1 ring-emerald-300/15",
                        locked && "cursor-not-allowed"
                      )
                    : locked
                    ? "cursor-not-allowed text-slate-600 opacity-55"
                    : "text-slate-400 hover:bg-white/[0.06] hover:text-slate-100"
                )}
                type="button"
              >
              <span
                className={cn(
                  "flex h-5 w-5 items-center justify-center rounded-md",
                  active ? "bg-emerald-400/20 text-emerald-300" : "bg-slate-700/60"
                )}
              >
                <Database className="h-3.5 w-3.5" />
              </span>
              <span className="min-w-0 flex-1 truncate text-left">{item.name}</span>
              {locked ? (
                <LockKeyhole className="h-3.5 w-3.5 text-slate-600" />
              ) : (
                <span className={active ? "text-emerald-300" : "text-slate-500"}>{count}</span>
              )}
              </button>
            );
          })
        ) : (
          <Link
            href="/kbs"
            className="block rounded-lg border border-dashed border-white/10 px-3 py-4 text-sm leading-6 text-slate-500 transition hover:border-emerald-300/30 hover:text-slate-300"
          >
            暂无知识库，去创建或上传资料
          </Link>
        )}
      </div>

      <Link
        href="/kbs"
        className="mt-3 flex h-10 items-center gap-2 rounded-lg px-3 text-sm text-slate-500 hover:bg-white/[0.06] hover:text-slate-200"
      >
        查看全部知识库
        <ChevronRight className="ml-auto h-4 w-4" />
      </Link>

      <div className="mt-3 min-h-0 flex-1 overflow-y-auto">
        <div className="px-2 pb-2 text-sm text-slate-400">最近对话</div>
        <div className="space-y-1">
          {filteredConversations.slice(0, 8).map((conversation) => (
            <div
              key={conversation.id}
              className={cn(
                "group flex h-9 items-center gap-2 rounded-lg px-3 text-sm transition",
                conversation.id === currentId
                  ? "bg-white/[0.08] text-slate-100"
                  : "text-slate-500 hover:bg-white/[0.06] hover:text-slate-200"
              )}
            >
              <button
                className="min-w-0 flex-1 truncate text-left"
                onClick={() => onSelectConversation(conversation.id)}
                type="button"
                title={conversation.title}
              >
                {conversation.title}
              </button>
              <button
                aria-label="删除会话"
                className="hidden h-7 w-7 items-center justify-center rounded-md text-slate-500 hover:bg-red-400/10 hover:text-red-300 group-hover:flex"
                onClick={() => {
                  if (window.confirm(`删除对话「${conversation.title}」？此操作不可恢复。`)) {
                    onDeleteConversation(conversation.id);
                  }
                }}
                type="button"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
          {filteredConversations.length === 0 && (
            <div className="rounded-lg border border-dashed border-white/10 px-3 py-4 text-sm text-slate-500">
              {searchTerm ? "没有匹配的对话。" : "还没有对话，先问一个问题。"}
            </div>
          )}
        </div>
      </div>

      <div className="mt-3 rounded-lg border border-white/10 bg-white/[0.04] p-3">
        <div className="flex items-center justify-between text-sm">
          <span className="flex items-center gap-2 text-slate-200">
            <ShieldCheck className="h-4 w-4 text-emerald-400" />
            企业版
          </span>
          <span className="text-xs text-emerald-300">已激活</span>
        </div>
        <div className="mt-2 text-xs text-slate-500">私有化部署 · BYOK</div>
      </div>

      <div className="mt-3 flex items-center justify-between rounded-lg border border-white/10 bg-black/20 p-2">
        <div className="flex min-w-0 items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-indigo-500 text-sm font-semibold text-white">
            {(user?.display_name?.[0] || user?.email?.[0] || "Z").toUpperCase()}
          </div>
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-slate-100">
              {user?.display_name || user?.email || "用户"}
            </div>
            <div className="text-xs text-slate-500">{user?.is_admin ? "管理员" : "成员"}</div>
          </div>
        </div>
        <button
          aria-label="退出登录"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-500 hover:bg-white/10 hover:text-slate-200"
          onClick={onLogout}
          type="button"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </aside>
  );
}

function TopBar({
  currentKb,
  llmReady,
  llmSource,
  onOpenSidebar,
}: {
  currentKb: KB | null;
  llmReady: boolean;
  llmSource: LlmSource;
  onOpenSidebar: () => void;
}) {
  const statusLabel = llmReady ? (llmSource === "system" ? "系统默认" : "就绪") : "待配置";
  const configLabel =
    llmSource === "user" ? "BYOK" : llmSource === "system" ? "系统模型" : "去配置";

  return (
    <header className="grid h-[72px] shrink-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 border-b border-white/10 bg-[#0b1422]/88 px-4 backdrop-blur-xl xl:px-7">
      <button
        className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-white/10 text-slate-300 lg:hidden"
        onClick={onOpenSidebar}
        type="button"
        aria-label="打开侧栏"
      >
        <ChevronLeft className="h-5 w-5 rotate-180" />
      </button>

      <div className="min-w-0">
        <div className="text-xs text-slate-500">当前会话知识库</div>
        <div className="mt-1 flex items-center gap-2 text-sm font-medium text-slate-100">
          <Database className="h-4 w-4 text-emerald-300" />
          <span className="truncate">{currentKb?.name ?? "通用对话"}</span>
        </div>
      </div>

      <div className="flex items-center justify-end gap-2">
        <Link
          href="/settings"
          className={cn(
            "hidden h-7 items-center gap-2 rounded-lg border px-3 text-sm sm:flex",
            llmReady
              ? "border-emerald-300/10 bg-emerald-400/12 text-emerald-300"
              : "border-amber-300/20 bg-amber-400/10 text-amber-200"
          )}
        >
          <span
            className={cn(
              "h-2 w-2 rounded-full",
              llmReady ? "bg-emerald-400" : "bg-amber-300"
            )}
          />
          {statusLabel}
        </Link>
        <Link
          className="hidden items-center gap-2 text-sm text-slate-400 transition hover:text-slate-100 sm:flex"
          href="/settings"
        >
          <LockKeyhole className="h-4 w-4" />
          {configLabel}
        </Link>
        <IconButton label="设置" href="/settings">
          <Settings className="h-5 w-5" />
        </IconButton>
        <IconButton label="帮助" href="/welcome">
          <HelpCircle className="h-5 w-5" />
        </IconButton>
      </div>
    </header>
  );
}

function IconButton({
  label,
  href,
  children,
}: {
  label: string;
  href?: string;
  children: ReactNode;
}) {
  const className =
    "inline-flex h-10 w-10 items-center justify-center rounded-lg text-slate-400 transition hover:bg-white/[0.06] hover:text-slate-100";
  if (href) {
    return (
      <Link href={href} aria-label={label} className={className}>
        {children}
      </Link>
    );
  }
  return (
    <button aria-label={label} className={className} type="button">
      {children}
    </button>
  );
}

function EmptyWorkbench({
  currentKbName,
  onPick,
}: {
  currentKbName: string;
  onPick: (q: string) => void;
}) {
  return (
    <div className="flex min-h-full items-center justify-center py-2">
      <section className="w-full max-w-[720px] rounded-lg border border-white/10 bg-[#111c2b]/72 p-5 shadow-[0_18px_46px_rgba(0,0,0,0.28)]">
        <div className="flex items-start gap-4">
          <Avatar label={<Box className="h-4 w-4" />} tone="assistant" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-emerald-300">已连接 {currentKbName}</div>
            <h1 className="mt-2 text-xl font-semibold tracking-tight text-slate-100 sm:text-2xl">
              向知识库提问，检索过程会实时展示
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
              这里不会预置假答案。发送问题后，中间区域会显示真实对话，右侧会根据工具调用展示检索、重排、生成状态。
            </p>
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <EmptyStat icon={<Database className="h-4 w-4" />} label="上下文" value={currentKbName} />
          <EmptyStat icon={<SlidersHorizontal className="h-4 w-4" />} label="检索模式" value="混合检索" />
          <EmptyStat icon={<ShieldCheck className="h-4 w-4" />} label="数据策略" value="BYOK / 私有化" />
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          {EMPTY_PROMPTS.map((item) => (
          <button
            className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-300 transition hover:border-emerald-300/40 hover:text-emerald-200"
            key={item}
            onClick={() => onPick(item)}
            type="button"
          >
            {item}
          </button>
        ))}
        </div>
      </section>
    </div>
  );
}

function EmptyStat({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/14 px-3 py-3">
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <span className="text-emerald-300">{icon}</span>
        {label}
      </div>
      <div className="mt-2 truncate text-sm font-medium text-slate-200" title={value}>
        {value}
      </div>
    </div>
  );
}

function DarkMessage({ message, user }: { message: Message; user: User | null }) {
  if (message.role === "user") {
    const userInitial = (user?.display_name?.[0] || user?.email?.[0] || "U").toUpperCase();
    return (
      <div className="flex items-start justify-end gap-3">
        <div className="flex max-w-[72%] flex-col items-end">
          <div className="rounded-lg border border-emerald-300/20 bg-emerald-400/14 px-5 py-3 text-[15px] leading-7 text-slate-100 shadow-[0_12px_34px_rgba(0,0,0,0.24)]">
            {message.content}
          </div>
          <div className="mt-2 text-xs text-slate-500">{formatMessageTime(message.created_at)}</div>
        </div>
        <Avatar label={userInitial} tone="user" />
      </div>
    );
  }

  const streaming = !!message.streaming;
  const hasContent = message.content.trim().length > 0;

  return (
    <div className="flex items-start gap-4">
      <Avatar label={<Box className="h-4 w-4" />} tone="assistant" />
      <div className="min-w-0 flex-1">
        <div className="rounded-lg border border-white/10 bg-[#111c2b]/78 px-5 py-4 shadow-[0_18px_46px_rgba(0,0,0,0.28)]">
          {message.error && (
            <div className="mb-3 rounded-lg border border-red-400/20 bg-red-400/10 px-3 py-2 text-sm text-red-200">
              {message.error}
            </div>
          )}
          {!hasContent && streaming && (
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <LoaderCircle className="h-4 w-4 animate-spin text-emerald-400" />
              正在检索并生成回答
            </div>
          )}
          {hasContent && <AnswerMarkdown markdown={message.content} streaming={streaming} />}
          {!hasContent && !streaming && !message.error && (
            <div className="text-sm text-slate-500">暂无内容</div>
          )}
          {hasContent && (
            <>
              <SourceStrip sources={buildMessageSources(message)} />
              <div className="mt-4 flex items-center gap-2 text-slate-500">
                <SmallAction
                  label="复制"
                  icon={<Copy className="h-4 w-4" />}
                  onClick={() => {
                    void navigator.clipboard.writeText(message.content);
                    toast.success("已复制回答");
                  }}
                />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function AnswerMarkdown({ markdown, streaming }: { markdown: string; streaming: boolean }) {
  return (
    <div className="text-[15px] leading-7 text-slate-300">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="mb-4 last:mb-0">{children}</p>,
          ul: ({ children }) => <ul className="mb-4 list-disc space-y-1 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="mb-4 list-decimal space-y-1 pl-5">{children}</ol>,
          li: ({ children }) => <li className="pl-1 marker:text-emerald-400">{children}</li>,
          strong: ({ children }) => <strong className="font-semibold text-slate-100">{children}</strong>,
          h1: ({ children }) => <h1 className="mb-3 text-xl font-semibold text-slate-100">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-3 mt-5 text-lg font-semibold text-slate-100">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-2 mt-4 text-base font-semibold text-slate-100">{children}</h3>,
          code: ({ children }) => (
            <code className="rounded bg-white/10 px-1.5 py-0.5 text-sm text-emerald-200">
              {children}
            </code>
          ),
        }}
      >
        {markdown.replace(/\\n/g, "\n")}
      </ReactMarkdown>
      {streaming && <span className="inline-block h-4 w-1.5 animate-pulse bg-emerald-400" />}
    </div>
  );
}

function SourceStrip({ sources }: { sources: SourceRow[] }) {
  if (sources.length === 0) return null;

  return (
    <div className="mt-5 rounded-lg border border-white/10 bg-black/14 p-2">
      <div className="mb-2 text-sm font-medium text-emerald-300">工具调用</div>
      <div className="grid gap-2 sm:grid-cols-2">
        {sources.map((source) => (
          <div
            className="flex min-w-0 items-center gap-2 rounded-md border border-white/10 bg-white/[0.04] px-2 py-2"
            key={source.title}
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-700/60 text-[10px] font-semibold text-slate-300">
              {source.score}
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs text-slate-200">{source.title}</div>
              <div className="truncate text-xs text-slate-500">{source.meta}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function buildMessageSources(message: Extract<Message, { role: "assistant" }>): SourceRow[] {
  if (message.tools.length === 0) return [];
  return message.tools.slice(0, 4).map((tool) => ({
    title: getToolLabel(tool.name),
    meta: tool.status === "running" ? "正在执行" : tool.status === "ok" ? "已完成" : "未完成",
    score:
      tool.status === "ok"
        ? "done"
        : tool.status === "running"
        ? "live"
        : tool.status === "blocked"
        ? "blocked"
        : "error",
  }));
}

function buildPanelSources(tools: ToolEvent[]): SourceRow[] {
  if (tools.length > 0) {
    return tools.slice(0, 6).map((tool) => ({
      title: getToolLabel(tool.name),
      meta:
        tool.status === "running"
          ? "正在执行"
          : tool.status === "ok"
          ? `已完成${tool.latency_ms ? ` · ${tool.latency_ms}ms` : ""}`
          : tool.status === "blocked"
          ? tool.reason || "已阻止"
          : tool.error || "执行失败",
      score:
        tool.status === "ok"
          ? "完成"
          : tool.status === "running"
          ? "实时"
          : tool.status === "blocked"
          ? "阻止"
          : "失败",
    }));
  }

  return [];
}

function getToolLabel(name: string): string {
  const labels: Record<string, string> = {
    search_kb: "知识库检索",
    generate_kb_report: "知识库报告生成",
    web_search: "网络搜索",
    get_weather: "天气查询",
    search_restaurant_kb: "本地知识检索",
    amap_search: "地图兜底搜索",
    generate_travel_report: "旅行报告生成",
  };
  return labels[name] ?? name;
}

function buildPanelSourcesClean(tools: ToolEvent[]): SourceRow[] {
  return tools.slice(0, 8).map((tool) => ({
    title: getToolLabelClean(tool.name),
    meta: getToolMetaClean(tool),
    score: getToolStatusLabelClean(tool.status),
  }));
}

function getToolLabelClean(name: string): string {
  const labels: Record<string, string> = {
    search_kb: "知识库检索",
    generate_kb_report: "知识库报告",
    web_search: "网络搜索",
    get_weather: "天气查询",
    search_restaurant_kb: "本地知识检索",
    amap_search: "地图兜底搜索",
    generate_travel_report: "旅行报告",
  };
  return labels[name] ?? name;
}

function getToolStatusLabelClean(status: ToolEvent["status"]) {
  if (status === "ok") return "完成";
  if (status === "running") return "进行中";
  if (status === "blocked") return "阻止";
  return "失败";
}

function getToolMetaClean(tool: ToolEvent) {
  if (tool.status === "running") return "正在执行";
  if (tool.status === "ok") {
    return tool.latency_ms ? `已完成 · ${formatDuration(tool.latency_ms)}` : "已完成";
  }
  if (tool.status === "blocked") return tool.reason || "调用被策略阻止";
  return normalizeToolError(tool.error);
}

function normalizeToolError(error?: string | null) {
  if (!error) return "调用失败";
  const lower = error.toLowerCase();
  if (lower.includes("timed out") || lower.includes("timeout")) {
    return "请求超时，已跳过该结果";
  }
  if (lower.includes("network") || lower.includes("fetch") || lower.includes("request")) {
    return "网络请求失败，已跳过该结果";
  }
  return error.length > 48 ? `${error.slice(0, 48)}...` : error;
}

function formatDuration(ms: number) {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

function describeToolSummary(tools: ToolEvent[]) {
  if (tools.length === 0) return "本轮未调用检索工具";
  const counts = new Map<string, number>();
  for (const tool of tools) {
    const label = getToolLabelClean(tool.name);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([label, count]) => (count > 1 ? `${label} x${count}` : label))
    .join("、");
}

function Avatar({ label, tone }: { label: ReactNode; tone: "user" | "assistant" }) {
  return (
    <div
      className={cn(
        "flex h-9 w-9 shrink-0 items-center justify-center rounded-full font-semibold shadow-lg",
        tone === "user"
          ? "bg-emerald-400 text-white"
          : "border border-emerald-300/30 bg-emerald-400/10 text-emerald-300"
      )}
    >
      {label}
    </div>
  );
}

function SmallAction({
  label,
  icon,
  disabled = false,
  onClick,
}: {
  label: string;
  icon?: ReactNode;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      className={cn(
        "inline-flex h-7 min-w-7 items-center justify-center rounded-md px-1.5 text-xs transition",
        disabled
          ? "cursor-not-allowed opacity-45"
          : "hover:bg-white/10 hover:text-slate-200"
      )}
      disabled={disabled}
      onClick={onClick}
      title={disabled ? `${label}暂未接入` : label}
      type="button"
    >
      {icon ?? <Circle className="h-3.5 w-3.5" />}
    </button>
  );
}

function Composer({
  value,
  textareaRef,
  busy,
  currentKbName,
  currentKbId,
  currentModel,
  modelOptions,
  llmReady,
  llmSource,
  kbLocked,
  onChange,
  onSubmit,
  onStop,
  onModelChange,
}: {
  value: string;
  textareaRef: React.RefObject<HTMLTextAreaElement>;
  busy: boolean;
  currentKbName: string;
  currentKbId: string | null;
  currentModel: string | null;
  modelOptions: string[];
  llmReady: boolean;
  llmSource: LlmSource;
  kbLocked: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  onModelChange: (model: string | null) => void;
}) {
  const defaultModelLabel = llmReady
    ? llmSource === "system"
      ? "系统默认模型"
      : "默认模型"
    : "未配置模型";

  return (
    <div className="shrink-0 border-t border-white/10 bg-[#08101c]/90 px-5 py-3 backdrop-blur-xl">
      <div className="mx-auto max-w-[820px] rounded-lg border border-white/12 bg-[#0d1726]/94 shadow-[0_18px_46px_rgba(0,0,0,0.32)] focus-within:border-emerald-300/40">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              onSubmit();
            }
          }}
          rows={1}
          aria-label="输入消息"
          data-testid="composer-input"
          placeholder="向当前会话提问，知识库会随会话锁定"
          className="block max-h-[112px] min-h-[44px] w-full resize-none bg-transparent px-4 py-3 text-[15px] leading-6 text-slate-100 outline-none placeholder:text-slate-500"
        />
        <div className="flex flex-wrap items-center gap-2 border-t border-white/8 px-3 py-2">
          <div
            className="inline-flex h-9 max-w-[220px] items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-slate-300"
            title={kbLocked ? "当前会话已锁定知识库，新建对话后可切换" : "当前会话知识库"}
          >
            <Database className="h-4 w-4 text-emerald-300" />
            <span className="truncate">{currentKbName}</span>
            {kbLocked && <LockKeyhole className="h-3.5 w-3.5 text-slate-500" />}
          </div>
          <Link
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-slate-300 transition hover:bg-white/[0.08]"
            href={currentKbId ? `/kbs/${currentKbId}` : "/kbs"}
            aria-label={currentKbId ? "打开知识库上传资料" : "选择知识库后上传资料"}
            title={currentKbId ? "打开知识库上传资料" : "选择知识库后上传资料"}
          >
            <Paperclip className="h-4 w-4" />
          </Link>
          <select
            className="ml-auto h-9 max-w-[190px] rounded-lg border border-white/10 bg-[#111c2b] px-3 text-sm text-slate-200 outline-none transition focus:border-emerald-300/40 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={busy || modelOptions.length === 0}
            value={currentModel ?? ""}
            onChange={(e) => onModelChange(e.target.value || null)}
            title={modelOptions.length > 0 ? "模型选择" : "请先在设置中配置模型"}
          >
            <option value="">{defaultModelLabel}</option>
            {modelOptions.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
          <Link
            href="/settings"
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-slate-300 transition hover:bg-white/[0.08]"
            title="检索与模型设置"
          >
            <SlidersHorizontal className="h-4 w-4 text-indigo-300" />
            混合检索
          </Link>
          {busy ? (
            <button
              className="inline-flex h-10 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.06] px-4 text-sm font-medium text-slate-100 hover:bg-white/10"
              aria-label="停止生成"
              data-testid="composer-stop"
              onClick={onStop}
              type="button"
            >
              <Square className="h-3.5 w-3.5 fill-current" />
              停止
            </button>
          ) : (
            <button
              className="inline-flex h-10 items-center gap-2 rounded-lg bg-emerald-400 px-4 text-sm font-medium text-white shadow-[0_10px_24px_rgba(16,185,129,0.28)] transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-45"
              aria-label="发送消息"
              data-testid="composer-send"
              disabled={!value.trim()}
              onClick={onSubmit}
              title="发送消息"
              type="button"
            >
              <Send className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
      <p className="mt-2 text-center text-xs text-slate-500">内容由 AI 生成，请仔细甄别</p>
    </div>
  );
}

function RightInsightPanel({
  currentKbName,
  currentConversation,
  currentModel,
  llmSource,
  messages,
  tools,
  busy,
}: {
  currentKbName: string;
  currentConversation: Conversation | null;
  currentModel: string | null;
  llmSource: LlmSource;
  messages: Message[];
  tools: ToolEvent[];
  busy: boolean;
}) {
  const steps = deriveStepsClean(tools, busy, messages);
  const panelSources = buildPanelSourcesClean(tools);
  const messageStats = formatMessageStats(messages);
  const modelLabel = currentModel || (llmSource === "system" ? "系统默认" : llmSource === "user" ? "默认模型" : "未配置");

  return (
    <aside className="hidden min-w-0 flex-col overflow-y-auto bg-[#0a121f] lg:flex">
      <section className="border-b border-white/10 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-100">检索与推理过程</h2>
          <span className="text-xs text-slate-500">只读状态</span>
        </div>
        <div className="mt-5 space-y-0">
          {steps.map((step, index) => (
            <div className="relative flex gap-3 pb-5 last:pb-0" key={step.title}>
              {index < steps.length - 1 && (
                <span className="absolute left-[7px] top-5 h-full w-px bg-white/10" />
              )}
              <span
                className={cn(
                  "relative z-10 mt-0.5 flex h-4 w-4 items-center justify-center rounded-full border",
                  step.status === "done" && "border-emerald-400 bg-emerald-400/15",
                  step.status === "running" && "border-emerald-400 bg-[#0a121f]",
                  step.status === "pending" && "border-slate-600 bg-[#0a121f]"
                )}
              >
                {step.status === "done" && <Check className="h-3 w-3 text-emerald-300" />}
                {step.status === "running" && (
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />
                )}
              </span>
              <div
                className={cn(
                  "flex-1 rounded-lg px-3 py-2",
                  step.active && "border border-emerald-300/40 bg-emerald-400/8"
                )}
              >
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium text-slate-200">{step.title}</span>
                  {step.status === "done" && <CheckCircle2 className="h-4 w-4 text-emerald-400" />}
                </div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{step.description}</div>
                {step.time && <div className="mt-1 text-xs text-slate-500">{step.time}</div>}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="border-b border-white/10 p-5">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold text-slate-100">工具调用记录</h2>
          <span className="rounded-full bg-white/10 px-2 py-0.5 text-xs text-slate-400">
            {panelSources.length}
          </span>
        </div>
        {panelSources.length > 0 ? (
          <>
            <div className="mt-4 overflow-hidden rounded-lg border border-white/10">
              {panelSources.map((source) => (
                <div
                  className="flex items-center gap-3 border-b border-white/8 px-3 py-3 last:border-b-0"
                  key={`${source.title}-${source.meta}`}
                >
                  <span className="flex h-7 min-w-10 shrink-0 items-center justify-center rounded-md bg-slate-700/60 px-1.5 text-[10px] font-semibold text-slate-300">
                    {source.score}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-slate-200">
                      {source.title}
                    </div>
                    <div className="text-xs text-slate-500">{source.meta}</div>
                  </div>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="mt-4 rounded-lg border border-dashed border-white/10 px-3 py-5 text-sm leading-6 text-slate-500">
            暂无工具调用。发送问题后，如果后端返回检索、重排或其他工具事件，这里会实时更新。
          </div>
        )}
      </section>

      <section className="flex-1 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-100">会话信息</h2>
          {currentConversation?.id && (
            <button
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-white/10 px-2 text-xs text-slate-400 transition hover:border-emerald-300/40 hover:text-emerald-200"
              onClick={() => {
                void navigator.clipboard.writeText(currentConversation.id);
                toast.success("已复制会话 ID");
              }}
              type="button"
            >
              <Copy className="h-3.5 w-3.5" />
              复制 ID
            </button>
          )}
        </div>
        <dl className="mt-5 space-y-4 text-sm">
          <InfoRow
            label="会话 ID"
            value={currentConversation?.id.slice(0, 8) ?? "-"}
            title={currentConversation?.id}
          />
          <InfoRow label="创建时间" value={formatTime(currentConversation?.created_at)} />
          <InfoRow label="最近更新" value={formatTime(currentConversation?.updated_at)} />
          <InfoRow label="消息统计" value={messageStats} />
          <InfoRow
            label="知识库"
            value={
              currentConversation?.kb_id ? (
                <Link
                  className="truncate text-right text-emerald-200 transition hover:text-emerald-100"
                  href={`/kbs/${currentConversation.kb_id}`}
                  title={currentKbName}
                >
                  {currentKbName}
                </Link>
              ) : (
                "通用对话"
              )
            }
          />
          <InfoRow label="模型" value={modelLabel} />
        </dl>
      </section>

      <section className="hidden">
        <h2 className="text-base font-semibold text-slate-100">会话信息</h2>
        <dl className="mt-5 space-y-4 text-sm">
          <InfoRow label="会话 ID" value={currentConversation?.id.slice(0, 8) ?? "-"} />
          <InfoRow label="创建时间" value={formatTime(currentConversation?.created_at)} />
          <InfoRow label="消息数" value={String(messages.length)} />
          <InfoRow label="知识库" value={currentKbName} />
        </dl>
      </section>
    </aside>
  );
}

function deriveStepsClean(tools: ToolEvent[], busy: boolean, messages: Message[]): ProcessStep[] {
  const hasMessages = messages.length > 0;
  const lastAssistant = [...messages].reverse().find((message) => message.role === "assistant");
  const hasAssistantAnswer =
    lastAssistant?.role === "assistant" && Boolean(lastAssistant.content.trim());
  const hasRunning = tools.some((tool) => tool.status === "running");
  const hasToolFailures = tools.some((tool) => tool.status === "error" || tool.status === "blocked");

  if (!hasMessages) {
    return [
      {
        title: "等待提问",
        description: "输入问题后开始分析意图",
        status: "pending",
        active: false,
      },
      {
        title: "检索知识",
        description: "绑定知识库时执行混合检索",
        status: "pending",
        active: false,
      },
      {
        title: "重排结果",
        description: "有检索结果时进行相关性排序",
        status: "pending",
        active: false,
      },
      {
        title: "生成回答",
        description: "检索完成后生成最终回答",
        status: "pending",
        active: false,
      },
    ];
  }

  const retrievalStatus = hasRunning ? "running" : tools.length > 0 ? "done" : "pending";
  const rerankStatus = hasRunning ? "pending" : tools.length > 0 ? "done" : "pending";
  const answerStatus = busy ? "running" : hasAssistantAnswer ? "done" : "pending";

  return [
    {
      title: "理解问题",
      description: "分析用户问题，识别关键意图",
      status: "done",
      active: false,
    },
    {
      title: "检索知识",
      description:
        tools.length > 0
          ? `${describeToolSummary(tools)}${hasToolFailures ? "，部分调用失败" : ""}`
          : "本轮未返回结构化检索事件",
      status: retrievalStatus,
      active: retrievalStatus === "running",
    },
    {
      title: "重排结果",
      description:
        tools.length > 0
          ? "已整理可用检索结果"
          : "无可展示的重排结果",
      status: rerankStatus,
      active: false,
    },
    {
      title: "生成回答",
      description: busy
        ? "正在生成最终回答"
        : hasAssistantAnswer
        ? "回答已写入当前会话"
        : "等待模型返回回答",
      status: answerStatus,
      active: answerStatus === "running",
    },
  ];
}

function deriveSteps(tools: ToolEvent[], busy: boolean, messages: Message[]): ProcessStep[] {
  const hasMessages = messages.length > 0;
  const lastAssistant = [...messages].reverse().find((message) => message.role === "assistant");
  const hasAssistantAnswer =
    lastAssistant?.role === "assistant" && Boolean(lastAssistant.content.trim());
  const hasRunning = tools.some((tool) => tool.status === "running");
  const hasErrors = tools.some((tool) => tool.status === "error" || tool.status === "blocked");

  if (!hasMessages) {
    return [
      {
        title: "等待提问",
        description: "输入问题后开始分析意图",
        status: "pending",
        active: false,
      },
      {
        title: "检索知识",
        description: "绑定知识库时执行混合检索",
        status: "pending",
        active: false,
      },
      {
        title: "重排结果",
        description: "有检索结果时进行相关性排序",
        status: "pending",
        active: false,
      },
      {
        title: "生成回答",
        description: "检索完成后生成可引用的回答",
        status: "pending",
        active: false,
      },
    ];
  }

  if (tools.length > 0) {
    const hasRunning = tools.some((tool) => tool.status === "running");
    return [
      {
        title: "理解问题",
        description: "分析用户问题，识别关键意图",
        status: "done" as const,
        active: false,
      },
      {
        title: "检索知识",
        description: tools.map((tool) => tool.name).join("、") || "执行混合检索",
        status: hasRunning ? ("running" as const) : ("done" as const),
        active: hasRunning,
      },
      {
        title: "重排结果",
        description: "对检索结果进行相关性重排",
        status: hasRunning ? ("pending" as const) : ("done" as const),
        active: !hasRunning && busy,
      },
      {
        title: "生成回答",
        description: "基于检索结果生成最终回答",
        status: busy ? ("running" as const) : ("pending" as const),
        active: busy,
      },
    ];
  }
  if (busy) {
    return [
      {
        title: "理解问题",
        description: "正在分析用户问题",
        status: "running" as const,
        active: true,
      },
      {
        title: "检索知识",
        description: "等待后端返回检索事件",
        status: "pending" as const,
        active: false,
      },
      {
        title: "重排结果",
        description: "等待检索结果",
        status: "pending" as const,
        active: false,
      },
      {
        title: "生成回答",
        description: "准备生成最终回答",
        status: "pending" as const,
        active: false,
      },
    ];
  }
  return [
    {
      title: "理解问题",
      description: "分析用户问题，识别关键意图",
      status: "done" as const,
      active: false,
    },
    {
      title: "检索知识",
      description: "本轮未返回结构化检索事件",
      status: "pending" as const,
      active: false,
    },
    {
      title: "重排结果",
      description: "无可展示的重排结果",
      status: "pending" as const,
      active: false,
    },
    {
      title: "生成回答",
      description: "回答已写入当前会话",
      status: "done" as const,
      active: false,
    },
  ];
}

function InfoRow({
  label,
  value,
  title,
}: {
  label: string;
  value: ReactNode;
  title?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-slate-500">{label}</dt>
      <dd className="min-w-0 truncate text-right text-slate-300" title={title}>
        {value}
      </dd>
    </div>
  );
}

function formatMessageStats(messages: Message[]) {
  const userCount = messages.filter((message) => message.role === "user").length;
  const assistantCount = messages.filter((message) => message.role === "assistant").length;
  return `${userCount} 轮 · ${messages.length} 条`;
}

function formatTime(value?: number | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(value);
}

function formatMessageTime(value?: number | null) {
  if (!value) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(value);
}
