"use client";

import { Send, Square } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { cn } from "@/lib/utils";

type Props = {
  onSend: (q: string) => void;
  onStop?: () => void;
  busy?: boolean;
  placeholder?: string;
};

const DEFAULT_PLACEHOLDER = "输入问题，例如：总结一下这份知识库的主要内容";
const MAX_HEIGHT = 200;

export default function ChatBox({ onSend, onStop, busy, placeholder }: Props) {
  const [value, setValue] = useState("");
  const [focused, setFocused] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  useEffect(() => {
    if (!busy) taRef.current?.focus();
  }, [busy]);

  const submit = () => {
    const q = value.trim();
    if (!q || busy) return;
    onSend(q);
    setValue("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const hasText = value.trim().length > 0;

  return (
    <div
      className={cn(
        "input-shell overflow-hidden shadow-soft transition-[border-color,box-shadow] duration-200",
        focused && "shadow-lift"
      )}
    >
      <textarea
        ref={taRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        placeholder={placeholder ?? DEFAULT_PLACEHOLDER}
        rows={1}
        disabled={busy && !onStop}
        className="block w-full resize-none bg-transparent px-4 pb-2 pt-4 text-[15px] leading-relaxed outline-none placeholder:text-muted disabled:opacity-50"
        style={{ maxHeight: MAX_HEIGHT }}
        aria-label="输入消息"
      />
      <div className="flex min-h-12 items-center justify-between gap-2 border-t border-surface-border/60 bg-surface-2/45 px-3 py-2">
        <span className="hidden text-xs text-muted sm:inline">
          Enter 发送 · Shift+Enter 换行
          {value.length > 0 && <span className="ml-2 text-muted/75">{value.length} 字</span>}
        </span>
        <span className="text-xs text-muted sm:hidden">
          {value.length > 0 ? `${value.length} 字` : "回车发送"}
        </span>
        {busy && onStop ? (
          <button
            type="button"
            onClick={onStop}
            className="admin-btn-secondary ml-auto h-[var(--control-h)] px-3"
            aria-label="停止生成"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
            停止
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={!hasText}
            className="admin-btn-primary ml-auto h-[var(--control-h)] px-4"
            aria-label="发送消息"
          >
            <Send className="h-3.5 w-3.5" />
            发送
          </button>
        )}
      </div>
    </div>
  );
}
