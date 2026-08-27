"use client";

import { useRouter } from "next/navigation";
import { useState, FormEvent, useEffect } from "react";
import { ArrowRight, Lock, LogIn, Mail } from "lucide-react";
import Link from "next/link";
import { toast } from "@/lib/toast";

import AuthPageShell from "@/components/auth/AuthPageShell";
import PasswordInput from "@/components/auth/PasswordInput";
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
    <AuthPageShell>
      <section className="admin-panel overflow-hidden" aria-labelledby="login-heading">
        <div className="border-b border-surface-border/70 bg-surface-2/45 px-6 py-6 sm:px-7">
          <h1 id="login-heading" className="text-balance text-2xl font-semibold text-ink">
            欢迎回来
          </h1>
          <p className="mt-2 text-pretty text-sm leading-6 text-muted">
            登录后继续管理你的知识库和会话。
          </p>
        </div>

        <form onSubmit={onSubmit} className="space-y-5 bg-surface px-6 py-7 sm:px-7" aria-busy={loading || undefined}>
          <div className="space-y-2">
            <Label htmlFor="email">邮箱</Label>
            <div className="relative">
              <Mail className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
              <Input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="h-11 bg-surface pl-10"
                placeholder="you@example.com"
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">密码</Label>
            <PasswordInput
              id="password"
              autoComplete="current-password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              prefixIcon={<Lock className="size-4" />}
              className="h-11 bg-surface"
              placeholder="至少 8 位"
            />
          </div>

          <Button type="submit" size="lg" disabled={loading} className="w-full">
            {loading ? (
              "登录中..."
            ) : (
              <>
                <LogIn className="size-4" />
                登录
              </>
            )}
          </Button>
        </form>

        <p className="border-t border-surface-border/70 bg-surface-2/35 px-6 py-4 text-center text-sm text-muted sm:px-7">
          还没有账号？{" "}
          <Link href="/register" className="app-inline-link-brand">
            创建账号 <ArrowRight className="size-3" />
          </Link>
        </p>
      </section>
    </AuthPageShell>
  );
}
