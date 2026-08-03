"use client";

import Select from "@/components/Select";
import { useTheme, type Theme } from "@/components/ThemeProvider";
import { cn } from "@/lib/utils";

const OPTIONS = [
  { value: "light", label: "浅色" },
  { value: "system", label: "跟随系统" },
  { value: "dark", label: "深色" },
];

export default function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();

  return (
    <Select
      value={theme}
      onChange={(e) => setTheme(e.target.value as Theme)}
      options={OPTIONS}
      size="sm"
      aria-label="外观主题"
      contentAlign="start"
      contentPosition="popper"
      className={cn("h-9 min-h-9 w-[8.5rem] min-w-[8.5rem]", className)}
    />
  );
}
