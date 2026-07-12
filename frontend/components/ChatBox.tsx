"use client";

import { Send, Square } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Props = {
  onSend: (q: string) => void;
  onStop?: () => void;
  busy?: boolean;
  placeholder?: string;
};

const DEFAULT_PLACEHOLDER = "问点什么... 例如：总结一下这份知识库的主要内容";
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
        "input-shell overflow-hidden shadow-soft transition-shadow duration-300",
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
        className="block w-full resize-none bg-transparent px-4 pb-1 pt-3.5 text-[15px] leading-relaxed outline-none placeholder:text-muted disabled:opacity-50"
        style={{ maxHeight: MAX_HEIGHT }}
        aria-label="输入消息"
      />
      <div className="flex items-center justify-between gap-2 border-t border-surface-border/50 bg-surface-2/35 px-3 py-2">
        <span className="hidden text-xs text-muted sm:inline">
          Enter 发送 · Shift+Enter 换行
          {value.length > 0 && <span className="ml-2 text-muted/75">{value.length} 字</span>}
        </span>
        <span className="text-xs text-muted sm:hidden">
          {value.length > 0 ? `${value.length} 字` : "回车发送"}
        </span>
        {busy && onStop ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onStop}
            className="ml-auto h-9 rounded-lg px-3"
            aria-label="停止生成"
          >
            <Square className="h-3 w-3 fill-current" />
            停止
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            onClick={submit}
            disabled={!hasText}
            className="ml-auto h-9 rounded-lg bg-brand px-4 text-white shadow-sm hover:bg-brand-dark"
            aria-label="发送消息"
          >
            <Send className="h-3.5 w-3.5" />
            发送
          </Button>
        )}
      </div>
    </div>
  );
}
