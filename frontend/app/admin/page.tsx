"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Activity,
  BookOpen,
  Database,
  FileText,
  MessageSquare,
  MessageSquareText,
  ShieldCheck,
  UserCheck,
  UserRoundX,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { getStats, type AdminStats } from "@/lib/admin-api";
import AdminShell from "./AdminShell";
import { PageSkeleton, StateView } from "@/components/ui/state-view";

/**
 * /admin — read-only platform stats dashboard (06-01).
 */
export default function AdminDashboardPage() {
  return (
    <AdminShell title="后台管理 · 看板">
      <Dashboard />
    </AdminShell>
  );
}

function Dashboard() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getStats()
      .then(setStats)
      .catch((e) => toast.error((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <PageSkeleton />;
  }

  if (!stats) {
    return <StateView title="暂时没有可展示的数据" description="稍后刷新，或先创建用户和知识库后再查看平台概览。" />;
  }

  return (
    <div className="space-y-7">
      <div className="border-b border-surface-border/70 pb-6">
        <p className="text-xs font-semibold tracking-[0.16em] text-brand">
          运行概览
        </p>
        <h2 className="mt-2 text-2xl font-semibold tracking-tight">平台运行概览</h2>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
          聚合用户、知识库、文档和会话规模，帮助管理员快速判断系统使用情况。
        </p>
      </div>

      <Section title="用户" description="账号规模、活跃状态与管理员配置。">
        <StatCard icon={Users} label="用户总数" value={stats.users.total} />
        <StatCard icon={UserCheck} label="活跃" value={stats.users.active} tone="success" />
        <StatCard icon={UserRoundX} label="封禁" value={stats.users.banned} tone="danger" />
        <StatCard icon={ShieldCheck} label="管理员" value={stats.users.admins} tone="accent" />
        <StatCard icon={Activity} label="近 7 天新增" value={stats.users.new_last_7d} />
      </Section>

      <Section title="知识库" description="资料库数量与系统示例库状态。">
        <StatCard icon={Database} label="KB 总数" value={stats.kbs.total} />
        <StatCard icon={BookOpen} label="系统 KB" value={stats.kbs.system} tone="accent" />
      </Section>

      <Section title="内容" description="文档、会话与消息沉淀规模。">
        <StatCard icon={FileText} label="文档" value={stats.documents} />
        <StatCard icon={MessageSquareText} label="会话" value={stats.conversations} />
        <StatCard icon={MessageSquare} label="消息" value={stats.messages} />
      </Section>
    </div>
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="admin-panel overflow-hidden">
      <div className="border-b border-surface-border/70 bg-surface-2/35 px-5 py-4">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="mt-1 text-xs leading-relaxed text-muted">{description}</p>
      </div>
      <div className="grid gap-3 p-4 [grid-template-columns:repeat(auto-fill,minmax(11rem,13.5rem))]">
        {children}
      </div>
    </section>
  );
}

const toneClass: Record<string, string> = {
  default: "text-fg",
  success: "text-success",
  danger: "text-danger",
  accent: "text-brand",
};

function StatCard({
  icon: Icon,
  label,
  value,
  tone = "default",
}: {
  icon: LucideIcon;
  label: string;
  value: number;
  tone?: "default" | "success" | "danger" | "accent";
}) {
  return (
    <div className="rounded-lg border border-surface-border/80 bg-surface p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-medium text-muted">{label}</div>
        <span className={`admin-icon-tile admin-icon-tile-muted rounded-md ${toneClass[tone]}`}>
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className={`mt-4 text-3xl font-semibold tracking-tight ${toneClass[tone]}`}>
        {value.toLocaleString()}
      </div>
    </div>
  );
}
