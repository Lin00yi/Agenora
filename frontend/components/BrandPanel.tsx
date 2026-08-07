"use client";

import { BookOpen, CheckCircle2, Database, LockKeyhole, Search, ShieldCheck } from "lucide-react";

import Brand, { APP_NAME } from "@/components/Brand";

export default function BrandPanel() {
  return (
    <div className="kf-brand-panel relative hidden overflow-hidden border-r border-surface-border lg:flex lg:flex-col">
      <div className="kf-brand-panel-gradient absolute inset-0" />
      <div className="kf-brand-panel-grid absolute inset-0" />
      <div className="relative z-10 flex h-full flex-col p-10 xl:p-14">
        <Brand size="sm" showWordmark />

        <div className="flex flex-1 flex-col justify-center">
          <div className="max-w-md">
            <p className="kf-brand-panel-kicker mb-3 text-xs font-semibold tracking-wide">
              私有知识工作区
            </p>
            <h2 className="text-3xl font-semibold leading-tight xl:text-4xl">
              让团队资料变成可追问、可引用的答案
            </h2>
            <p className="kf-brand-panel-muted mt-4 text-sm leading-7">
              {APP_NAME} 面向私有知识库与 Agent 场景：模型密钥由你提供，文档和向量数据保留在自己的部署环境里。
            </p>
          </div>

          <div className="kf-brand-panel-card mt-10 max-w-md rounded-lg border p-4 backdrop-blur">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-medium">产品资料库</p>
                <p className="kf-brand-panel-muted mt-1 text-xs">混合检索 · 重排已开启</p>
              </div>
              <span className="kf-brand-panel-chip inline-flex min-h-6 shrink-0 items-center rounded-md border px-2.5 text-xs font-medium">
                就绪
              </span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <MiniStat label="文档" value="42" />
              <MiniStat label="分块" value="1.2k" />
              <MiniStat label="命中" value="3" />
            </div>
            <div className="mt-4 space-y-2">
              <FeatureLine icon={<Search className="h-4 w-4" />} text="混合检索和重排提升命中质量" />
              <FeatureLine icon={<ShieldCheck className="h-4 w-4" />} text="API Key 加密存储，支持 BYOK" />
              <FeatureLine icon={<Database className="h-4 w-4" />} text="Postgres + Milvus Lite 本地持久化" />
            </div>
          </div>
        </div>

        <div className="kf-brand-panel-bottom grid grid-cols-3 gap-2 text-xs">
          <BottomPill icon={<BookOpen className="h-3.5 w-3.5" />} text="知识库" />
          <BottomPill icon={<LockKeyhole className="h-3.5 w-3.5" />} text="BYOK" />
          <BottomPill icon={<CheckCircle2 className="h-3.5 w-3.5" />} text="MIT" />
        </div>
      </div>
    </div>
  );
}

function FeatureLine({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="kf-brand-panel-row flex items-center gap-2 rounded-md border px-3 py-2 text-xs">
      <span className="kf-brand-panel-icon">{icon}</span>
      <span>{text}</span>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="kf-brand-panel-stat rounded-md border px-3 py-2">
      <div className="kf-brand-panel-stat-label text-[10px] tracking-wide">{label}</div>
      <div className="mt-1 text-sm font-semibold">{value}</div>
    </div>
  );
}

function BottomPill({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="kf-brand-panel-pill flex items-center justify-center gap-1.5 rounded-md border px-2 py-2">
      {icon}
      {text}
    </div>
  );
}
