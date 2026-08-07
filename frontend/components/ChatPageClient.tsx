"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  Suspense,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import SystemSettingsDialog from "@/components/SystemSettingsDialog";
import { useStreamingTokenPaint } from "@/hooks/useStreamingTokenPaint";
import { Button } from "@/components/ui/button";
import { StateView } from "@/components/ui/state-view";
import { ArrowDown } from "lucide-react";
import { toast } from "sonner";
import { APP_NAME } from "@/components/Brand";
import { type ToolEvent } from "@/components/ThinkingChain";
import { logout } from "@/lib/auth";
import { cn } from "@/lib/cn";
import {
  appendAssistantMessage,
  appendUserMessage,
  createConversation,
  deleteConversation,
  finalizeConversation,
  getConversation,
  getConversationContextStatus,
  listConversations,
  patchConversation,
  type ConversationContextStatus,
  type ConversationSummary,
} from "@/lib/conversations-api";
import {
  deriveTitle,
  flattenAssistantTools,
  genMessageId,
  joinAssistantText,
  type AssistantPart,
  type Message,
} from "@/lib/conversationStore";
import {
  connectChat,
  type ChatEvent,
  type ChatMessage as SseChatMessage,
  type Citation,
  type MemoryTrace,
} from "@/lib/sseClient";
import {
  ChatLoadingShell,
  ChatSidebar,
  ConversationSearchDialog,
  ChatTopBar,
  ChatMessage,
  Composer,
  ContextCompressionNotice,
  EmptyWorkbench,
  StarterPromptCards,
  DEFAULT_TITLE,
  formatMessageStats,
  mergeCitations,
  updateToolEvent,
} from "@/components/chat";
import { useChatBoot } from "@/hooks/useChatBoot";
import {
  CHAT_PANE_FADE_MS,
  CONVERSATION_PAGE_SIZE,
  EMPTY_ASSISTANT_RESPONSE,
  conversationHref,
  conversationIdFromPath,
  estimateContextStatus,
  mergeConversationSummaries,
  normalizeMessages,
  serverMsgToLocal,
  summaryToConv,
  waitPaneMs,
} from "@/lib/chatPageHelpers";

