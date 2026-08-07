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
import { Button } from "@/components/ui/button";
import { StateView } from "@/components/ui/state-view";
import { ArrowDown } from "lucide-react";
import { toast } from "sonner";
import { APP_NAME } from "@/components/Brand";
import { logout } from "@/lib/auth";
import { cn } from "@/lib/cn";
import {
  deleteConversation,
  finalizeConversation,
  getConversation,
  getConversationContextStatus,
  listConversations,
  patchConversation,
  type ConversationContextStatus,
  type ConversationSummary,
} from "@/lib/conversations-api";
import { type Message } from "@/lib/conversationStore";
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
} from "@/components/chat";
import { useChatBoot } from "@/hooks/useChatBoot";
import { useChatSend } from "@/hooks/useChatSend";
import {
  CHAT_PANE_FADE_MS,
  CONVERSATION_PAGE_SIZE,
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
  const [composerValue, setComposerValue] = useState("");

  const messagesCache = useRef<Map<string, Message[]>>(new Map());
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const paneSwitchSeq = useRef(0);
  const modelOptionsRef = useRef<string[]>([]);
  const currentIdRef = useRef<string | null>(null);

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

  const { busy, handleSend, handleStop, submitComposer, abortStreaming } = useChatSend({
    currentId,
    currentKbId,
    currentMessages,
    currentModel,
    summaries,
    composerValue,
    currentIdRef,
    messagesCache,
    modelOptionsRef,
    stickToBottomRef,
    setShowScrollToBottom,
    setComposerValue,
    setCurrentId,
    setCurrentKbId,
    setCurrentModel,
    setCurrentContextStatus,
    setSummaries,
    setConversationTotal,
    setMessagesForCurrent,
    updateLastAssistant,
    bumpSummary,
  });

  const handleLogout = useCallback(() => {
    abortStreaming();
    logout();
    router.replace("/login");
  }, [abortStreaming, router]);

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