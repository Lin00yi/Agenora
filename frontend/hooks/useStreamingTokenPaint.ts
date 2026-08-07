"use client";

import { useCallback, useEffect, useRef, type MutableRefObject } from "react";
import type { Message } from "@/lib/conversationStore";

/**
 * Coalesce SSE token paints to one React update per animation frame.
 * Keeps streamingRef.content as the source of truth between paints.
 */
export function useStreamingTokenPaint(
  streamingRef: MutableRefObject<{ msgId: string; content: string } | null>,
  setMessagesForCurrent: (next: Message[] | ((prev: Message[]) => Message[])) => void
) {
  const tokenPaintRafRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (tokenPaintRafRef.current != null) {
        cancelAnimationFrame(tokenPaintRafRef.current);
        tokenPaintRafRef.current = null;
      }
    };
  }, []);

  const paintContent = useCallback(() => {
    const snap = streamingRef.current;
    if (!snap) return;
    const { msgId, content } = snap;
    setMessagesForCurrent((prev) => {
      const next = [...prev];
      for (let i = next.length - 1; i >= 0; i--) {
        const msg = next[i];
        if (msg.role === "assistant" && msg.id === msgId) {
          if (msg.content === content) return prev;
          next[i] = { ...msg, content };
          break;
        }
      }
      return next;
    });
  }, [setMessagesForCurrent, streamingRef]);

  const flushTokenPaint = useCallback(
    (paint = true) => {
      if (tokenPaintRafRef.current != null) {
        cancelAnimationFrame(tokenPaintRafRef.current);
        tokenPaintRafRef.current = null;
      }
      if (paint) paintContent();
    },
    [paintContent]
  );

  const scheduleTokenPaint = useCallback(() => {
    if (tokenPaintRafRef.current != null) return;
    tokenPaintRafRef.current = requestAnimationFrame(() => {
      tokenPaintRafRef.current = null;
      paintContent();
    });
  }, [paintContent]);

  return { flushTokenPaint, scheduleTokenPaint };
}
