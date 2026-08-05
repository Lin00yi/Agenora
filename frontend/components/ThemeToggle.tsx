"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import Select from "@/components/Select";
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
  { value: "system", label: "跟随系统", icon: Monitor },
  { value: "dark", label: "深色", icon: Moon },
] as const;

function ThemeIcon({ theme, className }: { theme: Theme; className?: string }) {
  const Icon = OPTIONS.find((opt) => opt.value === theme)?.icon ?? Monitor;
  return <Icon className={cn("h-4 w-4", className)} />;
}

export default function ThemeToggle({
  className,
  compact = false,
}: {
  className?: string;
  compact?: boolean;
}) {
  const { theme, setTheme } = useTheme();

  if (compact) {
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
          <ThemeIcon theme={theme} />
        </SelectTrigger>
        <SelectContent align="end" position="popper" className="min-w-[9.5rem]">
          {OPTIONS.map((opt) => {
            const Icon = opt.icon;
            return (
              <SelectItem key={opt.value} value={opt.value}>
                <span className="flex items-center gap-2">
                  <Icon className="h-4 w-4 shrink-0 opacity-70" />
                  {opt.label}
                </span>
              </SelectItem>
            );
          })}
        </SelectContent>
      </ShadcnSelect>
    );
  }

  return (
    <Select
      value={theme}
      onChange={(e) => setTheme(e.target.value as Theme)}
      options={OPTIONS.map(({ value, label }) => ({ value, label }))}
      aria-label="外观主题"
      contentAlign="start"
      contentPosition="popper"
      className={cn("h-[var(--control-h)] min-h-[var(--control-h)] w-[8.5rem] min-w-[8.5rem]", className)}
    />
  );
}
