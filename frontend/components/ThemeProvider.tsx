"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { migrateLegacyKeys } from "@/lib/storage-migrate";

export type Theme = "light" | "dark" | "system";

type Ctx = {
  theme: Theme;
  resolved: "light" | "dark";
  setTheme: (t: Theme) => void;
};

const ThemeContext = createContext<Ctx | null>(null);

const STORAGE_KEY = "agenora:theme";

function readStored(): Theme {
  if (typeof window === "undefined") return "system";
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* ignore */
  }
  return "system";
}

function systemPrefersDark(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function applyClass(resolved: "light" | "dark") {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("dark", resolved === "dark");
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("system");
  const [resolved, setResolved] = useState<"light" | "dark">("light");

  useEffect(() => {
    migrateLegacyKeys();
    const t = readStored();
    setThemeState(t);
    const r: "light" | "dark" =
      t === "system" ? (systemPrefersDark() ? "dark" : "light") : t;
    setResolved(r);
    applyClass(r);
  }, []);

  useEffect(() => {
    if (theme !== "system" || typeof window === "undefined") return;
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => {
      const r: "light" | "dark" = e.matches ? "dark" : "light";
      setResolved(r);
      applyClass(r);
    };
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [theme]);

  const setTheme = (t: Theme) => {
    setThemeState(t);
    try {
      window.localStorage.setItem(STORAGE_KEY, t);
    } catch {
      /* ignore */
    }
    const r: "light" | "dark" =
      t === "system" ? (systemPrefersDark() ? "dark" : "light") : t;
    setResolved(r);
    applyClass(r);
  };

  return (
    <ThemeContext.Provider value={{ theme, resolved, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): Ctx {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    return {
      theme: "system",
      resolved: "light",
      setTheme: () => {},
    };
  }
  return ctx;
}
