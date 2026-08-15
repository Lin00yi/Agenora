"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import {
  Select as ShadcnSelect,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "@/components/ui/select";
import { useTheme, type Theme } from "@/components/ThemeProvider";
import { cn } from "@/lib/utils";

const OPTIONS = [
  { value: "light", label: "浅色", icon: Sun },
  { value: "dark", label: "深色", icon: Moon },
  { value: "system", label: "跟随系统", icon: Monitor },
] as const;

function ThemeIcon({ theme, className }: { theme: Theme; className?: string }) {
  const Icon = OPTIONS.find((opt) => opt.value === theme)?.icon ?? Monitor;
  return <Icon className={cn("h-4 w-4", className)} />;
}

export default function ThemeToggle({
  className,
}: {
  className?: string;
  /** Kept for existing callers; every entry now uses the compact shared control. */
  compact?: boolean;
}) {
  const { theme, setTheme } = useTheme();

  return (
    <ShadcnSelect value={theme} onValueChange={(next) => setTheme(next as Theme)}>
      <SelectTrigger
        aria-label="外观主题"
        title="外观主题"
        tone="plain"
        layout="icon"
        className={cn(
          "kf-theme-toggle-compact size-[var(--control-h)] shrink-0",
          className
        )}
      >
        <ThemeIcon theme={theme} className="size-5" />
      </SelectTrigger>
      <SelectContent align="end" position="popper" className="min-w-[10rem]">
        {OPTIONS.map((opt) => {
          const Icon = opt.icon;
          return (
            <SelectItem
              key={opt.value}
              value={opt.value}
              className="theme-select-item data-[state=checked]:bg-surface-2 data-[state=checked]:text-ink dark:data-[state=checked]:bg-surface-2"
            >
              <span className="flex items-center gap-3">
                <Icon className="size-5 shrink-0 text-muted" />
                {opt.label}
              </span>
            </SelectItem>
          );
        })}
      </SelectContent>
    </ShadcnSelect>
  );
}
