"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "@/components/ThemeProvider";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";

const OPTIONS = [
  { value: "light" as const, Icon: Sun, label: "浅色" },
  { value: "system" as const, Icon: Monitor, label: "跟随系统" },
  { value: "dark" as const, Icon: Moon, label: "深色" },
];

export default function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();

  return (
    <ToggleGroup
      type="single"
      value={theme}
      onValueChange={(value) => {
        if (value) setTheme(value as typeof theme);
      }}
      className={cn("ak-theme-toggle gap-0.5 rounded-md border border-surface-border/80 bg-surface/85 p-0.5 shadow-soft", className)}
      aria-label="主题切换"
      spacing={0}
    >
      {OPTIONS.map(({ value, Icon, label }) => (
        <ToggleGroupItem
          key={value}
          value={value}
          size="sm"
          className="app-theme-toggle-item h-7 min-h-7 w-7 min-w-7 rounded border p-0"
          title={label}
          aria-label={label}
        >
          <Icon className="size-3.5" />
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
