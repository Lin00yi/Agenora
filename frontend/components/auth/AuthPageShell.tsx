import type { ReactNode } from "react";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";

import Brand, { APP_NAME } from "@/components/Brand";
import ThemeToggle from "@/components/ThemeToggle";

type AuthPageShellProps = {
  children: ReactNode;
};

/** Shared centered frame for unauthenticated entry points. */
export default function AuthPageShell({ children }: AuthPageShellProps) {
  return (
    <main className="app-gradient-bg flex min-h-dvh flex-col px-5 py-5 sm:px-8 sm:py-7">
      <header className="flex h-11 items-center justify-between">
        <Link href="/welcome" className="app-nav-link app-nav-link-surface" aria-label="返回首页">
          <ChevronLeft className="size-4" />
          返回首页
        </Link>
        <ThemeToggle />
      </header>

      <div className="flex flex-1 items-center justify-center py-8 sm:py-10">
        <div className="w-full max-w-md">
          <div className="mb-7 flex flex-col items-center text-center sm:mb-8">
            <Brand size="lg" showWordmark />
            <p className="mt-3 text-pretty text-sm leading-6 text-muted">
              私有知识库与可信 Agent 工作台
            </p>
          </div>
          {children}
        </div>
      </div>

      <footer className="pt-2 text-center text-xs text-muted">
        © {new Date().getFullYear()} {APP_NAME}
      </footer>
    </main>
  );
}
