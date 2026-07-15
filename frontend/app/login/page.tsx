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
            className="inline-flex items-center gap-1 text-sm text-muted transition hover:text-fg"
          >
            <ChevronLeft className="h-4 w-4" />
            返回首页
          </Link>
          <div className="flex items-center gap-3">
            <ThemeToggle />
            <div className="flex items-center gap-2 lg:hidden">
              <Brand size="sm" showWordmark />
            </div>
          </div>
        </div>

        <div className="flex flex-1 items-center justify-center py-8">
          <div className="w-full max-w-sm">
            <div className="card p-7 shadow-lift sm:p-8">
              <h1 className="text-2xl font-bold tracking-tight">欢迎回到 {APP_NAME}</h1>
              <p className="mt-2 text-sm text-muted">登录后继续管理你的知识库和会话。</p>

              <form onSubmit={onSubmit} className="mt-8 space-y-5">
                <div className="space-y-2">
                  <Label htmlFor="email">邮箱</Label>
                  <div className="relative">
                    <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                    <Input
                      id="email"
                      type="email"
                      autoComplete="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="h-10 bg-bg pl-9"
                      placeholder="you@example.com"
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="password">密码</Label>
                  <div className="relative">
                    <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                    <Input
                      id="password"
                      type="password"
                      autoComplete="current-password"
                      required
                      minLength={8}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="h-10 bg-bg pl-9"
                      placeholder="至少 8 位"
                    />
                  </div>
                </div>

                <Button
                  type="submit"
                  disabled={loading}
                  className="h-10 w-full bg-brand text-white hover:bg-brand-dark"
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

              <p className="mt-6 text-center text-sm text-muted">
                还没有账号？{" "}
                <Link
                  href="/register"
                  className="inline-flex items-center gap-0.5 font-medium text-brand hover:underline"
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
