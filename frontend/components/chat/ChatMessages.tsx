"use client";

import React, { useEffect, useState, memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  BrainCircuit,
  ChevronDown,
  ChevronRight,
  Copy,
  LoaderCircle,
  ShieldCheck,
} from "lucide-react";
import ExportActions from "@/components/ExportActions";
import ThinkingChain from "@/components/ThinkingChain";
import { toast } from "@/lib/toast";
import { joinAssistantText, type Message } from "@/lib/conversationStore";
import type { MemoryTrace } from "@/lib/sseClient";
import { cn } from "@/lib/cn";
import { SourceCards } from "./SourceCards";
import {
  buildInjectedMemoryItems,
  formatMemoryTraceSummary,
  formatMessageTime,
  formatTokenCount,
  getAssistantStreamingStatus,
  hasVisibleCitations,
  hasVisibleMemoryTrace,
  memoryTraceTypeLabel,
  stripHandwrittenSourceList,
} from "./utils";

export const ChatMessage = memo(function ChatMessage({ message }: { message: Message }) {
  if (message.role === "user") {
    const copyMessage = async () => {
      try {
        await navigator.clipboard.writeText(message.content);
        toast.success("已复制消息");
      } catch {
        toast.error("复制失败");
      }
    };

    return (
      <div className="flex items-start justify-end">
        <div className="flex max-w-[78%] flex-col items-end">
          <div className="kf-message-user max-w-full whitespace-pre-wrap break-words rounded-[1.25rem] px-4 py-2.5 text-left text-[15px] leading-7 sm:px-5 sm:py-3">
            {message.content}
          </div>
          <div className="kf-message-time mt-1.5 flex items-center gap-1 text-xs tabular-nums">
            <time dateTime={new Date(message.created_at).toISOString()}>
              {formatMessageTime(message.created_at)}
            </time>
            <button
              type="button"
              onClick={copyMessage}
              className="inline-flex size-5 items-center justify-center rounded text-muted hover:bg-surface-2 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40"
              aria-label="复制用户消息"
              title="复制消息"
            >
              <Copy className="size-3" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
    );
  }

  return <ChatAssistantMessage message={message} />;
});

