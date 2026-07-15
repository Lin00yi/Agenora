"use client";

import { useRouter } from "next/navigation";
import { useState, FormEvent } from "react";
import { ArrowRight, ChevronLeft, Lock, Mail, User as UserIcon, UserPlus } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import Brand, { APP_NAME } from "@/components/Brand";
import BrandPanel from "@/components/BrandPanel";
import ThemeToggle from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { register } from "@/lib/auth";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [loading, setLoading] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await register(email.trim(), password, displayName.trim());
      const next = new URLSearchParams(window.location.search).get("next");
      const safeNext = next && next.startsWith("/") ? next : "/";
      router.replace(safeNext);
    } catch (err: unknown) {
      toast.error((err as Error)?.message ?? "注册失败");
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
              <h1 className="text-2xl font-bold tracking-tight">创建 {APP_NAME} 账号</h1>
              <p className="mt-2 text-sm text-muted">
                注册后即可创建知识库，并在当前部署环境中管理资料。
              </p>

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
                  <Label htmlFor="displayName">
                    昵称 <span className="font-normal text-muted">（可选）</span>
                  </Label>
                  <div className="relative">
                    <UserIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                    <Input
                      id="displayName"
                      type="text"
                      maxLength={64}
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      className="h-10 bg-bg pl-9"
                      placeholder="例如：张小北"
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
                      autoComplete="new-password"
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
                    "创建中..."
                  ) : (
                    <>
                      <UserPlus className="h-4 w-4" />
                      创建账号
                    </>
                  )}
                </Button>

                <p className="text-center text-[11px] leading-relaxed text-muted">
                  请使用你能接收邀请的邮箱注册。管理员可在后台调整账号权限。
                </p>
              </form>

              <p className="mt-6 text-center text-sm text-muted">
                已有账号？{" "}
                <Link
                  href="/login"
                  className="inline-flex items-center gap-0.5 font-medium text-brand hover:underline"
                >
                  去登录 <ArrowRight className="h-3 w-3" />
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