export function ChatPage({
  routeConversationId = null,
  startBlank = false,
}: {
  routeConversationId?: string | null;
  startBlank?: boolean;
}) {
  const router = useRouter();
  const [panePhase, setPanePhase] = useState<"in" | "out">("in");

  const [summaries, setSummaries] = useState<ConversationSummary[]>([]);
  const [conversationTotal, setConversationTotal] = useState(0);
  const [conversationPage, setConversationPage] = useState(1);
  const [conversationHasMore, setConversationHasMore] = useState(false);
  const [conversationLoadingMore, setConversationLoadingMore] = useState(false);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [currentMessages, setCurrentMessages] = useState<Message[]>([]);
  const [missingConversationId, setMissingConversationId] = useState<string | null>(null);
  const [currentKbId, setCurrentKbId] = useState<string | null>(null);
  const [currentModel, setCurrentModel] = useState<string | null>(null);
  const [currentContextStatus, setCurrentContextStatus] =
    useState<ConversationContextStatus | null>(null);
  const [contextStatusLoading, setContextStatusLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [composerValue, setComposerValue] = useState("");

  const messagesCache = useRef<Map<string, Message[]>>(new Map());
  const cleanupRef = useRef<(() => void) | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const paneSwitchSeq = useRef(0);
  const sendLockRef = useRef(false);
  const modelOptionsRef = useRef<string[]>([]);
  const currentIdRef = useRef<string | null>(null);
  const streamingRef = useRef<{
    convId: string;
    msgId: string;
    content: string;
    parts: AssistantPart[];
    tools: ToolEvent[];
    memory_trace: MemoryTrace | null;
    citations: Citation[];
  } | null>(null);

  useEffect(() => {
    currentIdRef.current = currentId;
  }, [currentId]);

  const visibleMessages = useMemo(() => normalizeMessages(currentMessages), [currentMessages]);

  const sidebarConversations = useMemo(
    () => summaries.map((s) => summaryToConv(s, s.id === currentId ? visibleMessages : [])),
    [summaries, currentId, visibleMessages]
  );

  const hasConversationMessages = visibleMessages.length > 0;

  const loadConversation = useCallback(async (id: string) => {
    setMissingConversationId(null);
    setCurrentId(id);
    setContextStatusLoading(true);
    const cached = messagesCache.current.get(id);
    if (cached) {
      const msgs = normalizeMessages(cached);
      messagesCache.current.set(id, msgs);
      setCurrentMessages(msgs);
      let cachedKbId: string | null = null;
      setSummaries((cur) => {
        const found = cur.find((c) => c.id === id);
        if (found) {
          cachedKbId = found.kb_id;
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
          setCurrentContextStatus(
            estimateContextStatus(cached, null, modelOptionsRef.current, cachedKbId)
          );
        })
        .finally(() => {
          setContextStatusLoading(false);
        });
      return true;
    }
    try {
      const detail = await getConversation(id);
      const msgs = normalizeMessages(detail.messages.map(serverMsgToLocal));
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
          finalized_at: detail.finalized_at,
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
          if (!detail.context_status) {
            setCurrentContextStatus(
              estimateContextStatus(msgs, detail.llm_model, modelOptionsRef.current, detail.kb_id)
            );
          }
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
      setMissingConversationId(id);
      setContextStatusLoading(false);
      return false;
    }
  }, []);

  const clearActiveConversation = useCallback(() => {
    setMissingConversationId(null);
    setCurrentId(null);
    setCurrentMessages([]);
    setCurrentKbId(null);
    setCurrentModel(null);
    setCurrentContextStatus(null);
  }, []);

  const {
    user,
    setUser,
    authChecked,
    initialLoadDone,
    bootPhase,
    modelOptions,
    llmReady,
    llmSource,
    kbs,
    systemSettingsOpen,
    setSystemSettingsOpen,
  } = useChatBoot({
    routeConversationId,
    startBlank,
    loadConversation,
    clearActiveConversation,
    setSummaries,
    setConversationTotal,
    setConversationPage,
    setConversationHasMore,
  });

  useEffect(() => {
    modelOptionsRef.current = modelOptions;
  }, [modelOptions]);

  const currentConversation = sidebarConversations.find((c) => c.id === currentId) ?? null;
  const currentKb = kbs.find((kb) => kb.id === currentKbId) ?? null;

  const runPaneTransition = useCallback(async (action: () => void | Promise<void | boolean>) => {
    const seq = ++paneSwitchSeq.current;
    setPanePhase("out");
    await waitPaneMs(CHAT_PANE_FADE_MS);
    if (seq !== paneSwitchSeq.current) return false;
    const result = await action();
    if (seq !== paneSwitchSeq.current) return false;
    await new Promise<void>((resolve) => {
      requestAnimationFrame(() => resolve());
    });
    if (seq !== paneSwitchSeq.current) return false;
    setPanePhase("in");
    return result !== false;
  }, []);

  const setMessagesForCurrent = useCallback(
    (next: Message[] | ((prev: Message[]) => Message[])) => {
      setCurrentMessages((prev) => {
        const resolved =
          typeof next === "function" ? (next as (p: Message[]) => Message[])(prev) : next;
        const id = currentIdRef.current;
        if (id) messagesCache.current.set(id, resolved);
        return resolved;
      });
    },
    []
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

  const { flushTokenPaint, scheduleTokenPaint } = useStreamingTokenPaint(
    streamingRef,
    setMessagesForCurrent
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

  const finalizeSilently = useCallback((id: string | null) => {
    if (!id) return;
    void finalizeConversation(id)
      .then((result) => {
        setSummaries((prev) =>
          prev.map((item) =>
            item.id === result.conversation.id
              ? { ...item, ...result.conversation }
              : item
          )
        );
      })
      .catch(() => {
        /* best effort: idle maintenance will retry later */
      });
  }, []);

  useEffect(() => {
    if (!authChecked) return;
    const handlePopState = () => {
      const id = conversationIdFromPath(window.location.pathname);
      void runPaneTransition(async () => {
        if (id) {
          await loadConversation(id);
        } else {
          clearActiveConversation();
        }
      });
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [authChecked, clearActiveConversation, loadConversation, runPaneTransition]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "k") return;
      event.preventDefault();
      setSearchOpen(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const scrollThreadToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
    stickToBottomRef.current = true;
    setShowScrollToBottom(false);
  }, []);

  const onThreadScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const nearBottom = distanceFromBottom < 96;
    stickToBottomRef.current = nearBottom;
    setShowScrollToBottom(!nearBottom && el.scrollHeight > el.clientHeight + 24);
  }, []);

  const lastAssistantContentLen = useMemo(() => {
    const last = visibleMessages[visibleMessages.length - 1];
    if (!last || last.role !== "assistant") return 0;
    return last.content.length;
  }, [visibleMessages]);

  useEffect(() => {
    if (!stickToBottomRef.current) return;
    scrollThreadToBottom("auto");
  }, [scrollThreadToBottom, visibleMessages.length, lastAssistantContentLen]);

  useEffect(() => {
    stickToBottomRef.current = true;
    setShowScrollToBottom(false);
    requestAnimationFrame(() => scrollThreadToBottom("auto"));
  }, [currentId, scrollThreadToBottom]);

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

  const handleNew = useCallback((kbId: string | null = currentKbId) => {
    if (currentId && hasConversationMessages && !busy) {
      finalizeSilently(currentId);
    }
    setSidebarOpen(false);
    void runPaneTransition(() => {
      clearActiveConversation();
      setCurrentKbId(kbId);
      setComposerValue("");
      window.history.pushState(null, "", "/c");
    });
  }, [busy, clearActiveConversation, currentId, currentKbId, finalizeSilently, hasConversationMessages, runPaneTransition]);

  const handleSelect = useCallback(
    async (id: string) => {
      setSidebarOpen(false);
      if (id === currentId) return;
      if (currentId && currentId !== id && hasConversationMessages && !busy) {
        finalizeSilently(currentId);
      }
      const ok = await runPaneTransition(() => loadConversation(id));
      if (ok) window.history.pushState(null, "", conversationHref(id));
    },
    [busy, currentId, finalizeSilently, hasConversationMessages, loadConversation, runPaneTransition]
  );

  const handleKbChange = useCallback(
    async (kbId: string | null) => {
      if (currentId && hasConversationMessages) {
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
    [currentId, hasConversationMessages]
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
        void runPaneTransition(async () => {
          if (newId) {
            window.history.replaceState(null, "", conversationHref(newId));
            await loadConversation(newId);
          } else {
            clearActiveConversation();
            window.history.replaceState(null, "", "/c");
          }
        });
      }
    },
    [clearActiveConversation, currentId, loadConversation, runPaneTransition, summaries]
  );

  const handleLogout = useCallback(() => {
    cleanupRef.current?.();
    logout();
    router.replace("/login");
  }, [router]);

  const releaseSendLock = useCallback(() => {
    sendLockRef.current = false;
    setBusy(false);
  }, []);

  const handleSend = useCallback(
    async (q: string) => {
      const trimmed = q.trim();
      if (!trimmed || sendLockRef.current) return;
      sendLockRef.current = true;
      stickToBottomRef.current = true;
      setShowScrollToBottom(false);
      setBusy(true);

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
            finalized_at: created.finalized_at,
            context_status: created.context_status ?? null,
          };
          setSummaries((prev) => [summary, ...prev]);
          setConversationTotal((total) => total + 1);
          currentIdRef.current = created.id;
          setCurrentId(created.id);
          setCurrentKbId(created.kb_id);
          setCurrentModel(created.llm_model ?? null);
          setCurrentContextStatus(created.context_status ?? null);
          window.history.replaceState(null, "", conversationHref(created.id));
        } catch (e) {
          toast.error((e as Error)?.message ?? "\u521b\u5efa\u4f1a\u8bdd\u5931\u8d25");
          releaseSendLock();
          return;
        }
      }

      // Paint the thread immediately so we never flash the empty-workbench
      // between createConversation and appendUserMessage.
      const optimisticUserId = genMessageId();
      const aiId = genMessageId();
      const optimisticUser: Message = {
        id: optimisticUserId,
        role: "user",
        content: trimmed,
        created_at: Date.now(),
      };
      const aiMsg: Message = {
        id: aiId,
        role: "assistant",
        content: "",
        tools: [],
        parts: [],
        streaming: true,
        created_at: Date.now(),
      };
      setMessagesForCurrent((prev) => [...prev, optimisticUser, aiMsg]);
      streamingRef.current = {
        convId: convId!,
        msgId: aiId,
        content: "",
        parts: [],
        tools: [],
        memory_trace: null,
        citations: [],
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
      setComposerValue("");

      try {
        const persisted = await appendUserMessage(convId!, trimmed);
        const userMsg = serverMsgToLocal(persisted) as Message;
        if (userMsg.id !== optimisticUserId) {
          setMessagesForCurrent((prev) =>
            prev.map((m) => (m.id === optimisticUserId ? userMsg : m))
          );
        }
      } catch (e) {
        toast.error((e as Error)?.message ?? "\u4fdd\u5b58\u6d88\u606f\u5931\u8d25");
        setMessagesForCurrent((prev) =>
          prev.filter((m) => m.id !== optimisticUserId && m.id !== aiId)
        );
        bumpSummary(convId!, {}, -1, false);
        streamingRef.current = null;
        releaseSendLock();
        return;
      }

      const priorHistory: SseChatMessage[] = currentMessages
        .filter((m) => {
          if (m.role === "user") return true;
          return !!m.content && !m.error && !m.streaming;
        })
        .map((m) => ({ role: m.role, content: m.content }));
      const messagesForBackend: SseChatMessage[] = [
        ...priorHistory,
        { role: "user", content: trimmed },
      ];

      const persistFinal = async (opts: { error?: string; costUsd?: number }) => {
        const snap = streamingRef.current;
        streamingRef.current = null;
        if (!snap || snap.convId !== convId) return;
        const joined = joinAssistantText(snap.parts, snap.content);
        const flatTools = flattenAssistantTools(snap.parts, snap.tools);
        const hasContent = joined.trim().length > 0;
        const hasTools = flatTools.length > 0;
        if (!hasContent && !hasTools && !opts.error) {
          setMessagesForCurrent((prev) => prev.filter((m) => m.id !== snap.msgId));
          return;
        }
        try {
          const result = await appendAssistantMessage(snap.convId, {
            content: joined,
            tools: flatTools,
            memory_trace: snap.memory_trace,
            citations: snap.citations.length > 0 ? snap.citations : undefined,
            cost_usd: opts.costUsd,
            error: opts.error,
          });
          setMessagesForCurrent((prev) =>
            prev.map((m) =>
              m.id === snap.msgId
                ? {
                    ...m,
                    id: result.id,
                    content: joined,
                    tools: flatTools,
                    parts: undefined,
                    streaming: false,
                    memory_trace: result.memory_trace ?? snap.memory_trace,
                    citations: result.citations ?? snap.citations,
                  }
                : m
            )
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
              const cachedMessages = messagesCache.current.get(snap.convId) ?? [];
              setCurrentContextStatus(
                estimateContextStatus(
                  cachedMessages,
                  currentModel,
                  modelOptionsRef.current,
                  currentKbId
                )
              );
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
              flushTokenPaint();
              const newTool: ToolEvent = {
                id: evt.id,
                name: evt.name!,
                input: evt.input,
                status: "running",
                t0: Date.now(),
              };
              if (streamingRef.current) {
                const snap = streamingRef.current;
                // Seal any open text before tools if backend didn't send segment_seal.
                if (snap.content.trim()) {
                  snap.parts = [...snap.parts, { type: "text", text: snap.content }];
                  snap.content = "";
                }
                const last = snap.parts[snap.parts.length - 1];
                if (last?.type === "tools") {
                  last.tools = [...last.tools, newTool];
                  snap.parts = [...snap.parts.slice(0, -1), last];
                } else {
                  snap.parts = [...snap.parts, { type: "tools", tools: [newTool] }];
                }
                snap.tools = [...snap.tools, newTool];
              }
              updateLastAssistant((m) => {
                if (m.role !== "assistant") return m;
                let parts = [...(m.parts ?? [])];
                let content = m.content;
                if (content.trim()) {
                  parts = [...parts, { type: "text", text: content }];
                  content = "";
                }
                const last = parts[parts.length - 1];
                if (last?.type === "tools") {
                  parts = [
                    ...parts.slice(0, -1),
                    { type: "tools", tools: [...last.tools, newTool] },
                  ];
                } else {
                  parts = [...parts, { type: "tools", tools: [newTool] }];
                }
                return { ...m, content, parts, tools: [...m.tools, newTool] };
              });
              break;
            }
            case "tool_end": {
              const incoming = evt.citations ?? [];
              if (streamingRef.current) {
                streamingRef.current.tools = updateToolEvent(streamingRef.current.tools, evt, {
                  status: evt.ok ? "ok" : "error",
                  latency_ms: evt.latency_ms ?? null,
                  error: evt.error ?? null,
                });
                streamingRef.current.parts = streamingRef.current.parts.map((part) =>
                  part.type === "tools"
                    ? {
                        type: "tools",
                        tools: updateToolEvent(part.tools, evt, {
                          status: evt.ok ? "ok" : "error",
                          latency_ms: evt.latency_ms ?? null,
                          error: evt.error ?? null,
                        }),
                      }
                    : part
                );
                if (incoming.length > 0) {
                  streamingRef.current.citations = mergeCitations(
                    streamingRef.current.citations,
                    incoming
                  );
                }
              }
              updateLastAssistant((m) => {
                if (m.role !== "assistant") return m;
                return {
                  ...m,
                  tools: updateToolEvent(m.tools, evt, {
                    status: evt.ok ? "ok" : "error",
                    latency_ms: evt.latency_ms ?? null,
                    error: evt.error ?? null,
                  }),
                  parts: (m.parts ?? []).map((part) =>
                    part.type === "tools"
                      ? {
                          type: "tools",
                          tools: updateToolEvent(part.tools, evt, {
                            status: evt.ok ? "ok" : "error",
                            latency_ms: evt.latency_ms ?? null,
                            error: evt.error ?? null,
                          }),
                        }
                      : part
                  ),
                  citations:
                    incoming.length > 0
                      ? mergeCitations(m.citations, incoming)
                      : m.citations,
                };
              });
              break;
            }
            case "tool_blocked": {
              flushTokenPaint();
              const newTool: ToolEvent = {
                id: evt.id,
                name: evt.name!,
                input: evt.input,
                status: "blocked",
                reason: evt.reason ?? "",
              };
              if (streamingRef.current) {
                const snap = streamingRef.current;
                if (snap.content.trim()) {
                  snap.parts = [...snap.parts, { type: "text", text: snap.content }];
                  snap.content = "";
                }
                const last = snap.parts[snap.parts.length - 1];
                if (last?.type === "tools") {
                  last.tools = [...last.tools, newTool];
                  snap.parts = [...snap.parts.slice(0, -1), last];
                } else {
                  snap.parts = [...snap.parts, { type: "tools", tools: [newTool] }];
                }
                snap.tools = [...snap.tools, newTool];
              }
              updateLastAssistant((m) => {
                if (m.role !== "assistant") return m;
                let parts = [...(m.parts ?? [])];
                let content = m.content;
                if (content.trim()) {
                  parts = [...parts, { type: "text", text: content }];
                  content = "";
                }
                const last = parts[parts.length - 1];
                if (last?.type === "tools") {
                  parts = [
                    ...parts.slice(0, -1),
                    { type: "tools", tools: [...last.tools, newTool] },
                  ];
                } else {
                  parts = [...parts, { type: "tools", tools: [newTool] }];
                }
                return { ...m, content, parts, tools: [...m.tools, newTool] };
              });
              break;
            }
            case "segment_seal": {
              flushTokenPaint();
              if (streamingRef.current?.content.trim()) {
                const snap = streamingRef.current;
                snap.parts = [...snap.parts, { type: "text", text: snap.content }];
                snap.content = "";
              }
              updateLastAssistant((m) => {
                if (m.role !== "assistant" || !m.content.trim()) return m;
                return {
                  ...m,
                  parts: [...(m.parts ?? []), { type: "text", text: m.content }],
                  content: "",
                };
              });
              break;
            }
            case "token": {
              if (streamingRef.current) streamingRef.current.content += evt.text ?? "";
              scheduleTokenPaint();
              break;
            }
            case "error": {
              flushTokenPaint();
              const errMsg = evt.message ?? "\u751f\u6210\u5931\u8d25";
              if (errMsg === "generation_in_progress") {
                const friendly = "当前会话正在生成回答，请稍后再发送";
                toast.info(friendly);
                flushTokenPaint(false);
                setMessagesForCurrent((prev) => prev.filter((m) => m.id !== aiId));
                streamingRef.current = null;
                cleanupRef.current = null;
                releaseSendLock();
                break;
              }
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
              cleanupRef.current = null;
              releaseSendLock();
              break;
            }
            case "done": {
              flushTokenPaint();
              const costUsd = typeof evt.cost_usd === "number" ? evt.cost_usd : undefined;
              const memoryTrace = evt.memory_trace ?? null;
              const finalCitations =
                evt.citations && evt.citations.length > 0
                  ? evt.citations
                  : streamingRef.current?.citations ?? [];
              if (streamingRef.current) {
                streamingRef.current.memory_trace = memoryTrace;
                streamingRef.current.citations = finalCitations;
              }
              const snap = streamingRef.current;
              const emptyResponse = !snap?.content.trim();
              if (emptyResponse) {
                updateLastAssistant((m) =>
                  m.role === "assistant"
                    ? {
                        ...m,
                        error: EMPTY_ASSISTANT_RESPONSE,
                        streaming: false,
                        cost_usd: costUsd,
                        memory_trace: memoryTrace,
                        citations: finalCitations,
                      }
                    : m
                );
                void persistFinal({ error: EMPTY_ASSISTANT_RESPONSE, costUsd });
                cleanupRef.current = null;
                releaseSendLock();
                break;
              }
              updateLastAssistant((m) =>
                m.role === "assistant"
                  ? {
                      ...m,
                      streaming: false,
                      cost_usd: costUsd,
                      memory_trace: memoryTrace,
                      citations: finalCitations,
                    }
                  : m
              );
              void persistFinal({ costUsd });
              cleanupRef.current = null;
              releaseSendLock();
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
      currentId,
      currentKbId,
      currentMessages,
      currentModel,
      summaries,
      setMessagesForCurrent,
      updateLastAssistant,
      flushTokenPaint,
      scheduleTokenPaint,
      bumpSummary,
      releaseSendLock,
      router,
    ]
  );

  const handleStop = useCallback(() => {
    cleanupRef.current?.();
    cleanupRef.current = null;
    flushTokenPaint();
    releaseSendLock();
    const snap = streamingRef.current;
    if (snap) {
      streamingRef.current = null;
      const hasContent = snap.content.trim().length > 0;
      if (!hasContent) {
        setMessagesForCurrent((prev) => prev.filter((m) => m.id !== snap.msgId));
        return;
      }
      updateLastAssistant((m) =>
        m.role === "assistant" && m.id === snap.msgId ? { ...m, streaming: false } : m
      );
      void appendAssistantMessage(snap.convId, {
        content: snap.content,
        tools: snap.tools,
        citations: snap.citations.length > 0 ? snap.citations : undefined,
      })
        .then((result) => {
          setMessagesForCurrent((prev) =>
            prev.map((m) =>
              m.id === snap.msgId
                ? {
                    ...m,
                    id: result.id,
                    citations: result.citations ?? snap.citations,
                  }
                : m
            )
          );
          bumpSummary(snap.convId, {}, 1, true);
        })
        .catch((e) => console.error("persist stopped turn failed", e));
    }
  }, [updateLastAssistant, setMessagesForCurrent, bumpSummary, releaseSendLock, flushTokenPaint]);

  const submitComposer = useCallback(() => {
    void handleSend(composerValue);
  }, [composerValue, handleSend]);

  const showBootShell = !authChecked || bootPhase !== "gone";
  const showChatApp = authChecked && initialLoadDone;

  if (!authChecked) {
    return (
      <ChatLoadingShell
        label={`正在打开 ${APP_NAME}`}
        description="正在恢复你的知识库和会话。"
      />
    );
  }

  return (
    <div className="relative h-dvh w-screen overflow-hidden" data-kf-root>
      {showChatApp && (
      <div
        className="kf-chat kf-chat-root kf-page-transition h-dvh w-screen overflow-hidden"
        data-kf-shell
      >
      {sidebarOpen && (
        <button
          aria-label="关闭侧栏遮罩"
          tabIndex={-1}
          className="kf-mobile-overlay fixed inset-0 z-30 lg:hidden"
          data-kf-region="overlay"
          onClick={() => setSidebarOpen(false)}
          type="button"
        />
      )}

      <div
        className="grid h-full grid-cols-1 lg:grid-cols-[286px_minmax(0,1fr)]"
        data-kf-layout="chat"
      >
        <ChatSidebar
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
          onOpenAccountSettings={() => setSystemSettingsOpen(true)}
          onOpenSearch={() => setSearchOpen(true)}
          onLogout={handleLogout}
        />

        <ConversationSearchDialog
          open={searchOpen}
          onOpenChange={setSearchOpen}
          conversations={sidebarConversations}
          onSelect={handleSelect}
        />

        <section
          className="kf-chat-pane flex h-[100dvh] max-h-[100dvh] min-h-0 min-w-0 flex-col overflow-hidden"
          data-kf-region="pane"
          data-phase={panePhase}
          aria-label="对话工作区"
        >
          <ChatTopBar
            title={currentConversation?.title ?? DEFAULT_TITLE}
            onOpenSidebar={() => setSidebarOpen(true)}
            conversation={currentConversation}
            kbName={currentKb?.name ?? "通用对话"}
            modelLabel={
              currentModel ||
              (llmSource === "system"
                ? "系统默认"
                : llmSource === "user"
                  ? "默认模型"
                  : "未配置")
            }
            messageStats={formatMessageStats(visibleMessages)}
          />

          <div className="min-h-0 flex-1" data-kf-region="workspace-host">
            <main
              className="kf-main kf-workspace flex h-full min-h-0 min-w-0 flex-col"
              data-kf-region="workspace"
            >
              {missingConversationId ? (
                <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
                  <div className="mx-auto flex min-h-full w-full max-w-[860px] items-center justify-center">
                    <StateView
                      variant="error"
                      title="会话不可用"
                      description="这个会话可能已被删除、你没有访问权限，或链接已经失效。"
                      className="w-full max-w-md"
                      action={
                        <Button type="button" onClick={() => handleNew(null)}>
                          新建对话
                        </Button>
                      }
                    />
                  </div>
                </div>
              ) : (!currentId && visibleMessages.length === 0) ? (
                <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
                  <div className="mx-auto flex w-full max-w-[920px] flex-col">
                    <EmptyWorkbench
                      centered
                      currentKbName={currentKb?.name ?? "\u901a\u7528\u5bf9\u8bdd"}
                      onPick={handleSend}
                    />
                    <Composer
                      centered
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
                      kbLocked={false}
                      onChange={setComposerValue}
                      onSubmit={submitComposer}
                      onStop={handleStop}
                      onSelectKb={handleKbChange}
                      onModelChange={handleModelChange}
                    />
                    <StarterPromptCards onPick={handleSend} />
                  </div>
                </div>
              ) : (
                <div className="kf-thread relative min-h-0 flex-1" data-kf-region="thread">
                  <div
                    ref={scrollRef}
                    onScroll={onThreadScroll}
                    className="kf-thread-scroll absolute inset-0 overflow-y-auto"
                    data-kf-region="thread-scroll"
                    role="log"
                    aria-live="polite"
                    aria-relevant="additions"
                  >
                    <div className="kf-thread-inner mx-auto flex w-full max-w-[860px] flex-col gap-7 px-5 pt-5" data-kf-region="thread-inner">
                      <ContextCompressionNotice contextStatus={currentContextStatus} />
                      {visibleMessages.length === 0 ? (
                        <EmptyWorkbench currentKbName={currentKb?.name ?? "\u901a\u7528\u5bf9\u8bdd"} onPick={handleSend} />
                      ) : (
                        visibleMessages.map((message) => <ChatMessage key={message.id} message={message} />)
                      )}
                    </div>
                  </div>
                  <div className="kf-thread-dock pointer-events-none absolute bottom-0 left-0 z-10" data-kf-region="thread-dock">
                    {showScrollToBottom ? (
                      <div className="pointer-events-none flex justify-center pb-2">
                        <button
                          type="button"
                          aria-label="滚动到底部"
                          className="kf-scroll-to-bottom kf-press pointer-events-auto inline-grid size-9 place-items-center rounded-full border p-0 shadow-sm"
                          onClick={() => scrollThreadToBottom("smooth")}
                        >
                          <ArrowDown aria-hidden className="block h-4 w-4 shrink-0" strokeWidth={2} />
                        </button>
                      </div>
                    ) : null}
                    <div className="pointer-events-auto">
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
                    </div>
                  </div>
                </div>
              )}
            </main>
          </div>
        </section>
      </div>
      {user && (
        <SystemSettingsDialog
          open={systemSettingsOpen}
          onClose={() => setSystemSettingsOpen(false)}
          user={user}
          onUserChanged={setUser}
        />
      )}
      </div>
      )}
      {showBootShell && (
        <div
          className={cn(
            showChatApp ? "pointer-events-none absolute inset-0 z-50" : "h-full",
            bootPhase === "leaving" && "kf-chat-boot-leave"
          )}
          aria-hidden={bootPhase === "leaving"}
        >
          <ChatLoadingShell
            animated={bootPhase === "loading" && !initialLoadDone}
            label={`正在打开 ${APP_NAME}`}
            description="正在恢复你的知识库和会话。"
          />
        </div>
      )}
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
        <ChatLoadingShell label="正在打开工作台" />
      }
    >
      <SearchParamChatPage />
    </Suspense>
  );
}