"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  BrainCircuit,
  ChevronDown,
  ChevronRight,
  LoaderCircle,
  ShieldCheck,
} from "lucide-react";
import ExportActions from "@/components/ExportActions";
import ThinkingChain from "@/components/ThinkingChain";
import type { ConversationContextStatus } from "@/lib/conversations-api";
import type { Message } from "@/lib/conversationStore";
import type { MemoryTrace } from "@/lib/sseClient";
import { cn } from "@/lib/cn";
import {
  buildInjectedMemoryItems,
  formatMemoryTraceSummary,
  formatMessageTime,
  formatTokenCount,
  getAssistantStreamingStatus,
  hasVisibleMemoryTrace,
  memoryTraceTypeLabel,
} from "./utils";

export function ChatMessage({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="flex items-start justify-end">
        <div className="flex max-w-[78%] flex-col items-end">
          <div className="kf-message-user max-w-full whitespace-pre-wrap break-words rounded-[1.25rem] px-4 py-2.5 text-left text-[15px] leading-7 sm:px-5 sm:py-3">
            {message.content}
          </div>
          <div className="kf-message-time mt-1.5 text-xs">{formatMessageTime(message.created_at)}</div>
        </div>
      </div>
    );
  }

  return <ChatAssistantMessage message={message} />;
}

function ChatAssistantMessage({ message }: { message: Extract<Message, { role: "assistant" }> }) {
  const streaming = !!message.streaming;
  const hasContent = message.content.trim().length > 0;
  const hasTools = message.tools.length > 0;
  const hasMemoryContext = hasVisibleMemoryTrace(message.memory_trace);
  const elapsedMs = useLiveElapsed(streaming, message.created_at);
  const status = getAssistantStreamingStatus(message, elapsedMs);
  if (!hasContent && !streaming && !message.error && !hasTools) return null;

  return (
    <div className="flex items-start">
      <div className="min-w-0 flex-1">
        {/* Process chips stay above the answer; quiet by default. */}
        {(hasTools || (!streaming && hasMemoryContext)) && (
          <div className="mb-3 space-y-2">
            {hasTools ? <ThinkingChain events={message.tools} /> : null}
            {!streaming && hasMemoryContext ? (
              <MemoryContextTrace trace={message.memory_trace!} />
            ) : null}
          </div>
        )}

        <div className="kf-answer px-1 py-1 sm:px-2">
          {message.error && (
            <div className="kf-answer-error mb-3 rounded-lg border px-3 py-2 text-sm">
              {message.error}
            </div>
          )}
          {!hasContent && streaming && (
            <div className="kf-streaming-status flex flex-wrap items-center gap-2 text-sm">
              <LoaderCircle className="h-4 w-4 animate-spin text-[color:var(--chat-accent)]" />
              <span>{status.label}</span>
              <span className="kf-live-badge rounded-md border px-2 py-0.5 text-xs tabular-nums">
                {status.elapsed}
              </span>
            </div>
          )}
          {hasContent && (
            <div id={`report-output-${message.id}`}>
              <AnswerMarkdown markdown={message.content} streaming={streaming} />
            </div>
          )}
          {hasContent && streaming && (
            <div className="kf-live-badge mt-3 inline-flex items-center gap-2 rounded-md border px-2.5 py-1 text-xs tabular-nums">
              <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
              <span>{status.label}</span>
              <span>{status.elapsed}</span>
            </div>
          )}
        </div>

        {hasContent && !streaming && (
          <ExportActions
            markdown={message.content}
            cost={message.cost_usd}
            reportId={`report-output-${message.id}`}
          />
        )}
      </div>
    </div>
  );
}

function useLiveElapsed(active: boolean, startedAt: number) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [active, startedAt]);

  return Math.max(0, (active ? now : Date.now()) - startedAt);
}

