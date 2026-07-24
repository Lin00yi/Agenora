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
      className={cn("ak-theme-toggle rounded-full border border-surface-border/80 bg-surface/80 p-1 shadow-soft", className)}
      aria-label="主题切换"
    >
      {OPTIONS.map(({ value, Icon, label }) => (
        <ToggleGroupItem
          key={value}
          value={value}
          size="sm"
          className="h-7 w-7 rounded-full p-0 text-muted transition-[background-color,color,box-shadow,transform] duration-press data-[state=on]:bg-brand data-[state=on]:text-white data-[state=on]:shadow-sm hover:bg-surface-2 hover:text-fg"
          title={label}
          aria-label={label}
        >
          <Icon className="h-3.5 w-3.5" />
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