function ChatAssistantMessage({ message }: { message: Extract<Message, { role: "assistant" }> }) {
  const streaming = !!message.streaming;
  const parts = message.parts ?? [];
  const hasParts = parts.length > 0;
  const liveContent = message.content;
  const hasLiveContent = liveContent.trim().length > 0;
  const hasTools = message.tools.length > 0;
  const joined = joinAssistantText(parts, liveContent);
  const hasAnyText = joined.trim().length > 0;
  const hasMemoryContext = hasVisibleMemoryTrace(message.memory_trace);
  const hasContextPart = parts.some((part) => part.type === "context");
  const hasCitations = hasVisibleCitations(message.citations);
  const elapsedMs = useLiveElapsed(streaming, message.created_at);
  const status = getAssistantStreamingStatus(message, elapsedMs);
  const exportMarkdown =
    hasCitations && !streaming ? stripHandwrittenSourceList(joined) : joined;

  // Legacy / persisted messages: no parts → single answer + tools above.
  const legacyLayout = !hasParts;

  if (!hasAnyText && !streaming && !message.error && !hasTools) return null;

  return (
    <div className="flex items-start">
      <div className="min-w-0 flex-1">
        {legacyLayout ? (
          <>
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
              {!hasAnyText && streaming && (
                <div className="kf-streaming-status flex flex-wrap items-center gap-2 text-sm">
                  <LoaderCircle className="h-4 w-4 animate-spin text-[color:var(--chat-accent)] motion-reduce:animate-none" />
                  <span>{status.label}</span>
                </div>
              )}
              {hasAnyText && (
                <AnswerMarkdown markdown={exportMarkdown} streaming={streaming} />
              )}
            </div>
          </>
        ) : (
          <div className="space-y-3">
            {message.error && (
              <div className="kf-answer-error rounded-lg border px-3 py-2 text-sm">
                {message.error}
              </div>
            )}
            {parts.map((part, index) => {
              if (part.type === "context") {
                return <MemoryContextTrace trace={part.trace} key={`context-${index}`} />;
              }
              if (part.type === "text" && parts[index + 1]?.type === "tools") return null;
              if (part.type === "text") {
                return (
                  <div className="kf-answer px-1 py-1 sm:px-2" key={`text-${index}`}>
                    <AnswerMarkdown markdown={part.text} streaming={false} />
                  </div>
                );
              }
              const previous = parts[index - 1];
              return (
                <ThinkingChain
                  events={part.tools}
                  intro={previous?.type === "text" ? previous.text : undefined}
                  key={`tools-${index}`}
                />
              );
            })}
            {!streaming && hasMemoryContext && !hasContextPart ? (
              <MemoryContextTrace trace={message.memory_trace!} />
            ) : null}
            {hasLiveContent && (
              <div className="kf-answer px-1 py-1 sm:px-2">
                <AnswerMarkdown markdown={liveContent} streaming={streaming} />
              </div>
            )}
            {!hasLiveContent && streaming && (
              <div className="kf-streaming-status flex flex-wrap items-center gap-2 px-1 text-sm">
                <LoaderCircle className="h-4 w-4 animate-spin text-[color:var(--chat-accent)] motion-reduce:animate-none" />
                <span>{status.label}</span>
              </div>
            )}
          </div>
        )}

        {hasAnyText && !streaming && hasCitations ? (
          <SourceCards citations={message.citations!} />
        ) : null}

        {hasAnyText && !streaming && (
          <ExportActions markdown={exportMarkdown} cost={message.cost_usd} />
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

const AnswerMarkdown = memo(function AnswerMarkdown({
  markdown,
  streaming,
}: {
  markdown: string;
  streaming: boolean;
}) {
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
          a: ({ href, children }) => (
            <a
              className="kf-answer-link underline underline-offset-2"
              href={href}
              rel="noopener noreferrer"
              target="_blank"
            >
              {children}
            </a>
          ),
          pre: ({ children }) => <pre className="kf-answer-pre mb-4 overflow-x-auto">{children}</pre>,
          code: ({ className, children }) => {
            const isBlock = typeof className === "string" && className.length > 0;
            if (isBlock) {
              return <code className={cn("kf-answer-code-block", className)}>{children}</code>;
            }
            return <code className="kf-answer-code rounded px-1.5 py-0.5 text-sm">{children}</code>;
          },
          table: ({ children }) => (
            <div className="kf-answer-table-wrap mb-4 overflow-x-auto">
              <table className="kf-answer-table">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="kf-answer-thead">{children}</thead>,
          tbody: ({ children }) => <tbody className="kf-answer-tbody">{children}</tbody>,
          tr: ({ children }) => <tr className="kf-answer-tr">{children}</tr>,
          th: ({ children }) => <th className="kf-answer-th">{children}</th>,
          td: ({ children }) => <td className="kf-answer-td">{children}</td>,
        }}
      >
        {markdown.replace(/\\n/g, "\n")}
      </ReactMarkdown>
      {streaming && <span className="kf-streaming-cursor inline-block h-4 w-1.5 animate-pulse" />}
    </div>
  );
});

function MemoryContextTrace({ trace }: { trace: MemoryTrace }) {
  const [open, setOpen] = useState(false);
  const items = buildInjectedMemoryItems(trace);
  const summaryText = formatMemoryTraceSummary(trace);
  const truncatedBlocks = trace.prompt
    ? [
        trace.prompt.truncation.profile ? "偏好" : "",
        trace.prompt.truncation.memory ? "长期记忆" : "",
        trace.prompt.truncation.summary ? "会话摘要" : "",
        trace.prompt.truncation.rag ? "检索资料" : "",
        trace.prompt.truncation.history ? "历史消息" : "",
      ].filter(Boolean)
    : [];

  return (
    <section aria-label="上下文准备" className="py-1 text-sm">
      <button
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-8 items-center gap-2 text-left text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40"
        type="button"
      >
        <span className="flex min-w-0 items-center gap-2">
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0" />
          )}
          <BrainCircuit className="h-3.5 w-3.5 shrink-0 text-brand/80" />
          <span className="truncate text-xs sm:text-sm">上下文已准备 · {summaryText}</span>
        </span>
      </button>

      <div className={cn("mt-2 border-t border-surface-border/60", open && "pt-2.5")}>
        {open ? (
          <div className="space-y-2 text-sm">
            {trace.runtime ? (
              <div className="flex items-start gap-2 text-xs leading-5 text-muted">
                <ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-brand/80" aria-hidden="true" />
                <span>
                  运行规则与安全边界已加载
                  {trace.runtime.safety === "heightened" ? "，已加强防护。" : "。"}
                </span>
              </div>
            ) : null}
            {trace.recent_message_count ? (
              <p className="text-xs leading-5 text-muted">
                保留最近 {trace.recent_message_count} 条对话作为本轮参考。
              </p>
            ) : null}
            {items.length > 0 ? (
              <ul className="space-y-1.5">
                {items.slice(0, 6).map((item) => (
                  <li key={item.id} className="border-l border-surface-border/70 pl-2.5">
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
              <p className="text-xs leading-5 text-muted">
                会话摘要已注入 · 覆盖 {trace.summary.covered_message_count} 条历史 / 约{" "}
                {formatTokenCount(trace.summary.token_count)}
              </p>
            ) : null}

            {trace.prompt ? (
              <div className="space-y-1 text-xs leading-5 text-muted">
                <p className="text-pretty">
                本轮请求 · 输入 {formatTokenCount(trace.prompt.tokens.total_input)} / 窗口{" "}
                {formatTokenCount(trace.prompt.context_window)}；系统 {formatTokenCount(trace.prompt.tokens.system)}、
                工具 {formatTokenCount(trace.prompt.tokens.tools)}、RAG {formatTokenCount(trace.prompt.tokens.rag)}、
                历史 {formatTokenCount(trace.prompt.tokens.history)}。
                {truncatedBlocks.length > 0 ? ` 已按预算裁剪${truncatedBlocks.join("、")}。` : ""}
                </p>
                {trace.prompt.retrieval ? (
                  <p className="text-pretty">
                    预取检索证据 {trace.prompt.retrieval.evidence_count} 条，
                    {trace.prompt.retrieval.in_system ? "当前使用兼容 system 注入。" : "作为普通参考消息注入，当前问题已固定保留。"}
                  </p>
                ) : null}
                {trace.prompt.cache && (trace.prompt.cache.cache_read_tokens > 0 || trace.prompt.cache.cache_creation_tokens > 0) ? (
                  <p className="text-pretty tabular-nums">
                    提示缓存 · 命中 {formatTokenCount(trace.prompt.cache.cache_read_tokens)} / 创建 {formatTokenCount(trace.prompt.cache.cache_creation_tokens)}。
                  </p>
                ) : null}
              </div>
            ) : null}

            {items.length === 0 && !trace.summary ? (
              <p className="text-xs leading-5 text-muted">本轮没有相关记忆或会话摘要。</p>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
