"use client";

import { useRouter } from "next/navigation";
import { useState, FormEvent } from "react";
import { ArrowRight, Lock, Mail, User as UserIcon, UserPlus } from "lucide-react";
import Link from "next/link";
import { toast } from "@/lib/toast";

import AuthPageShell from "@/components/auth/AuthPageShell";
import PasswordInput from "@/components/auth/PasswordInput";
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
    <AuthPageShell>
      <section className="admin-panel overflow-hidden" aria-labelledby="register-heading">
        <div className="border-b border-surface-border/70 bg-surface-2/45 px-6 py-6 sm:px-7">
          <h1 id="register-heading" className="text-balance text-2xl font-semibold text-ink">
            创建账号
          </h1>
          <p className="mt-2 text-pretty text-sm leading-6 text-muted">
            注册后即可创建知识库，并在当前部署环境中管理资料。
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
            <Label htmlFor="displayName">
              昵称 <span className="font-normal text-muted">（可选）</span>
            </Label>
            <div className="relative">
              <UserIcon className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
              <Input
                id="displayName"
                type="text"
                maxLength={64}
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="h-11 bg-surface pl-10"
                placeholder="例如：张小北"
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">密码</Label>
            <PasswordInput
              id="password"
              autoComplete="new-password"
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
              "创建中..."
            ) : (
              <>
                <UserPlus className="size-4" />
                创建账号
              </>
            )}
          </Button>

          <p className="text-pretty text-center text-xs leading-relaxed text-muted">
            请使用你能接收邀请的邮箱注册。管理员可在后台调整账号权限。
          </p>
        </form>

        <p className="border-t border-surface-border/70 bg-surface-2/35 px-6 py-4 text-center text-sm text-muted sm:px-7">
          已有账号？{" "}
          <Link href="/login" className="app-inline-link-brand">
            去登录 <ArrowRight className="size-3" />
          </Link>
        </p>
      </section>
    </AuthPageShell>
  );
}
