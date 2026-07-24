"use client";

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  Suspense,
  type ReactNode,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ThemeToggle from "@/components/ThemeToggle";
import {
  Box,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
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
  Shield,
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
  getConversationContextStatus,
  listConversations,
  migrateFromLocalStorage,
  patchConversation,
  type ConversationContextStatus,
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

const DEFAULT_TITLE = "\u65b0\u5bf9\u8bdd";
const EMPTY_PROMPTS = [
  "AnyKB \u5982\u4f55\u4fdd\u8bc1\u6570\u636e\u7684\u5b89\u5168\u6027\uff1f\u662f\u5426\u652f\u6301\u672c\u5730\u90e8\u7f72\u548c\u79c1\u6709\u5316\uff1f",
  "\u603b\u7ed3\u8fd9\u4e2a\u77e5\u8bc6\u5e93\u6700\u8fd1\u4e0a\u4f20\u8d44\u6599\u7684\u6838\u5fc3\u7ed3\u8bba",
  "\u5e2e\u6211\u627e\u51fa\u6743\u9650\u914d\u7f6e\u548c BYOK \u76f8\u5173\u8bf4\u660e",
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

const CONVERSATION_PAGE_SIZE = 30;

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
    message_count: s.message_count,
    created_at: createdMs,
    updated_at: updatedMs,
  };
}

function mergeConversationSummaries(
  current: ConversationSummary[],
  incoming: ConversationSummary[]
) {
  const seen = new Set<string>();
  return [...current, ...incoming].filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
}

