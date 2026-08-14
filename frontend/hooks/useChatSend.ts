"use client";

import { useCallback, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { useRouter } from "next/navigation";
import { toast } from "@/lib/toast";

import { type ToolEvent } from "@/components/ThinkingChain";
import { DEFAULT_TITLE, mergeCitations, updateToolEvent } from "@/components/chat";
import { useStreamingTokenPaint } from "@/hooks/useStreamingTokenPaint";
import {
  appendAssistantMessage,
  appendUserMessage,
  createConversation,
  getConversationContextStatus,
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
  EMPTY_ASSISTANT_RESPONSE,
  conversationHref,
  estimateContextStatus,
  serverMsgToLocal,
} from "@/lib/chatPageHelpers";

type StreamingSnap = {
  convId: string;
  msgId: string;
  content: string;
  parts: AssistantPart[];
  tools: ToolEvent[];
  memory_trace: MemoryTrace | null;
  citations: Citation[];
};

type Args = {
  currentId: string | null;
  currentKbId: string | null;
  currentMessages: Message[];
  currentModel: string | null;
  currentProfileId: string | null;
  summaries: ConversationSummary[];
  composerValue: string;
  currentIdRef: MutableRefObject<string | null>;
  messagesCache: MutableRefObject<Map<string, Message[]>>;
  modelOptionsRef: MutableRefObject<string[]>;
  stickToBottomRef: MutableRefObject<boolean>;
  setShowScrollToBottom: Dispatch<SetStateAction<boolean>>;
  setComposerValue: Dispatch<SetStateAction<string>>;
  setCurrentId: Dispatch<SetStateAction<string | null>>;
  setCurrentKbId: Dispatch<SetStateAction<string | null>>;
  setCurrentModel: Dispatch<SetStateAction<string | null>>;
  setCurrentProfileId: Dispatch<SetStateAction<string | null>>;
  setCurrentContextStatus: Dispatch<SetStateAction<ConversationContextStatus | null>>;
  setSummaries: Dispatch<SetStateAction<ConversationSummary[]>>;
  setConversationTotal: Dispatch<SetStateAction<number>>;
  setMessagesForCurrent: (next: Message[] | ((prev: Message[]) => Message[])) => void;
  updateLastAssistant: (mutator: (m: Message) => Message) => void;
  bumpSummary: (
    convId: string,
    patch: Partial<ConversationSummary>,
    messageCountDelta?: number,
    moveToTop?: boolean
  ) => void;
};

/**
 * Owns send lock, SSE streaming state, optimistic first-turn paint, stop, and composer submit.
 */
export function useChatSend({
  currentId,
  currentKbId,
  currentMessages,
  currentModel,
  currentProfileId,
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
  setCurrentProfileId,
  setCurrentContextStatus,
  setSummaries,
  setConversationTotal,
  setMessagesForCurrent,
  updateLastAssistant,
  bumpSummary,
}: Args) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const sendLockRef = useRef(false);
  const cleanupRef = useRef<(() => void) | null>(null);
  const streamingRef = useRef<StreamingSnap | null>(null);
  const { flushTokenPaint, scheduleTokenPaint } = useStreamingTokenPaint(
    streamingRef,
    setMessagesForCurrent
  );

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
            llm_profile_id: created.llm_profile_id,
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
          setCurrentProfileId(created.llm_profile_id ?? null);
          setCurrentContextStatus(created.context_status ?? null);
          window.history.replaceState(null, "", conversationHref(created.id));
          if (currentProfileId) {
            const updated = await patchConversation(created.id, { llm_profile_id: currentProfileId });
            setCurrentModel(updated.llm_model);
            setCurrentProfileId(updated.llm_profile_id);
            setSummaries((prev) => prev.map((item) => item.id === created.id ? { ...item, llm_model: updated.llm_model, llm_profile_id: updated.llm_profile_id } : item));
          }
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
        { conversationId: convId!, kbId: currentKbId, model: currentModel, modelProfileId: currentProfileId }
      );

      cleanupRef.current = cleanup;
    },
    [
      currentId,
      currentKbId,
      currentMessages,
      currentModel,
      currentProfileId,
      summaries,
      setMessagesForCurrent,
      updateLastAssistant,
      flushTokenPaint,
      scheduleTokenPaint,
      bumpSummary,
      releaseSendLock,
      router,
      setCurrentModel,
      setCurrentProfileId,
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


  const abortStreaming = useCallback(() => {
    cleanupRef.current?.();
    cleanupRef.current = null;
    flushTokenPaint(false);
    streamingRef.current = null;
  }, [flushTokenPaint]);

  return {
    busy,
    handleSend,
    handleStop,
    submitComposer,
    abortStreaming,
  };
}
