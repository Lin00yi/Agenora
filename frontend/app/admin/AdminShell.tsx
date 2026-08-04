"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { BookOpen, ChevronLeft, Home, LayoutDashboard, Users } from "lucide-react";

import { getToken, getUser, refreshMe } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { LoadingState, StateView } from "@/components/ui/state-view";
import ThemeToggle from "@/components/ThemeToggle";

/**
 * Client-side guard + chrome for the /admin/* pages (06-01).
 *
 * The guard is UX only — the backend 403 on every /api/admin/* call is the real
 * gate. On mount we refresh /api/auth/me so a freshly-granted is_admin flag is
 * picked up without re-login, then redirect non-admins home.
 */
export default function AdminShell({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);
  const [forbidden, setForbidden] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    // Fast path off the cached user, then confirm against the server.
    if (getUser()?.is_admin === false) {
      setForbidden(true);
      return;
    }
    let active = true;
    refreshMe()
      .then((u) => {
        if (!active) return;
        // Fall back to the cached user when /me is unreachable.
        const isAdmin = (u ?? getUser())?.is_admin;
        if (!isAdmin) {
          setForbidden(true);
          return;
        }
        setReady(true);
      })
      .catch(() => {
        if (!active) return;
        if (!getUser()?.is_admin) setForbidden(true);
        else setReady(true);
      });
    return () => {
      active = false;
    };
  }, [router]);

  if (forbidden) {
    return (
      <div className="app-page min-h-dvh text-fg">
        <header className="app-page-header border-b">
          <div className="mx-auto flex h-14 max-w-5xl items-center gap-3 px-4 sm:px-6">
            <Link
              href="/"
              className="inline-flex items-center gap-1 text-sm text-muted transition hover:text-fg"
            >
              <ChevronLeft className="h-4 w-4" />
              <span>返回对话</span>
            </Link>
            <div className="flex-1" />
            <ThemeToggle />
          </div>
        </header>
        <main className="app-page-content mx-auto flex min-h-[calc(100dvh-56px)] max-w-5xl items-center justify-center px-4 py-10 sm:px-6">
          <StateView
            title="没有后台管理权限"
            description="当前账号不是管理员，无法访问后台看板、用户管理和全局知识库管理。"
            action={
              <Link href="/" className="admin-btn-primary">
                返回对话
              </Link>
            }
          />
        </main>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="flex min-h-dvh items-center justify-center px-4">
        <LoadingState label="正在验证访问权限" description="正在确认你的后台管理权限。" className="w-full max-w-md" />
      </div>
    );
  }

  const tabs = [
    { href: "/admin", label: "看板", icon: LayoutDashboard },
    { href: "/admin/users", label: "用户", icon: Users },
    { href: "/admin/kbs", label: "知识库", icon: BookOpen },
  ];

  return (
    <div className="app-page min-h-dvh text-fg">
      <header className="app-page-header border-b">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4 sm:px-6">
          <Link
            href="/"
            className="admin-icon-action admin-icon-action-surface"
            aria-label="返回对话"
          >
            <Home className="h-4 w-4" />
          </Link>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold">{title}</h1>
            <p className="hidden text-xs text-muted sm:block">平台管理</p>
          </div>
          <ThemeToggle />
        </div>
        <nav className="mx-auto flex max-w-7xl items-center gap-1 overflow-x-auto px-4 pb-3 sm:px-6">
          {tabs.map((t) => {
            const active = pathname === t.href;
            const Icon = t.icon;
            return (
              <Link
                key={t.href}
                href={t.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex min-h-[var(--control-h)] shrink-0 items-center gap-2 rounded-md border border-transparent px-3.5 py-2 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30",
                  active
                    ? "border-brand/25 bg-brand/10 text-fg shadow-sm"
                    : "text-muted hover:border-surface-border/80 hover:bg-surface hover:text-fg"
                )}
              >
                <Icon className="h-4 w-4" />
                {t.label}
              </Link>
            );
          })}
        </nav>
      </header>

      <main className="app-page-content mx-auto max-w-7xl px-4 py-7 sm:px-6 sm:py-10">{children}</main>
    </div>
  );
}
