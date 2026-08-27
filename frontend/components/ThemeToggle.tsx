"use client";

import { Monitor, Moon, Sun } from "lucide-react";

import { type Theme, useTheme } from "@/components/ThemeProvider";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/** Compact theme picker for public and unauthenticated pages. */
export default function ThemeToggle() {
  const { theme, resolved, setTheme } = useTheme();
  const ThemeIcon = theme === "system" ? Monitor : resolved === "dark" ? Moon : Sun;
  const themeLabel = theme === "system" ? "跟随系统" : theme === "dark" ? "深色" : "浅色";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="outline" size="icon" aria-label={`主题：${themeLabel}`} title={`主题：${themeLabel}`}>
          <ThemeIcon className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-36">
        <DropdownMenuLabel>主题</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme} onValueChange={(value) => setTheme(value as Theme)}>
          <DropdownMenuRadioItem value="system">
            <Monitor className="size-4" />
            跟随系统
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light">
            <Sun className="size-4" />
            浅色
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">
            <Moon className="size-4" />
            深色
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
