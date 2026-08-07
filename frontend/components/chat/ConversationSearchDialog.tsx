"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Clock3, LoaderCircle, MessageSquareText, Search, X } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/cn";
import {
  listConversations,
  type ConversationSummary,
} from "@/lib/conversations-api";
import { formatConversationTime } from "@/components/chat/utils";

const RECENT_KEY = "agenora:recent-conversation-searches";
const MAX_RECENT = 8;
const SEARCH_DEBOUNCE_MS = 220;

function loadRecentSearches(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is string => typeof item === "string")
      .map((item) => item.trim())
      .filter(Boolean)
      .slice(0, MAX_RECENT);
  } catch {
    return [];
  }
}

function persistRecentSearches(items: string[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(items.slice(0, MAX_RECENT)));
  } catch {
    /* ignore quota */
  }
}

export function ConversationSearchDialog({
  open,
  onOpenChange,
  conversations,
  onSelect,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Loaded sidebar conversations — used as instant local fallback while the server search runs. */
  conversations: Array<{
    id: string;
    title: string;
    updated_at: number;
    message_count?: number;
    messages?: unknown[];
  }>;
  onSelect: (id: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const searchSeq = useRef(0);
  const [query, setQuery] = useState("");
  const [recent, setRecent] = useState<string[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [results, setResults] = useState<ConversationSummary[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setRecent(loadRecentSearches());
    setActiveIndex(0);
    setResults([]);
    setSearching(false);
    setSearchError(null);
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  const trimmed = query.trim();
  const showRecent = !trimmed && recent.length > 0;

  useEffect(() => {
    if (!trimmed) {
      searchSeq.current += 1;
      setResults([]);
      setSearching(false);
      setSearchError(null);
      return;
    }

    const localHits = conversations
      .filter((conversation) => conversation.title.toLowerCase().includes(trimmed.toLowerCase()))
      .slice(0, 20)
      .map(
        (conversation): ConversationSummary => ({
          id: conversation.id,
          title: conversation.title,
          kb_id: null,
          llm_model: null,
          message_count: conversation.message_count ?? conversation.messages?.length ?? 0,
          created_at: null,
          updated_at: new Date(conversation.updated_at).toISOString(),
          finalized_at: null,
        })
      );
    setResults(localHits);
    setSearching(true);
    setSearchError(null);

    const seq = ++searchSeq.current;
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const page = await listConversations({ page: 1, pageSize: 50, q: trimmed });
          if (seq !== searchSeq.current) return;
          setResults(page.items);
          setSearchError(null);
        } catch (error) {
          if (seq !== searchSeq.current) return;
          setSearchError((error as Error)?.message ?? "搜索失败");
        } finally {
          if (seq === searchSeq.current) setSearching(false);
        }
      })();
    }, SEARCH_DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
  }, [trimmed, conversations]);

  const itemCount = showRecent ? recent.length : results.length;

  useEffect(() => {
    setActiveIndex(0);
  }, [trimmed, showRecent, itemCount]);

  const rememberQuery = useCallback((value: string) => {
    const next = value.trim();
    if (!next) return;
    setRecent((prev) => {
      const merged = [next, ...prev.filter((item) => item.toLowerCase() !== next.toLowerCase())].slice(
        0,
        MAX_RECENT
      );
      persistRecentSearches(merged);
      return merged;
    });
  }, []);

  const clearRecent = () => {
    setRecent([]);
    persistRecentSearches([]);
  };

  const selectConversation = (id: string, searchValue?: string) => {
    if (searchValue?.trim()) rememberQuery(searchValue);
    else if (trimmed) rememberQuery(trimmed);
    onOpenChange(false);
    onSelect(id);
  };

  const applyRecent = (value: string) => {
    setQuery(value);
    setActiveIndex(0);
    inputRef.current?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (itemCount === 0) return;
      setActiveIndex((index) => (index + 1) % itemCount);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (itemCount === 0) return;
      setActiveIndex((index) => (index - 1 + itemCount) % itemCount);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (showRecent) {
        const value = recent[activeIndex];
        if (value) applyRecent(value);
        return;
      }
      const hit = results[activeIndex];
      if (hit) selectConversation(hit.id);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="gap-0 overflow-hidden p-0 sm:max-w-lg"
        onKeyDown={onKeyDown}
      >
        <DialogHeader className="sr-only">
          <DialogTitle>搜索对话</DialogTitle>
          <DialogDescription>按标题或消息内容搜索历史对话，或从最近搜索继续。</DialogDescription>
        </DialogHeader>

        <div className="flex items-center gap-2 border-b border-surface-border/80 px-3">
          <Search className="h-4 w-4 shrink-0 text-muted" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索标题或消息内容…"
            className="h-12 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
            aria-label="搜索对话"
          />
          {searching ? (
            <LoaderCircle className="h-4 w-4 shrink-0 animate-spin text-muted" aria-label="搜索中" />
          ) : query ? (
            <button
              type="button"
              className="rounded-md p-1 text-muted transition hover:bg-surface-2 hover:text-ink"
              aria-label="清空搜索"
              onClick={() => setQuery("")}
            >
              <X className="h-4 w-4" />
            </button>
          ) : (
            <kbd className="rounded border border-surface-border/80 px-1.5 py-0.5 text-[10px] text-muted">
              Esc
            </kbd>
          )}
        </div>

        <div className="max-h-[min(24rem,60vh)] overflow-y-auto p-2">
          {showRecent && (
            <div className="mb-1 flex items-center justify-between px-2 py-1.5">
              <span className="text-xs font-medium text-muted">最近搜索</span>
              <button
                type="button"
                className="text-xs text-muted transition hover:text-ink"
                onClick={clearRecent}
              >
                清空
              </button>
            </div>
          )}

          {showRecent &&
            recent.map((item, index) => (
              <button
                key={item}
                type="button"
                className={cn(
                  "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm transition",
                  index === activeIndex ? "bg-surface-2 text-ink" : "text-ink hover:bg-surface-2/70"
                )}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => applyRecent(item)}
              >
                <Clock3 className="h-3.5 w-3.5 shrink-0 text-muted" />
                <span className="min-w-0 truncate">{item}</span>
              </button>
            ))}

          {trimmed && searchError && (
            <div className="px-3 py-2 text-center text-xs text-muted">{searchError}（已显示本地结果）</div>
          )}

          {trimmed && !searching && results.length === 0 && (
            <div className="px-3 py-8 text-center text-sm text-muted">没有匹配的对话</div>
          )}

          {trimmed &&
            results.map((conversation, index) => {
              const messageCount = conversation.message_count || 0;
              const updatedMs = conversation.updated_at
                ? new Date(conversation.updated_at).getTime()
                : Date.now();
              return (
                <button
                  key={conversation.id}
                  type="button"
                  className={cn(
                    "flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition",
                    index === activeIndex ? "bg-surface-2" : "hover:bg-surface-2/70"
                  )}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => selectConversation(conversation.id)}
                >
                  <MessageSquareText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-ink">{conversation.title}</span>
                    <span className="mt-0.5 block text-[11px] text-muted">
                      {formatConversationTime(updatedMs)}
                      {" · "}
                      {messageCount}
                      {" 条消息"}
                    </span>
                  </span>
                </button>
              );
            })}

          {!trimmed && recent.length === 0 && (
            <div className="px-3 py-8 text-center text-sm text-muted">
              输入关键词搜索标题或消息内容
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
