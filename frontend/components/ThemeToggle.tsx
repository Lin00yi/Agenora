"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "@/components/ThemeProvider";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";

const OPTIONS = [
  { value: "light" as const, Icon: Sun, label: "亮色" },
  { value: "system" as const, Icon: Monitor, label: "跟随系统" },
  { value: "dark" as const, Icon: Moon, label: "暗色" },
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
      className={cn("rounded-lg border bg-muted/40 p-0.5", className)}
      aria-label="主题切换"
    >
      {OPTIONS.map(({ value, Icon, label }) => (
        <ToggleGroupItem
          key={value}
          value={value}
          size="sm"
          className="h-7 w-7 p-0"
          title={label}
          aria-label={label}
        >
          <Icon className="h-3.5 w-3.5" />
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
