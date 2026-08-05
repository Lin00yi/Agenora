"use client";

import { useRouter } from "next/navigation";
import { useState, FormEvent, useEffect } from "react";
import { ArrowRight, ChevronLeft, Lock, LogIn, Mail } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import Brand, { APP_NAME } from "@/components/Brand";
import BrandPanel from "@/components/BrandPanel";
import ThemeToggle from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { login } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const reason = new URLSearchParams(window.location.search).get("reason");
    if (reason === "session_expired") {
      toast.info("登录已失效，请重新登录");
    }
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(email.trim(), password);
      const next = new URLSearchParams(window.location.search).get("next");
      const safeNext = next && next.startsWith("/") ? next : "/";
      router.replace(safeNext);
    } catch (err: unknown) {
      toast.error((err as Error)?.message ?? "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <BrandPanel />

      <div className="app-gradient-bg flex min-h-screen flex-col px-6 py-8 sm:px-10">
        <div className="flex items-center justify-between gap-3">
          <Link
            href="/welcome"
            className="app-nav-link app-nav-link-surface"
          >
            <ChevronLeft className="h-4 w-4" />
            返回首页
          </Link>
          <ThemeToggle />
        </div>

        <div className="flex flex-1 items-center justify-center py-8">
          <div className="w-full max-w-md">
            <div className="mb-5 flex justify-center lg:hidden">
              <Brand size="sm" showWordmark />
            </div>
            <div className="admin-panel overflow-hidden">
              <div className="border-b border-surface-border/70 bg-surface-2/45 px-7 py-6 sm:px-8">
                <p className="text-xs font-semibold tracking-[0.16em] text-brand">
                  安全登录
                </p>
                <h1 className="mt-2 text-2xl font-semibold tracking-tight">欢迎回到 {APP_NAME}</h1>
                <p className="mt-2 text-sm leading-6 text-muted">登录后继续管理你的知识库和会话。</p>
              </div>

              <form onSubmit={onSubmit} className="space-y-5 bg-surface px-7 py-7 sm:px-8">
                <div className="space-y-2">
                  <Label htmlFor="email">邮箱</Label>
                  <div className="relative">
                    <Mail className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                    <Input
                      id="email"
                      type="email"
                      autoComplete="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="h-[44px] bg-surface pl-10"
                      placeholder="you@example.com"
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="password">密码</Label>
                  <div className="relative">
                    <Lock className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                    <Input
                      id="password"
                      type="password"
                      autoComplete="current-password"
                      required
                      minLength={8}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="h-[44px] bg-surface pl-10"
                      placeholder="至少 8 位"
                    />
                  </div>
                </div>

                <Button
                  type="submit"
                  disabled={loading}
                  className="min-h-[44px] w-full"
                >
                  {loading ? (
                    "登录中..."
                  ) : (
                    <>
                      <LogIn className="h-4 w-4" />
                      登录
                    </>
                  )}
                </Button>
              </form>

              <p className="border-t border-surface-border/70 bg-surface-2/35 px-7 py-4 text-center text-sm text-muted sm:px-8">
                还没有账号？{" "}
                <Link
                  href="/register"
                  className="app-inline-link-brand"
                >
                  创建账号 <ArrowRight className="h-3 w-3" />
                </Link>
              </p>
            </div>
          </div>
        </div>

        <p className="text-center text-xs text-muted">
          © {new Date().getFullYear()} {APP_NAME} · MIT License
        </p>
      </div>
    </div>
  );
}
