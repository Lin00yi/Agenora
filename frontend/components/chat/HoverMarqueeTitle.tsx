"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";

const MARQUEE_SPEED_PX_PER_SEC = 56;
const MARQUEE_MIN_DURATION_MS = 400;
const MARQUEE_HOVER_DELAY_MS = 280;

function prefersReducedMotion() {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * Codex-style truncated title: clips with edge fades; on hover slides via
 * GPU transform (not text-indent) so the motion stays smooth.
 */
export function HoverMarqueeTitle({
  text,
  className,
  scrolling,
}: {
  text: string;
  className?: string;
  scrolling: boolean;
}) {
  const outerRef = useRef<HTMLDivElement | null>(null);
  const innerRef = useRef<HTMLSpanElement | null>(null);
  const pendingRef = useRef<number | null>(null);
  const [shiftPx, setShiftPx] = useState(0);
  const [durationMs, setDurationMs] = useState(0);
  const [running, setRunning] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useEffect(() => {
    const outer = outerRef.current;
    const inner = innerRef.current;
    if (!outer || !inner) return;

    const measure = () => {
      const overflow = Math.max(0, inner.scrollWidth - outer.clientWidth);
      setOverflows(overflow > 1);
      return overflow;
    };

    // Baseline: know whether a right-edge fade is needed while idle.
    measure();

    const clearPending = () => {
      if (pendingRef.current != null) {
        window.clearTimeout(pendingRef.current);
        pendingRef.current = null;
      }
    };

    const stop = () => {
      clearPending();
      setRunning(false);
      setShiftPx(0);
    };

    if (!scrolling || prefersReducedMotion()) {
      stop();
      measure();
      return;
    }

    // Defer measure until hover actions have settled in layout.
    const frame = window.requestAnimationFrame(() => {
      clearPending();
      pendingRef.current = window.setTimeout(() => {
        pendingRef.current = null;
        const overflow = measure();
        if (overflow <= 1) {
          stop();
          return;
        }
        setDurationMs(
          Math.max(MARQUEE_MIN_DURATION_MS, Math.round((overflow / MARQUEE_SPEED_PX_PER_SEC) * 1000))
        );
        setShiftPx(overflow);
        // Two frames so the browser commits shift/duration before toggling running.
        window.requestAnimationFrame(() => {
          window.requestAnimationFrame(() => setRunning(true));
        });
      }, MARQUEE_HOVER_DELAY_MS);
    });

    return () => {
      window.cancelAnimationFrame(frame);
      clearPending();
      setRunning(false);
      setShiftPx(0);
    };
  }, [scrolling, text]);

  return (
    <div
      ref={outerRef}
      className={cn(
        "kf-hover-marquee min-w-0 overflow-hidden",
        overflows && !running && "kf-hover-marquee--clip",
        running && "kf-hover-marquee--scrolling",
        className
      )}
    >
      <span
        ref={innerRef}
        className="kf-hover-marquee__text inline-block max-w-none whitespace-nowrap will-change-transform"
        style={{
          transform: running ? `translate3d(-${shiftPx}px,0,0)` : "translate3d(0,0,0)",
          transition: running
            ? `transform ${durationMs}ms linear`
            : "transform 160ms ease-out",
        }}
      >
        {text}
      </span>
    </div>
  );
}
