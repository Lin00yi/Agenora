"use client";

import { User, Bot } from "lucide-react";
import ThinkingChain, { type ToolEvent } from "@/components/ThinkingChain";
import ReportView from "@/components/ReportView";
import ExportActions from "@/components/ExportActions";
import type { Message } from "@/lib/conversationStore";
import { cn } from "@/lib/utils";

export default function MessageBubble({
  message,
  prevUserMessage,
}: {
  message: Message;
  prevUserMessage?: string;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="flex max-w-[85%] items-end gap-2.5">
          <div className="rounded-2xl rounded-br-md bg-gradient-to-br from-brand to-brand-dark px-4 py-2.5 text-[15px] leading-relaxed text-white shadow-sm whitespace-pre-wrap break-words">
            {message.content}
          </div>
          <div className="mb-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-full bg-brand/15 text-brand ring-1 ring-brand/20">
            <User className="h-4 w-4" />
          </div>
        </div>
      </div>
    );
  }

  const hasContent = message.content && message.content.length > 0;
  const hasTools = message.tools && message.tools.length > 0;
  const streaming = !!message.streaming;

  const showInitialThinking = streaming && !hasTools && !hasContent && !message.error;
  const showWritingHint =
    streaming &&
    hasTools &&
    !hasContent &&
    !message.error &&
    message.tools.every((t) => t.status !== "running");

  return (
    <div className="flex justify-start">
      <div className="flex w-full max-w-full items-start gap-2.5">
        <div className="mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-full bg-surface-2 text-fg/70 ring-1 ring-surface-border/80">
          <Bot className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1 space-y-3">
          {showInitialThinking && <ThinkingPlaceholder label="正在思考" />}
          {hasTools && <ThinkingChain events={message.tools} />}
          {showWritingHint && <ThinkingPlaceholder label="正在撰写报告" />}

          {message.error && (
            <div className="rounded-xl border border-red-300/40 bg-red-50/80 p-3.5 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">
              {message.error}
            </div>
          )}

          {hasContent && (
            <div className="rounded-2xl rounded-tl-md border border-surface-border/60 bg-surface px-4 py-3 shadow-soft">
              <ReportView markdown={message.content} streaming={streaming} />
            </div>
          )}

          {!hasContent && !streaming && !message.error && (
            <div className="text-sm text-muted">（无内容）</div>
          )}

          {hasContent && !streaming && (
            <ExportActions
              markdown={message.content}
              cost={message.cost_usd ?? null}
              question={prevUserMessage}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function ThinkingPlaceholder({ label }: { label: string }) {
  return (
    <div className="inline-flex items-center gap-2.5 rounded-xl border border-surface-border/60 bg-surface px-3.5 py-2.5 text-sm text-muted shadow-soft">
      <span className="relative inline-flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand opacity-50" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-brand" />
      </span>
      <span>{label}</span>
      <span className="inline-flex gap-0.5">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className={cn(
              "h-1 w-1 animate-bounce rounded-full bg-subtle/60",
              i === 0 && "[animation-delay:-0.3s]",
              i === 1 && "[animation-delay:-0.15s]"
            )}
          />
        ))}
      </span>
    </div>
  );
}