function ChatPage({ routeConversationId = null }: { routeConversationId?: string | null }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  const [summaries, setSummaries] = useState<ConversationSummary[]>([]);
  const [conversationTotal, setConversationTotal] = useState(0);
  const [conversationPage, setConversationPage] = useState(1);
  const [conversationHasMore, setConversationHasMore] = useState(false);
  const [conversationLoadingMore, setConversationLoadingMore] = useState(false);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [currentMessages, setCurrentMessages] = useState<Message[]>([]);
  const [currentKbId, setCurrentKbId] = useState<string | null>(null);
  const [currentModel, setCurrentModel] = useState<string | null>(null);
  const [currentContextStatus, setCurrentContextStatus] =
    useState<ConversationContextStatus | null>(null);
  const [contextStatusLoading, setContextStatusLoading] = useState(false);
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
    setContextStatusLoading(true);
    const cached = messagesCache.current.get(id);
    if (cached) {
      setCurrentMessages(cached);
      setSummaries((cur) => {
        const found = cur.find((c) => c.id === id);
        if (found) {
          setCurrentKbId(found.kb_id);
          setCurrentModel(found.llm_model ?? null);
          setCurrentContextStatus(found.context_status ?? null);
        }
        return cur;
      });
      getConversationContextStatus(id)
        .then((status) => {
          setCurrentContextStatus(status);
          setSummaries((cur) =>
            cur.map((item) =>
              item.id === id ? { ...item, context_status: status } : item
            )
          );
        })
        .catch(() => {
          /* best-effort status refresh */
        })
        .finally(() => {
          setContextStatusLoading(false);
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
      setCurrentContextStatus(detail.context_status ?? null);
      setSummaries((prev) => {
        const summary: ConversationSummary = {
          id: detail.id,
          title: detail.title,
          kb_id: detail.kb_id,
          llm_model: detail.llm_model,
          message_count: detail.message_count,
          created_at: detail.created_at,
          updated_at: detail.updated_at,
          context_status: detail.context_status ?? null,
        };
        if (prev.some((item) => item.id === detail.id)) {
          return prev.map((item) => (item.id === detail.id ? { ...item, ...summary } : item));
        }
        return [summary, ...prev];
      });
      getConversationContextStatus(id)
        .then((status) => {
          setCurrentContextStatus(status);
          setSummaries((prev) =>
            prev.map((item) =>
              item.id === id ? { ...item, context_status: status } : item
            )
          );
        })
        .catch(() => {
          /* Keep the detail payload when the dedicated refresh is unavailable. */
        })
        .finally(() => {
          setContextStatusLoading(false);
        });
      return true;
    } catch (e) {
      setCurrentId(null);
      setCurrentMessages([]);
      setCurrentKbId(null);
      setCurrentModel(null);
      setCurrentContextStatus(null);
      setContextStatusLoading(false);
      toast.error((e as Error)?.message ?? "\u52a0\u8f7d\u4f1a\u8bdd\u5931\u8d25");
      return false;
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
            toast.success(`\u5df2\u4ece\u672c\u5730\u6062\u590d ${imported} \u6761\u5386\u53f2\u5bf9\u8bdd`);
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
        const page = await listConversations({ page: 1, pageSize: CONVERSATION_PAGE_SIZE });
        if (cancelled) return;
        const list = page.items;
        setSummaries(list);
        setConversationTotal(page.total);
        setConversationPage(page.page);
        setConversationHasMore(page.has_more);
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
          setCurrentContextStatus(null);
        }
      } catch (e) {
        if (!cancelled) {
          console.error("list conversations failed", e);
          toast.error((e as Error)?.message ?? "\u52a0\u8f7d\u4f1a\u8bdd\u5386\u53f2\u5931\u8d25");
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
        setCurrentContextStatus(null);
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

  const loadMoreConversations = useCallback(async () => {
    if (conversationLoadingMore || !conversationHasMore) return;
    setConversationLoadingMore(true);
    try {
      const nextPage = conversationPage + 1;
      const page = await listConversations({
        page: nextPage,
        pageSize: CONVERSATION_PAGE_SIZE,
      });
      setSummaries((prev) => mergeConversationSummaries(prev, page.items));
      setConversationTotal(page.total);
      setConversationPage(page.page);
      setConversationHasMore(page.has_more);
    } catch (e) {
      toast.error((e as Error)?.message ?? "\u52a0\u8f7d\u66f4\u591a\u5bf9\u8bdd\u5931\u8d25");
    } finally {
      setConversationLoadingMore(false);
    }
  }, [conversationHasMore, conversationLoadingMore, conversationPage]);

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
        context_status: created.context_status ?? null,
      };
      setSummaries((prev) => [summary, ...prev]);
      setConversationTotal((total) => total + 1);
      setCurrentId(created.id);
      messagesCache.current.set(created.id, []);
      setCurrentMessages([]);
      setCurrentKbId(created.kb_id);
      setCurrentModel(created.llm_model ?? null);
      setCurrentContextStatus(created.context_status ?? null);
      setSidebarOpen(false);
      window.history.pushState(null, "", conversationHref(created.id));
    } catch (e) {
      toast.error((e as Error)?.message ?? "\u65b0\u5efa\u5bf9\u8bdd\u5931\u8d25");
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
        toast.info("\u5f53\u524d\u4f1a\u8bdd\u7684\u77e5\u8bc6\u5e93\u5df2\u9501\u5b9a\uff0c\u8bf7\u65b0\u5efa\u5bf9\u8bdd\u540e\u518d\u5207\u6362\u3002");
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
        toast.error((e as Error)?.message ?? "\u4fdd\u5b58\u77e5\u8bc6\u5e93\u7ed1\u5b9a\u5931\u8d25");
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
        toast.error((e as Error)?.message ?? "\u4fdd\u5b58\u6a21\u578b\u9009\u62e9\u5931\u8d25");
      }
    },
    [currentId, currentModel]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteConversation(id);
      } catch (e) {
        toast.error((e as Error)?.message ?? "\u5220\u9664\u4f1a\u8bdd\u5931\u8d25");
        return;
      }
      messagesCache.current.delete(id);
      const next = summaries.filter((c) => c.id !== id);
      setSummaries(next);
      setConversationTotal((total) => Math.max(0, total - 1));
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
          setCurrentContextStatus(null);
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
          context_status: created.context_status ?? null,
        };
          setSummaries((prev) => [summary, ...prev]);
          setConversationTotal((total) => total + 1);
          setCurrentId(created.id);
          messagesCache.current.set(created.id, []);
          setCurrentMessages([]);
          setCurrentKbId(created.kb_id);
          setCurrentModel(created.llm_model ?? null);
          setCurrentContextStatus(created.context_status ?? null);
          window.history.replaceState(null, "", conversationHref(created.id));
        } catch (e) {
          toast.error((e as Error)?.message ?? "\u521b\u5efa\u4f1a\u8bdd\u5931\u8d25");
          return;
        }
      }

      let userMsg: Message;
      try {
        const persisted = await appendUserMessage(convId!, trimmed);
        userMsg = serverMsgToLocal(persisted) as Message;
      } catch (e) {
        toast.error((e as Error)?.message ?? "\u4fdd\u5b58\u6d88\u606f\u5931\u8d25");
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
          getConversationContextStatus(snap.convId)
            .then((status) => {
              setCurrentContextStatus(status);
              setSummaries((prev) =>
                prev.map((item) =>
                  item.id === snap.convId ? { ...item, context_status: status } : item
                )
              );
            })
            .catch(() => {
              /* best-effort status refresh */
            });
        } catch (e) {
          console.error("persist assistant failed", e);
          toast.error("\u52a9\u624b\u56de\u590d\u4fdd\u5b58\u5931\u8d25\uff0c\u5237\u65b0\u540e\u53ef\u80fd\u4e22\u5931");
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
              const errMsg = evt.message ?? "\u751f\u6210\u5931\u8d25";
              updateLastAssistant((m) =>
                m.role === "assistant" ? { ...m, error: errMsg, streaming: false } : m
              );
              if (evt.code === "llm_not_configured" || evt.code === "embedding_not_configured") {
                toast.error(errMsg, {
                  action: {
                    label: "\u53bb\u914d\u7f6e",
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
        { conversationId: convId!, kbId: currentKbId, model: currentModel }
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
        ? { ...m, streaming: false, error: m.error ?? "\u7528\u6237\u5df2\u505c\u6b62\u751f\u6210" }
        : m
    );
    const snap = streamingRef.current;
    if (snap) {
      streamingRef.current = null;
      void appendAssistantMessage(snap.convId, {
        content: snap.content,
        tools: snap.tools,
        error: "\u7528\u6237\u5df2\u505c\u6b62\u751f\u6210",
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
      <div className="ak-chat flex min-h-screen items-center justify-center bg-[#0b111b] text-slate-400">
        <div className="flex items-center gap-3 rounded-lg border border-white/10 bg-white/[0.03] px-4 py-3">
          <LoaderCircle className="h-4 w-4 animate-spin text-emerald-400" />
          {"\u6b63\u5728\u52a0\u8f7d "}{APP_NAME}
        </div>
      </div>
    );
  }

  return (
    <div className="ak-chat h-screen w-screen overflow-hidden bg-[#08101c] text-slate-100">
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
          conversationTotal={conversationTotal}
          conversationHasMore={conversationHasMore}
          conversationLoadingMore={conversationLoadingMore}
          currentId={currentId}
          currentKbId={currentKbId}
          user={user}
          busy={busy}
          onClose={() => setSidebarOpen(false)}
          onNew={handleNew}
          onSelectConversation={handleSelect}
          onDeleteConversation={handleDelete}
          onLoadMoreConversations={loadMoreConversations}
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
            <main className="ak-main flex min-h-0 min-w-0 flex-col border-r border-white/10 bg-[radial-gradient(circle_at_50%_0%,rgba(16,185,129,0.10),transparent_32%),linear-gradient(180deg,#0d1624,#08101c)]">
              <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
                <div className="mx-auto flex w-full max-w-[820px] flex-col gap-7">
                  <ContextCompressionNotice contextStatus={currentContextStatus} />
                  {currentMessages.length === 0 ? (
                    <EmptyWorkbench
                      currentKbName={currentKb?.name ?? "\u901a\u7528\u5bf9\u8bdd"}
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
                currentKbId={currentKbId}
                kbs={kbs}
                currentModel={currentModel}
                modelOptions={modelOptions}
                llmReady={llmReady}
                llmSource={llmSource}
                contextStatus={currentContextStatus}
                contextStatusLoading={contextStatusLoading}
                kbLocked={!!currentId && hasConversationMessages}
                onChange={setComposerValue}
                onSubmit={submitComposer}
                onStop={handleStop}
                onSelectKb={handleKbChange}
                onModelChange={handleModelChange}
              />
            </main>

            <RightInsightPanel
              currentKbName={currentKb?.name ?? "\u901a\u7528\u5bf9\u8bdd"}
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

function SearchParamChatPage() {
  const searchParams = useSearchParams();
  return <ChatPage routeConversationId={searchParams.get("conversation")} />;
}

export default function Page() {
  return (
    <Suspense
      fallback={
        <div className="ak-chat flex min-h-screen items-center justify-center bg-[#0b111b] text-slate-400">
          <LoaderCircle className="h-4 w-4 animate-spin text-emerald-400" aria-hidden />
        </div>
      }
    >
      <SearchParamChatPage />
    </Suspense>
  );
}

function getKbStatusView(kb: KB) {
  const counts = kb.document_status_counts;
  const failed = counts?.failed ?? 0;
  const running = (counts?.pending ?? 0) + (counts?.ingesting ?? 0);
  if (failed > 0) {
    return {
      label: "\u9700\u5904\u7406",
      detail: `${failed} \u4e2a\u6587\u6863\u5f02\u5e38`,
      dot: "bg-red-400",
      tone: "text-red-300",
    };
  }
  if (running > 0) {
    return {
      label: "\u5904\u7406\u4e2d",
      detail: `${running} \u4e2a\u6587\u6863\u6392\u961f/\u89e3\u6790`,
      dot: "bg-amber-300",
      tone: "text-amber-200",
    };
  }
  if (kb.documents_count === 0) {
    return {
      label: "\u7a7a\u5e93",
      detail: "\u7b49\u5f85\u4e0a\u4f20\u8d44\u6599",
      dot: "bg-slate-500",
      tone: "text-slate-400",
    };
  }
  if (kb.chunks_count > 0) {
    return {
      label: "\u53ef\u68c0\u7d22",
      detail: `${kb.chunks_count.toLocaleString()} chunks`,
      dot: "bg-emerald-400",
      tone: "text-emerald-300",
    };
  }
  return {
    label: "\u5f85\u7d22\u5f15",
    detail: `${kb.documents_count.toLocaleString()} \u4e2a\u6587\u6863`,
    dot: "bg-sky-300",
    tone: "text-sky-200",
  };
}

function formatConversationTime(value?: number | null) {
  if (!value) return "";
  const diff = Date.now() - value;
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < minute) return "\u521a\u521a";
  if (diff < hour) return `${Math.max(1, Math.floor(diff / minute))} \u5206\u949f\u524d`;
  if (diff < day) return `${Math.floor(diff / hour)} \u5c0f\u65f6\u524d`;
  if (diff < 7 * day) return `${Math.floor(diff / day)} \u5929\u524d`;
  return new Date(value).toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

function getConversationStatusView(conversation: Conversation, currentId: string | null, busy: boolean) {
  const active = conversation.id === currentId;
  const messageCount = conversation.messages.length || conversation.message_count || 0;
  if (active && busy) {
    return {
      label: "\u751f\u6210\u4e2d",
      dot: "bg-amber-300",
      tone: "border-amber-300/20 bg-amber-300/10 text-amber-200",
    };
  }
  if (active) {
    return {
      label: "\u5f53\u524d",
      dot: "bg-emerald-400",
      tone: "border-emerald-300/20 bg-emerald-400/10 text-emerald-300",
    };
  }
  if (messageCount === 0) {
    return {
      label: "\u7a7a\u4f1a\u8bdd",
      dot: "bg-slate-500",
      tone: "border-white/10 bg-white/[0.04] text-slate-400",
    };
  }
  return {
    label: "\u5df2\u4fdd\u5b58",
    dot: "bg-sky-300",
    tone: "border-sky-300/15 bg-sky-300/10 text-sky-200",
  };
}

function DarkSidebar({
  open,
  conversations,
  conversationTotal,
  conversationHasMore,
  conversationLoadingMore,
  currentId,
  currentKbId,
  user,
  busy,
  onClose,
  onNew,
  onSelectConversation,
  onDeleteConversation,
  onLoadMoreConversations,
  onLogout,
}: {
  open: boolean;
  conversations: Conversation[];
  conversationTotal: number;
  conversationHasMore: boolean;
  conversationLoadingMore: boolean;
  currentId: string | null;
  currentKbId: string | null;
  user: User | null;
  busy: boolean;
  onClose: () => void;
  onNew: (kbId?: string | null) => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  onLoadMoreConversations: () => void;
  onLogout: () => void;
}) {
  const [searchTerm, setSearchTerm] = useState("");
  const [newMenuOpen, setNewMenuOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement | null>(null);
  const filteredConversations = conversations.filter((conversation) =>
    conversation.title.toLowerCase().includes(searchTerm.trim().toLowerCase())
  );
  const handleConversationScroll = useCallback(
    (event: { currentTarget: HTMLDivElement }) => {
      const target = event.currentTarget;
      const nearBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 80;
      if (nearBottom && conversationHasMore && !conversationLoadingMore) {
        onLoadMoreConversations();
      }
    },
    [conversationHasMore, conversationLoadingMore, onLoadMoreConversations]
  );

  useEffect(() => {
    if (!userMenuOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setUserMenuOpen(false);
    };
    const onPointerDown = (event: MouseEvent) => {
      if (!userMenuRef.current?.contains(event.target as Node)) {
        setUserMenuOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onPointerDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onPointerDown);
    };
  }, [userMenuOpen]);

  return (
    <aside
      className={cn(
        "ak-sidebar ak-motion-enter fixed inset-y-0 left-0 z-40 flex h-full min-h-0 w-[286px] flex-col overflow-hidden border-r border-white/10 bg-[#0a121f]/98 px-3 py-4 shadow-2xl transition-transform duration-surface ease-ui-drawer lg:relative lg:z-auto lg:translate-x-0 lg:shadow-none",
        open ? "translate-x-0" : "-translate-x-full"
      )}
    >
      <div className="flex items-center justify-between px-2">
        <Brand className="text-slate-950 dark:text-white" size="md" />
        <button
          aria-label="关闭侧栏"
          className="ak-press inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-white/10 lg:hidden"
          onClick={onClose}
          type="button"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="relative mt-7">
        <div className="flex overflow-hidden rounded-lg border border-emerald-300/20 bg-emerald-400 text-sm font-medium text-white shadow-[0_10px_30px_rgba(16,185,129,0.22)]">
          <button
            className="ak-press flex h-11 flex-1 items-center justify-center gap-2 bg-gradient-to-r from-emerald-400 to-emerald-500"
            onClick={() => onNew(currentKbId)}
            type="button"
          >
            <Plus className="h-4 w-4" />
            {"\u65b0\u5efa\u5bf9\u8bdd"}
          </button>
          <button
            aria-expanded={newMenuOpen}
            aria-label="新建菜单"
            className="ak-press flex w-10 items-center justify-center border-l border-white/20 hover:bg-emerald-500"
            onClick={() => setNewMenuOpen((open) => !open)}
            type="button"
          >
            <ChevronDown className={cn("h-4 w-4 transition-transform duration-press ease-ui-out", newMenuOpen && "rotate-180")} />
          </button>
        </div>
        {newMenuOpen && (
          <div className="ak-popover ak-motion-enter absolute left-0 right-0 top-12 z-20 overflow-hidden rounded-lg border border-white/10 bg-[#111c2b] p-1 text-sm text-slate-200 shadow-2xl">
            <button
              className="ak-press flex w-full items-center gap-2 rounded-md px-3 py-2 text-left hover:bg-white/[0.06]"
              onClick={() => {
                setNewMenuOpen(false);
                onNew(null);
              }}
              type="button"
            >
              <MessageCircle className="h-4 w-4 text-slate-400" />
              {"\u65b0\u5efa\u901a\u7528\u5bf9\u8bdd"}
            </button>
            <button
              className={cn(
                "ak-press flex w-full items-center gap-2 rounded-md px-3 py-2 text-left hover:bg-white/[0.06]",
                !currentKbId && "cursor-not-allowed opacity-45 hover:bg-transparent"
              )}
              disabled={!currentKbId}
              onClick={() => {
                if (!currentKbId) return;
                setNewMenuOpen(false);
                onNew(currentKbId);
              }}
              title={currentKbId ? "\u4f7f\u7528\u5f53\u524d\u77e5\u8bc6\u5e93\u65b0\u5efa\u5bf9\u8bdd" : "\u5f53\u524d\u672a\u7ed1\u5b9a\u77e5\u8bc6\u5e93"}
              type="button"
            >
              <Database className="h-4 w-4 text-emerald-300" />
              {"\u57fa\u4e8e\u5f53\u524d\u77e5\u8bc6\u5e93\u65b0\u5efa"}
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
        <span className="flex-1 text-left">{"\u5168\u90e8\u5bf9\u8bdd"}</span>
        <span className="tabular-nums text-slate-500">{conversationTotal}</span>
      </button>

      <div className="my-4 h-px bg-white/10" />

      <div
        className="min-h-0 basis-0 flex-1 overflow-y-auto pr-1"
        onScroll={handleConversationScroll}
      >
        <div className="flex items-center justify-between px-2 pb-2 text-sm text-slate-400">
          <span>{"\u6700\u8fd1\u5bf9\u8bdd"}</span>
          <span className="text-xs tabular-nums text-slate-600">
            {filteredConversations.length}/{conversationTotal}
          </span>
        </div>
        <div className="space-y-1">
          {filteredConversations.map((conversation) => {
            const statusView = getConversationStatusView(conversation, currentId, busy);
            const messageCount = conversation.messages.length || conversation.message_count || 0;
            const showStatusTag = conversation.id === currentId && busy;
            return (
            <div
              key={conversation.id}
              className={cn(
                "group flex min-h-12 items-center gap-2 rounded-lg px-3 py-2 text-sm transition",
                conversation.id === currentId
                  ? "bg-white/[0.08] text-slate-100"
                  : "text-slate-500 hover:bg-white/[0.06] hover:text-slate-200"
              )}
            >
              <button
                className="min-w-0 flex-1 text-left"
                onClick={() => onSelectConversation(conversation.id)}
                type="button"
                title={conversation.title}
              >
                <span className="block truncate">{conversation.title}</span>
                <span className="mt-0.5 flex items-center gap-2 text-[11px] text-slate-600">
                  <span className={cn("h-1.5 w-1.5 rounded-full", statusView.dot)} />
                  <span>{formatConversationTime(conversation.updated_at)}</span>
                  <span className="h-1 w-1 rounded-full bg-slate-700" />
                  <span>{messageCount}{" \u6761\u6d88\u606f"}</span>
                </span>
              </button>
              {showStatusTag && (
                <span
                  className={cn(
                    "shrink-0 rounded-md border px-1.5 py-0.5 text-[11px] group-hover:hidden",
                    statusView.tone
                  )}
                >
                  {statusView.label}
                </span>
              )}
              <button
                aria-label="删除会话"
                className="hidden h-7 w-7 shrink-0 items-center justify-center rounded-md text-slate-500 hover:bg-red-400/10 hover:text-red-300 group-hover:flex"
                onClick={() => {
                  if (window.confirm(`\u5220\u9664\u5bf9\u8bdd\u300c${conversation.title}\u300d\uff1f\u6b64\u64cd\u4f5c\u4e0d\u53ef\u6062\u590d\u3002`)) {
                    onDeleteConversation(conversation.id);
                  }
                }}
                type="button"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
            );
          })}
          {filteredConversations.length === 0 && (
            <div className="rounded-lg border border-dashed border-white/10 px-3 py-4 text-sm text-slate-500">
              {searchTerm ? "\u6ca1\u6709\u5339\u914d\u7684\u5bf9\u8bdd\u3002" : "\u8fd8\u6ca1\u6709\u5bf9\u8bdd\uff0c\u5148\u95ee\u4e00\u4e2a\u95ee\u9898\u3002"}
            </div>
          )}
          {(conversationHasMore || conversationLoadingMore) && (
            <button
              className="flex h-9 w-full items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] text-xs text-slate-500 transition hover:border-emerald-300/20 hover:text-slate-300 disabled:cursor-wait disabled:opacity-70"
              disabled={conversationLoadingMore}
              onClick={onLoadMoreConversations}
              type="button"
            >
              {conversationLoadingMore ? (
                <>
                  <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                  {"\u6b63\u5728\u52a0\u8f7d"}
                </>
              ) : (
                "\u52a0\u8f7d\u66f4\u591a\u5bf9\u8bdd"
              )}
            </button>
          )}
        </div>
      </div>

      <div ref={userMenuRef} className="relative mt-3 shrink-0">
        {userMenuOpen && (
          <div className="ak-popover absolute bottom-full left-0 right-0 mb-2 overflow-hidden rounded-lg border border-white/10 bg-[#111c2b] shadow-2xl">
            <Link
              className="flex items-center gap-2 px-3 py-2.5 text-sm text-slate-200 transition hover:bg-white/[0.06]"
              href="/settings"
              onClick={() => setUserMenuOpen(false)}
            >
              <Settings className="h-4 w-4 text-slate-400" />
              模型设置
            </Link>
            <Link
              className="flex items-center gap-2 px-3 py-2.5 text-sm text-slate-200 transition hover:bg-white/[0.06]"
              href="/kbs"
              onClick={() => setUserMenuOpen(false)}
            >
              <BookOpen className="h-4 w-4 text-slate-400" />
              我的知识库
            </Link>
            {user?.is_admin && (
              <Link
                className="flex items-center gap-2 px-3 py-2.5 text-sm text-slate-200 transition hover:bg-white/[0.06]"
                href="/admin"
                onClick={() => setUserMenuOpen(false)}
              >
                <Shield className="h-4 w-4 text-slate-400" />
                后台管理
              </Link>
            )}
            <div className="h-px bg-white/10" />
            <button
              className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm text-red-300 transition hover:bg-red-400/10"
              onClick={() => {
                setUserMenuOpen(false);
                onLogout();
              }}
              type="button"
            >
              <LogOut className="h-4 w-4" />
              退出登录
            </button>
          </div>
        )}
        <button
          aria-expanded={userMenuOpen}
          aria-haspopup="menu"
          aria-label="用户菜单"
          className={cn(
            "flex w-full items-center justify-between rounded-lg border border-white/10 bg-black/20 p-2 text-left transition hover:bg-white/[0.06]",
            userMenuOpen && "border-emerald-300/30 bg-white/[0.06]"
          )}
          onClick={() => setUserMenuOpen((open) => !open)}
          type="button"
        >
          <span className="flex min-w-0 items-center gap-2">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-500 text-sm font-semibold text-white">
              {(user?.display_name?.[0] || user?.email?.[0] || "Z").toUpperCase()}
            </span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-slate-100">
                {user?.display_name || user?.email || "\u7528\u6237"}
              </span>
              <span className="block text-xs text-slate-500">{user?.is_admin ? "\u7ba1\u7406\u5458" : "\u6210\u5458"}</span>
            </span>
          </span>
          <ChevronDown className={cn("h-4 w-4 shrink-0 text-slate-500 transition", userMenuOpen && "rotate-180")} />
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
    llmSource === "user" ? "BYOK" : llmSource === "system" ? "系统模型" : "未配置模型";

  return (
    <header className="ak-topbar grid h-[72px] shrink-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 border-b border-white/10 bg-[#0b1422]/88 px-4 backdrop-blur-xl xl:px-7">
      <button
        className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-white/10 text-slate-300 lg:hidden"
        onClick={onOpenSidebar}
        type="button"
        aria-label="打开侧栏"
      >
        <ChevronLeft className="h-5 w-5 rotate-180" />
      </button>

      <div className="min-w-0">
        <div className="text-xs text-slate-500">{"\u5f53\u524d\u4f1a\u8bdd\u77e5\u8bc6\u5e93"}</div>
        <div className="mt-1 flex items-center gap-2 text-sm font-medium text-slate-100">
          <Database className="h-4 w-4 text-emerald-300" />
          <span className="truncate">{currentKb?.name ?? "\u901a\u7528\u5bf9\u8bdd"}</span>
        </div>
      </div>

      <div className="flex items-center justify-end gap-2">
        <ThemeToggle className="hidden sm:flex" />
        <div
          className={cn(
            "hidden h-9 items-center gap-2 rounded-lg border px-3 text-xs sm:flex",
            llmReady
              ? "border-emerald-300/20 bg-emerald-400/10 text-emerald-300"
              : "border-amber-300/25 bg-amber-400/10 text-amber-200"
          )}
          title="模型状态"
        >
          <span
            className={cn(
              "h-2 w-2 rounded-full",
              llmReady ? "bg-emerald-400" : "bg-amber-300"
            )}
          />
          <span className="font-medium">{statusLabel}</span>
          <span className="h-3 w-px bg-white/15" />
          <span className="text-slate-400">{configLabel}</span>
        </div>
        <Link
          className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/10 px-3 text-sm text-slate-400 transition hover:border-emerald-300/30 hover:bg-white/[0.06] hover:text-slate-100"
          href="/welcome"
          aria-label="打开产品介绍"
        >
          <HelpCircle className="h-4 w-4" />
          <span className="hidden sm:inline">介绍</span>
        </Link>
      </div>
    </header>
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
      <section className="ak-card w-full max-w-[720px] rounded-lg border border-white/10 bg-[#111c2b]/72 p-5 shadow-[0_18px_46px_rgba(0,0,0,0.28)]">
        <div className="flex items-start gap-4">
          <Avatar label={<Box className="h-4 w-4" />} tone="assistant" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-emerald-300">{"\u5df2\u8fde\u63a5 "}{currentKbName}</div>
            <h1 className="mt-2 text-xl font-semibold tracking-tight text-slate-100 sm:text-2xl">
              {"\u5411\u77e5\u8bc6\u5e93\u63d0\u95ee\uff0c\u68c0\u7d22\u8fc7\u7a0b\u4f1a\u5b9e\u65f6\u5c55\u793a"}
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
              {"\u8fd9\u91cc\u4e0d\u4f1a\u9884\u7f6e\u5047\u7b54\u6848\u3002\u53d1\u9001\u95ee\u9898\u540e\uff0c\u4e2d\u95f4\u533a\u57df\u4f1a\u663e\u793a\u771f\u5b9e\u5bf9\u8bdd\uff0c\u53f3\u4fa7\u4f1a\u6839\u636e\u5de5\u5177\u8c03\u7528\u5c55\u793a\u68c0\u7d22\u3001\u91cd\u6392\u3001\u751f\u6210\u72b6\u6001\u3002"}
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
        <div className="ak-card rounded-lg border border-white/10 bg-[#111c2b]/78 px-5 py-4 shadow-[0_18px_46px_rgba(0,0,0,0.28)]">
          {message.error && (
            <div className="mb-3 rounded-lg border border-red-400/20 bg-red-400/10 px-3 py-2 text-sm text-red-200">
              {message.error}
            </div>
          )}
          {!hasContent && streaming && (
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <LoaderCircle className="h-4 w-4 animate-spin text-emerald-400" />
              {"\u6b63\u5728\u68c0\u7d22\u5e76\u751f\u6210\u56de\u7b54"}
            </div>
          )}
          {hasContent && <AnswerMarkdown markdown={message.content} streaming={streaming} />}
          {!hasContent && !streaming && !message.error && (
            <div className="text-sm text-slate-500">{"\u6682\u65e0\u5185\u5bb9"}</div>
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
                    toast.success("\u5df2\u590d\u5236\u56de\u7b54");
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
      <div className="mb-2 text-sm font-medium text-emerald-300">{"\u5de5\u5177\u8c03\u7528"}</div>
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

function ContextCompressionNotice({
  contextStatus,
}: {
  contextStatus: ConversationContextStatus | null;
}) {
  if (!contextStatus || contextStatus.state === "normal") return null;
  const isCompressed = contextStatus.state === "compressed";
  return (
    <div className="mx-auto flex w-fit max-w-full items-center gap-2 rounded-full border border-white/10 bg-[#0d1726]/82 px-3 py-1.5 text-xs text-slate-400 shadow-[0_10px_28px_rgba(0,0,0,0.18)]">
      <ShieldCheck
        className={cn(
          "h-3.5 w-3.5",
          isCompressed ? "text-emerald-300" : "text-amber-300"
        )}
      />
      <span className="truncate">
        {isCompressed
          ? `已自动压缩早期上下文，保留最近 ${contextStatus.retained_recent_turns} 轮完整对话`
          : contextStatus.description}
      </span>
    </div>
  );
}

function buildMessageSources(message: Extract<Message, { role: "assistant" }>): SourceRow[] {
  if (message.tools.length === 0) return [];
  return message.tools.slice(0, 4).map((tool) => ({
    title: getToolLabel(tool.name),
    meta: tool.status === "running" ? "\u6b63\u5728\u6267\u884c" : tool.status === "ok" ? "\u5df2\u5b8c\u6210" : "\u672a\u5b8c\u6210",
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
          ? "\u6b63\u5728\u6267\u884c"
          : tool.status === "ok"
          ? `\u5df2\u5b8c\u6210${tool.latency_ms ? ` · ${tool.latency_ms}ms` : ""}`
          : tool.status === "blocked"
          ? tool.reason || "\u5df2\u963b\u6b62"
          : tool.error || "\u6267\u884c\u5931\u8d25",
      score:
        tool.status === "ok"
          ? "\u5b8c\u6210"
          : tool.status === "running"
          ? "\u5b9e\u65f6"
          : tool.status === "blocked"
          ? "\u963b\u6b62"
          : "\u5931\u8d25",
    }));
  }
  return [];
}

function getToolLabel(name: string): string {
  const labels: Record<string, string> = {
    search_kb: "\u77e5\u8bc6\u5e93\u68c0\u7d22",
    generate_kb_report: "\u77e5\u8bc6\u5e93\u62a5\u544a\u751f\u6210",
    web_search: "\u7f51\u7edc\u641c\u7d22",
    get_weather: "\u5929\u6c14\u67e5\u8be2",
    search_restaurant_kb: "\u672c\u5730\u77e5\u8bc6\u68c0\u7d22",
    amap_search: "\u5730\u56fe\u641c\u7d22",
    generate_travel_report: "\u65c5\u884c\u62a5\u544a\u751f\u6210",
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
    search_kb: "\u77e5\u8bc6\u5e93\u68c0\u7d22",
    generate_kb_report: "\u77e5\u8bc6\u5e93\u62a5\u544a",
    web_search: "\u7f51\u7edc\u641c\u7d22",
    get_weather: "\u5929\u6c14\u67e5\u8be2",
    search_restaurant_kb: "\u672c\u5730\u77e5\u8bc6\u68c0\u7d22",
    amap_search: "\u5730\u56fe\u641c\u7d22",
    generate_travel_report: "\u65c5\u884c\u62a5\u544a",
  };
  return labels[name] ?? name;
}

function getToolStatusLabelClean(status: ToolEvent["status"]) {
  if (status === "ok") return "\u5b8c\u6210";
  if (status === "running") return "\u8fdb\u884c\u4e2d";
  if (status === "blocked") return "\u963b\u585e";
  return "\u5931\u8d25";
}

function getToolMetaClean(tool: ToolEvent) {
  if (tool.status === "running") return "\u6b63\u5728\u6267\u884c";
  if (tool.status === "ok") {
    return tool.latency_ms ? `\u5df2\u5b8c\u6210 \u00b7 ${formatDuration(tool.latency_ms)}` : "\u5df2\u5b8c\u6210";
  }
  if (tool.status === "blocked") return tool.reason || "\u8c03\u7528\u88ab\u7b56\u7565\u963b\u6b62";
  return normalizeToolError(tool.error);
}

function normalizeToolError(error?: string | null) {
  if (!error) return "\u8c03\u7528\u5931\u8d25";
  const lower = error.toLowerCase();
  if (lower.includes("timed out") || lower.includes("timeout")) {
    return "\u8bf7\u6c42\u8d85\u65f6\uff0c\u5df2\u8df3\u8fc7\u8be5\u7ed3\u679c";
  }
  if (lower.includes("network") || lower.includes("fetch") || lower.includes("request")) {
    return "\u7f51\u7edc\u8bf7\u6c42\u5931\u8d25\uff0c\u5df2\u8df3\u8fc7\u8be5\u7ed3\u679c";
  }
  return error.length > 48 ? `${error.slice(0, 48)}...` : error;
}

function formatDuration(ms: number) {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

function describeToolSummary(tools: ToolEvent[]) {
  if (tools.length === 0) return "\u672c\u8f6e\u672a\u8c03\u7528\u68c0\u7d22\u5de5\u5177";
  const counts = new Map<string, number>();
  for (const tool of tools) {
    const label = getToolLabelClean(tool.name);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([label, count]) => (count > 1 ? `${label} x${count}` : label))
    .join("\u3001");
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
      title={disabled ? `${label}\u6682\u672a\u63a5\u5165` : label}
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
  currentKbId,
  kbs,
  currentModel,
  modelOptions,
  llmReady,
  llmSource,
  contextStatus,
  contextStatusLoading,
  kbLocked,
  onChange,
  onSubmit,
  onStop,
  onSelectKb,
  onModelChange,
}: {
  value: string;
  textareaRef: React.RefObject<HTMLTextAreaElement>;
  busy: boolean;
  currentKbId: string | null;
  kbs: KB[];
  currentModel: string | null;
  modelOptions: string[];
  llmReady: boolean;
  llmSource: LlmSource;
  contextStatus: ConversationContextStatus | null;
  contextStatusLoading: boolean;
  kbLocked: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  onSelectKb: (id: string | null) => void;
  onModelChange: (model: string | null) => void;
}) {
  const defaultModelLabel = llmReady
    ? llmSource === "system"
      ? "\u7cfb\u7edf\u9ed8\u8ba4\u6a21\u578b"
      : "\u9ed8\u8ba4\u6a21\u578b"
    : "\u672a\u914d\u7f6e\u6a21\u578b";

  return (
    <div className="ak-composer shrink-0 border-t border-white/10 bg-[#08101c]/90 px-5 py-3 backdrop-blur-xl">
      <div className="ak-composer-box mx-auto max-w-[820px] rounded-lg border border-white/12 bg-[#0d1726]/94 shadow-[0_18px_46px_rgba(0,0,0,0.32)] focus-within:border-emerald-300/40">
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
            className="ak-control inline-flex h-9 max-w-[240px] items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-slate-300"
            title={kbLocked ? "当前会话已有消息，知识库已锁定" : "选择通用聊天或知识库"}
          >
            <Database className="h-4 w-4 text-emerald-300" />
            <select
              aria-label="选择知识库"
              className="min-w-0 flex-1 bg-transparent text-sm text-slate-200 outline-none disabled:cursor-not-allowed disabled:text-slate-500"
              disabled={kbLocked || busy}
              onChange={(e) => onSelectKb(e.target.value || null)}
              value={currentKbId ?? ""}
            >
              <option value="">通用聊天</option>
              {kbs.map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name}
                </option>
              ))}
            </select>
            {kbLocked && <LockKeyhole className="h-3.5 w-3.5 text-slate-500" />}
          </div>
          <Link
            className="ak-control ak-press inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-slate-300 hover:bg-white/[0.08]"
            href={currentKbId ? `/kbs/${currentKbId}` : "/kbs"}
            aria-label={currentKbId ? "\u6253\u5f00\u77e5\u8bc6\u5e93\u4e0a\u4f20\u8d44\u6599" : "\u9009\u62e9\u77e5\u8bc6\u5e93\u540e\u4e0a\u4f20\u8d44\u6599"}
            title={currentKbId ? "\u6253\u5f00\u77e5\u8bc6\u5e93\u4e0a\u4f20\u8d44\u6599" : "\u9009\u62e9\u77e5\u8bc6\u5e93\u540e\u4e0a\u4f20\u8d44\u6599"}
          >
            <Paperclip className="h-4 w-4" />
          </Link>
          <div className="ml-auto flex min-w-0 items-center gap-2">
            <ContextUsageIndicator
              contextStatus={contextStatus}
              loading={contextStatusLoading}
            />
            <select
              className="ak-control h-9 max-w-[190px] rounded-lg border border-white/10 bg-[#111c2b] px-3 text-sm text-slate-200 outline-none transition focus:border-emerald-300/40 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={busy || modelOptions.length === 0}
              value={currentModel ?? ""}
              onChange={(e) => onModelChange(e.target.value || null)}
              title={modelOptions.length > 0 ? "\u6a21\u578b\u9009\u62e9" : "\u8bf7\u5148\u5728\u8bbe\u7f6e\u4e2d\u914d\u7f6e\u6a21\u578b"}
            >
              <option value="">{defaultModelLabel}</option>
              {modelOptions.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          </div>
          {busy ? (
            <button
              className="ak-press inline-flex h-10 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.06] px-4 text-sm font-medium text-slate-100 hover:bg-white/10"
              aria-label="停止生成"
              data-testid="composer-stop"
              onClick={onStop}
              type="button"
            >
              <Square className="h-3.5 w-3.5 fill-current" />
              {"\u505c\u6b62"}
            </button>
          ) : (
            <button
              className="ak-control-primary ak-press inline-flex h-10 items-center gap-2 rounded-lg bg-emerald-400 px-4 text-sm font-medium text-white shadow-[0_10px_24px_rgba(16,185,129,0.28)] hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-45"
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
      <p className="mt-2 text-center text-xs text-slate-500">{"\u5185\u5bb9\u7531 AI \u751f\u6210\uff0c\u8bf7\u4ed4\u7ec6\u7504\u522b"}</p>
    </div>
  );
}

function ContextUsageIndicator({
  contextStatus,
  loading,
}: {
  contextStatus: ConversationContextStatus | null;
  loading: boolean;
}) {
  const status = contextStatus ?? {
    state: "normal" as const,
    label: loading ? "正在读取" : "暂不可用",
    description: loading
      ? "正在读取当前会话的上下文使用情况。"
      : "暂时无法读取上下文状态，请刷新后重试。",
    current_tokens: 0,
    available_tokens: 0,
    percent: 0,
    retained_recent_turns: 10,
    summary: null,
  };
  const progress = Math.min(100, Math.max(0, status.percent));
  const circumference = 2 * Math.PI * 8;
  const dashOffset = loading ? 0 : circumference * (1 - progress / 100);
  const isAttention = status.state === "approaching" || status.state === "ready" || status.state === "critical";
  const ringTone =
    status.state === "compressed"
      ? "text-emerald-300"
      : isAttention
        ? "text-amber-300"
        : "text-slate-400";
  const detail =
    status.state === "compressed"
      ? `已自动压缩早期上下文，保留最近 ${status.retained_recent_turns} 轮完整对话。`
      : status.description;

  return (
    <div className="group relative shrink-0">
      <button
        aria-describedby="context-usage-detail"
        aria-label={loading ? "正在读取上下文使用率" : `上下文使用率 ${progress}%：${status.label}`}
        className="ak-context-usage ak-press inline-flex size-9 items-center justify-center rounded-full text-slate-400 outline-none focus-visible:ring-2 focus-visible:ring-emerald-300/70"
        type="button"
      >
        <svg
          aria-hidden="true"
          className={cn("size-5 -rotate-90", loading && "animate-spin motion-reduce:animate-none")}
          viewBox="0 0 20 20"
        >
          <circle className="stroke-current text-white/10" cx="10" cy="10" fill="none" r="8" strokeWidth="2.25" />
          <circle
            className={cn("ak-context-ring stroke-current", ringTone)}
            cx="10"
            cy="10"
            fill="none"
            r="8"
            strokeDasharray={loading ? `16 ${circumference}` : circumference}
            strokeDashoffset={dashOffset}
            strokeLinecap="round"
            strokeWidth="2.25"
          />
        </svg>
      </button>
      <div
        className="pointer-events-none absolute bottom-full right-0 z-20 mb-2 w-72 translate-y-1 rounded-lg border border-white/10 bg-[#111c2b]/98 p-3 text-left opacity-0 shadow-xl transition-[opacity,transform] duration-150 ease-out group-hover:translate-y-0 group-hover:opacity-100 group-focus-within:translate-y-0 group-focus-within:opacity-100"
        id="context-usage-detail"
        role="tooltip"
      >
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium text-slate-100">上下文使用</span>
          <span className={cn("text-xs font-medium tabular-nums", ringTone)}>{status.label}</span>
        </div>
        <div className="mt-2 flex items-baseline justify-between gap-3 tabular-nums">
          <span className="text-lg font-semibold text-slate-100">{progress}%</span>
          <span className="text-xs text-slate-400">
            {formatTokenCount(status.current_tokens)} / {formatTokenCount(status.available_tokens)}
          </span>
        </div>
        <p className="mt-2 text-xs leading-5 text-slate-400">{detail}</p>
        {status.summary && (
          <p className="mt-2 border-t border-white/10 pt-2 text-xs leading-5 text-slate-400">
            已覆盖 {status.summary.covered_message_count} 条早期消息 · 摘要约 {formatTokenCount(status.summary.token_count)}
          </p>
        )}
      </div>
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
  const modelLabel = currentModel || (llmSource === "system" ? "\u7cfb\u7edf\u9ed8\u8ba4" : llmSource === "user" ? "\u9ed8\u8ba4\u6a21\u578b" : "\u672a\u914d\u7f6e");

  return (
    <aside className="ak-insight hidden min-w-0 flex-col overflow-y-auto bg-[#0a121f] lg:flex">
      <section className="border-b border-white/10 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-100">{"\u68c0\u7d22\u4e0e\u63a8\u7406\u8fc7\u7a0b"}</h2>
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
          <h2 className="text-base font-semibold text-slate-100">{"\u5de5\u5177\u8c03\u7528\u8bb0\u5f55"}</h2>
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
            {"\u6682\u65e0\u5de5\u5177\u8c03\u7528\u3002\u53d1\u9001\u95ee\u9898\u540e\uff0c\u5982\u679c\u540e\u7aef\u8fd4\u56de\u68c0\u7d22\u3001\u91cd\u6392\u6216\u5176\u4ed6\u5de5\u5177\u4e8b\u4ef6\uff0c\u8fd9\u91cc\u4f1a\u5b9e\u65f6\u66f4\u65b0\u3002"}
          </div>
        )}
      </section>

      <section className="flex-1 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-100">{"\u4f1a\u8bdd\u4fe1\u606f"}</h2>
          {currentConversation?.id && (
            <button
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-white/10 px-2 text-xs text-slate-400 transition hover:border-emerald-300/40 hover:text-emerald-200"
              onClick={() => {
                void navigator.clipboard.writeText(currentConversation.id);
                toast.success("\u5df2\u590d\u5236\u4f1a\u8bdd ID");
              }}
              type="button"
            >
              <Copy className="h-3.5 w-3.5" />
              {"\u590d\u5236 ID"}
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
                "\u901a\u7528\u5bf9\u8bdd"
              )
            }
          />
          <InfoRow label="模型" value={modelLabel} />
        </dl>
      </section>

      <section className="hidden">
        <h2 className="text-base font-semibold text-slate-100">{"\u4f1a\u8bdd\u4fe1\u606f"}</h2>
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
        title: "\u7b49\u5f85\u63d0\u95ee",
        description: "\u8f93\u5165\u95ee\u9898\u540e\u5f00\u59cb\u5206\u6790\u610f\u56fe",
        status: "pending",
        active: false,
      },
      {
        title: "\u68c0\u7d22\u77e5\u8bc6",
        description: "\u7ed1\u5b9a\u77e5\u8bc6\u5e93\u65f6\u6267\u884c\u6df7\u5408\u68c0\u7d22",
        status: "pending",
        active: false,
      },
      {
        title: "\u91cd\u6392\u7ed3\u679c",
        description: "\u6709\u68c0\u7d22\u7ed3\u679c\u65f6\u8fdb\u884c\u76f8\u5173\u6027\u6392\u5e8f",
        status: "pending",
        active: false,
      },
      {
        title: "\u751f\u6210\u56de\u7b54",
        description: "\u68c0\u7d22\u5b8c\u6210\u540e\u751f\u6210\u6700\u7ec8\u56de\u7b54",
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
      title: "\u7406\u89e3\u95ee\u9898",
      description: "\u5206\u6790\u7528\u6237\u95ee\u9898\uff0c\u8bc6\u522b\u5173\u952e\u610f\u56fe",
      status: "done",
      active: false,
    },
    {
      title: "\u68c0\u7d22\u77e5\u8bc6",
      description:
        tools.length > 0
          ? `${describeToolSummary(tools)}${hasToolFailures ? "\uff0c\u90e8\u5206\u8c03\u7528\u5931\u8d25" : ""}`
          : "\u672c\u8f6e\u672a\u8fd4\u56de\u7ed3\u6784\u5316\u68c0\u7d22\u4e8b\u4ef6",
      status: retrievalStatus,
      active: retrievalStatus === "running",
    },
    {
      title: "\u91cd\u6392\u7ed3\u679c",
      description:
        tools.length > 0
          ? "\u5df2\u6574\u7406\u53ef\u7528\u68c0\u7d22\u7ed3\u679c"
          : "\u65e0\u53ef\u5c55\u793a\u7684\u91cd\u6392\u7ed3\u679c",
      status: rerankStatus,
      active: false,
    },
    {
      title: "\u751f\u6210\u56de\u7b54",
      description: busy
        ? "\u6b63\u5728\u751f\u6210\u6700\u7ec8\u56de\u7b54"
        : hasAssistantAnswer
        ? "\u56de\u7b54\u5df2\u5199\u5165\u5f53\u524d\u4f1a\u8bdd"
        : "\u7b49\u5f85\u6a21\u578b\u8fd4\u56de\u56de\u7b54",
      status: answerStatus,
      active: answerStatus === "running",
    },
  ];
}

function deriveSteps(tools: ToolEvent[], busy: boolean, messages: Message[]): ProcessStep[] {
  return deriveStepsClean(tools, busy, messages);
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

function formatTokenCount(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "-";
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

function formatMessageStats(messages: Message[]) {
  const userCount = messages.filter((message) => message.role === "user").length;
  const assistantCount = messages.filter((message) => message.role === "assistant").length;
  return `${userCount} \u8f6e \u00b7 ${messages.length} \u6761`;
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