function AnswerMarkdown({ markdown, streaming }: { markdown: string; streaming: boolean }) {
  return (
    <div className="kf-answer-markdown text-[15px] leading-7">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="mb-4 last:mb-0">{children}</p>,
          ul: ({ children }) => <ul className="mb-4 list-disc space-y-1 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="mb-4 list-decimal space-y-1 pl-5">{children}</ol>,
          li: ({ children }) => <li className="kf-answer-list-item pl-1">{children}</li>,
          strong: ({ children }) => <strong className="kf-answer-strong font-semibold">{children}</strong>,
          h1: ({ children }) => <h1 className="kf-answer-heading mb-3 text-xl font-semibold">{children}</h1>,
          h2: ({ children }) => <h2 className="kf-answer-heading mb-3 mt-5 text-lg font-semibold">{children}</h2>,
          h3: ({ children }) => <h3 className="kf-answer-heading mb-2 mt-4 text-base font-semibold">{children}</h3>,
          code: ({ children }) => (
            <code className="kf-answer-code rounded px-1.5 py-0.5 text-sm">
              {children}
            </code>
          ),
        }}
      >
        {markdown.replace(/\\n/g, "\n")}
      </ReactMarkdown>
      {streaming && <span className="kf-streaming-cursor inline-block h-4 w-1.5 animate-pulse" />}
    </div>
  );
}

export function ContextCompressionNotice({
  contextStatus,
}: {
  contextStatus: ConversationContextStatus | null;
}) {
  if (!contextStatus || contextStatus.state === "normal") return null;
  const isCompressed = contextStatus.state === "compressed";
  return (
    <div className="kf-context-notice mx-auto flex w-fit max-w-full items-center gap-2 rounded-lg border px-3 py-2 text-xs">
      <ShieldCheck
        className={cn(
          "h-3.5 w-3.5",
          isCompressed ? "text-brand" : "text-amber-300"
        )}
      />
      <span className="truncate">
        {isCompressed
          ? `已自动压缩长期上下文，保留最近 ${contextStatus.retained_recent_turns} 轮对话`
          : contextStatus.description}
      </span>
    </div>
  );
}

function MemoryContextTrace({ trace }: { trace: MemoryTrace }) {
  const [open, setOpen] = useState(false);
  const items = buildInjectedMemoryItems(trace);
  const summaryText = formatMemoryTraceSummary(trace);

  return (
    <div className="overflow-hidden rounded-lg border border-surface-border/70 bg-surface/80">
      <button
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-9 w-full cursor-pointer items-center justify-between gap-3 px-3 py-1.5 text-sm transition-colors hover:bg-surface-2/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40"
        type="button"
      >
        <span className="flex min-w-0 items-center gap-2 text-muted">
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0" />
          )}
          <BrainCircuit className="h-3.5 w-3.5 shrink-0 text-brand/80" />
          <span className="truncate text-xs sm:text-sm">{summaryText}</span>
        </span>
      </button>

      {open ? (
        <div className="space-y-2 border-t border-surface-border/60 px-3 py-2.5 text-sm">
          {items.length > 0 ? (
            <ul className="space-y-1.5">
              {items.slice(0, 6).map((item) => (
                <li
                  key={item.id}
                  className="rounded-md border border-surface-border/60 bg-surface-2/35 px-2.5 py-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-xs font-medium text-ink/85">
                      {memoryTraceTypeLabel(item.type)}
                    </span>
                    <span className="shrink-0 text-[11px] tabular-nums text-muted">
                      重要度 {Math.round((item.importance ?? 0) * 100)}%
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted">{item.content}</p>
                </li>
              ))}
            </ul>
          ) : null}

          {trace.summary ? (
            <p className="rounded-md border border-surface-border/60 bg-surface-2/35 px-2.5 py-2 text-xs leading-5 text-muted">
              会话摘要已注入 · 覆盖 {trace.summary.covered_message_count} 条历史 / 约{" "}
              {formatTokenCount(trace.summary.token_count)}
            </p>
          ) : null}

          {items.length === 0 && !trace.summary ? (
            <p className="text-xs leading-5 text-muted">本轮未注入可展示的记忆内容。</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
