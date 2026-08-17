"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import {
  BookOpen,
  ChevronLeft,
  GitBranch,
  LayoutDashboard,
  Users,
} from "lucide-react";

import { getToken, getUser, refreshMe } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { LoadingState, StateView } from "@/components/ui/state-view";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

const TABS = [
  { href: "/admin", label: "看板", icon: LayoutDashboard, title: "看板" },
  { href: "/admin/users", label: "用户", icon: Users, title: "用户" },
  { href: "/admin/kbs", label: "知识库", icon: BookOpen, title: "知识库" },
  { href: "/admin/traces", label: "追踪", icon: GitBranch, title: "追踪" },
] as const;

/**
 * Client-side guard + chrome for the /admin/* pages.
 * Mounted once via app/admin/layout.tsx so tab navigations keep the shell.
 */
export default function AdminShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);
  const [forbidden, setForbidden] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    let active = true;
    refreshMe()
      .then((u) => {
        if (!active) return;
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

  const activeTab =
    TABS.find((tab) =>
      tab.href === "/admin"
        ? pathname === "/admin"
        : pathname === tab.href || pathname.startsWith(`${tab.href}/`)
    ) ?? TABS[0];

  if (forbidden) {
    return (
      <div className="app-page min-h-dvh text-ink">
        <header className="app-page-header border-b">
          <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:px-6">
            <Link href="/" className="app-nav-link app-nav-link-compact">
              <ChevronLeft className="h-4 w-4" />
              <span>返回对话</span>
            </Link>
            <div className="flex-1" />
          </div>
        </header>
        <main className="app-page-content mx-auto flex min-h-[calc(100dvh-56px)] max-w-5xl items-center justify-center px-4 py-10 sm:px-6">
          <StateView
            title="没有后台管理权限"
            description="当前账号不是管理员，无法访问后台看板、用户管理和全局知识库管理。"
            action={
              <Button asChild>
                <Link href="/">返回对话</Link>
              </Button>
            }
          />
        </main>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="flex min-h-dvh items-center justify-center px-4">
        <LoadingState
          label="正在验证访问权限"
          description="正在确认你的后台管理权限。"
          className="w-full max-w-md"
        />
      </div>
    );
  }

  return (
    <div className="app-page min-h-dvh text-ink">
      <header className="app-page-header border-b">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:px-6">
          <Link href="/" className="app-nav-link app-nav-link-compact">
            <ChevronLeft className="h-4 w-4" />
            <span>返回对话</span>
          </Link>
          <span className="hidden text-sm text-muted sm:inline" aria-hidden>
            /
          </span>
          <span className="hidden truncate text-sm font-medium text-ink sm:inline">
            {activeTab.title}
          </span>
          <div className="flex-1" />
        </div>
        <nav className="mx-auto max-w-7xl overflow-x-auto px-4 pb-3 sm:px-6" aria-label="管理分区">
          <Tabs value={activeTab.href} onValueChange={(href) => router.push(href)} className="w-max">
            <TabsList aria-label="管理分区">
              {TABS.map((t) => {
                const Icon = t.icon;
                return (
                  <TabsTrigger key={t.href} value={t.href}>
                    <Icon />
                    {t.label}
                  </TabsTrigger>
                );
              })}
            </TabsList>
          </Tabs>
        </nav>
      </header>

      <main className="app-page-content mx-auto max-w-7xl px-4 py-7 sm:px-6 sm:py-10">
        {children}
      </main>
    </div>
  );
}
