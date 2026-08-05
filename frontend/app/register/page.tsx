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
                  创建账号
                </p>
                <h1 className="mt-2 text-2xl font-semibold tracking-tight">创建 {APP_NAME} 账号</h1>
                <p className="mt-2 text-sm leading-6 text-muted">
                  注册后即可创建知识库，并在当前部署环境中管理资料。
                </p>
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
                  <Label htmlFor="displayName">
                    昵称 <span className="font-normal text-muted">（可选）</span>
                  </Label>
                  <div className="relative">
                    <UserIcon className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                    <Input
                      id="displayName"
                      type="text"
                      maxLength={64}
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      className="h-[44px] bg-surface pl-10"
                      placeholder="例如：张小北"
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
                      autoComplete="new-password"
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

              <p className="border-t border-surface-border/70 bg-surface-2/35 px-7 py-4 text-center text-sm text-muted sm:px-8">
                已有账号？{" "}
                <Link
                  href="/login"
                  className="app-inline-link-brand"
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
