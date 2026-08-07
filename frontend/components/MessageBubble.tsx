"use client";

import { Bot, LoaderCircle, User } from "lucide-react";
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
          <div className="app-message-user whitespace-pre-wrap break-words rounded-lg rounded-br-sm px-4 py-2.5 text-[15px] leading-relaxed">
            {message.content}
          </div>
          <div className="admin-icon-tile admin-icon-tile-brand mb-0.5 flex-none rounded-md">
            <User className="h-4 w-4" />
          </div>
        </div>
      </div>
    );
  }

  const hasContent = message.content && message.content.length > 0;
  const hasTools = message.tools && message.tools.length > 0;
  const hasParts = (message.parts?.length ?? 0) > 0;
  const streaming = !!message.streaming;
  if (!hasContent && !streaming && !message.error && !hasTools && !hasParts) return null;

  const showInitialThinking =
    streaming && !hasTools && !hasContent && !hasParts && !message.error;
  const showWritingHint =
    streaming &&
    hasTools &&
    !hasContent &&
    !message.error &&
    message.tools.every((t) => t.status !== "running");

  return (
    <div className="flex justify-start">
      <div className="flex w-full max-w-full items-start gap-2.5">
        <div className="admin-icon-tile admin-icon-tile-muted mt-0.5 flex-none rounded-md">
          <Bot className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1 space-y-3">
          {showInitialThinking && <ThinkingPlaceholder label="正在思考" />}
          {(message.parts ?? []).map((part, index) =>
            part.type === "text" ? (
              <div className="text-[15px] leading-relaxed whitespace-pre-wrap" key={`p-${index}`}>
                {part.text}
              </div>
            ) : (
              <ThinkingChain events={part.tools} key={`t-${index}`} />
            )
          )}
          {!hasParts && hasTools && <ThinkingChain events={message.tools} />}
          {showWritingHint && <ThinkingPlaceholder label="正在撰写回答" />}

          {message.error && (
            <div className="app-error-panel rounded-lg border p-3.5 text-sm">
              {message.error}
            </div>
          )}

          {hasContent && (
            <div className="rounded-lg rounded-tl-sm border border-surface-border/70 bg-surface px-4 py-3 shadow-soft">
              <ReportView markdown={message.content} streaming={streaming} />
            </div>
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
    <div className="inline-flex min-h-[var(--control-h)] items-center gap-2.5 rounded-lg border border-surface-border/80 bg-surface px-3.5 py-2 text-sm text-muted shadow-soft">
      <span className="admin-icon-tile admin-icon-tile-sm admin-icon-tile-brand">
        <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
      </span>
      <span>{label}</span>
      <span className="inline-flex gap-0.5">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className={cn(
              "h-1 w-1 animate-bounce rounded-sm bg-subtle/60",
              i === 0 && "[animation-delay:-0.3s]",
              i === 1 && "[animation-delay:-0.15s]"
            )}
          />
        ))}
      </span>
    </div>
  );
}
