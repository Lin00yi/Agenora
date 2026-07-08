const fs = require("fs");
const path = require("path");

const out = path.join(__dirname, "..", "components", "ChatBox.tsx");

const PLACEHOLDER =
  "\u95ee\u70b9\u4ec0\u4e48... \u4f8b\u5982\uff1a\u603b\u7ed3\u4e00\u4e0b\u8fd9\u4efd\u77e5\u8bc6\u5e93\u7684\u4e3b\u8981\u5185\u5bb9";
const HINT = "Enter \u53d1\u9001 \u00b7 Shift+Enter \u6362\u884c";
const MOBILE = "\u56de\u8f66\u53d1\u9001";
const STOP = "\u505c\u6b62";
const SEND = "\u53d1\u9001";

const content = `"use client";

import { Send, Square } from "lucide-react";
import { useEffect, useRef, useState, KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Props = {
  onSend: (q: string) => void;
  onStop?: () => void;
  busy?: boolean;
  placeholder?: string;
};

const DEFAULT_PLACEHOLDER = ${JSON.stringify(PLACEHOLDER)};

export default function ChatBox({ onSend, onStop, busy, placeholder }: Props) {
  const [value, setValue] = useState("");
  const [focused, setFocused] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
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
        style={{ maxHeight: 200 }}
      />
      <div className="flex items-center justify-between gap-2 px-3 pb-2.5 pt-1">
        <span className="hidden text-xs text-muted sm:inline">${HINT}</span>
        <span className="text-xs text-muted sm:hidden">${MOBILE}</span>
        {busy && onStop ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onStop}
            className="ml-auto rounded-full"
          >
            <Square className="h-3 w-3 fill-current" />
            ${STOP}
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            onClick={submit}
            disabled={!value.trim()}
            className="ml-auto rounded-full bg-brand px-4 text-white shadow-sm hover:bg-brand-dark"
          >
            <Send className="h-3.5 w-3.5" />
            ${SEND}
          </Button>
        )}
      </div>
    </div>
  );
}
`;

fs.writeFileSync(out, content, "utf8");
console.log("OK:", PLACEHOLDER);
