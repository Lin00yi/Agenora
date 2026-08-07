"use client";

import Link from "next/link";
import { cn } from "@/lib/cn";

const ITEMS = [
  { key: "model" as const, href: "/settings", label: "模型" },
  { key: "memory" as const, href: "/memories", label: "记忆" },
  { key: "account" as const, href: "/c?account=1", label: "账号" },
];

export type SettingsAreaKey = (typeof ITEMS)[number]["key"];

/** Compact cross-links between model / memory / account settings surfaces. */
export function SettingsAreaNav({
  active,
  className,
  onNavigate,
}: {
  active: SettingsAreaKey;
  className?: string;
  /** Optional: close a modal before following a link. */
  onNavigate?: () => void;
}) {
  return (
    <nav
      className={cn(
        "inline-flex items-center gap-1 rounded-lg border border-surface-border/80 bg-surface-2/50 p-1",
        className
      )}
      aria-label="设置分区"
    >
      {ITEMS.map((item) => {
        const isActive = item.key === active;
        return (
          <Link
            key={item.key}
            href={item.href}
            onClick={onNavigate}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition",
              isActive
                ? "bg-surface text-ink shadow-sm"
                : "text-muted hover:bg-surface/70 hover:text-ink"
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
