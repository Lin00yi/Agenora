"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

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
    <div className="space-y-8">
      <Section title="用户">
        <StatCard label="用户总数" value={stats.users.total} />
        <StatCard label="活跃" value={stats.users.active} tone="success" />
        <StatCard label="封禁" value={stats.users.banned} tone="danger" />
        <StatCard label="管理员" value={stats.users.admins} tone="accent" />
        <StatCard label="近 7 天新增" value={stats.users.new_last_7d} />
      </Section>

      <Section title="知识库">
        <StatCard label="KB 总数" value={stats.kbs.total} />
        <StatCard label="系统 KB" value={stats.kbs.system} tone="accent" />
      </Section>

      <Section title="内容">
        <StatCard label="文档" value={stats.documents} />
        <StatCard label="会话" value={stats.conversations} />
        <StatCard label="消息" value={stats.messages} />
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-3 text-sm font-medium text-muted">{title}</h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
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
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: number;
  tone?: "default" | "success" | "danger" | "accent";
}) {
  return (
    <div className="card p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${toneClass[tone]}`}>
        {value.toLocaleString()}
      </div>
    </div>
  );
}
