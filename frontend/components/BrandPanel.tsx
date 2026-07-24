"use client";

import { BookOpen, CheckCircle2, Database, LockKeyhole, Search, ShieldCheck } from "lucide-react";

import Brand, { APP_NAME } from "@/components/Brand";

export default function BrandPanel() {
  return (
    <div className="relative hidden overflow-hidden border-r border-surface-border bg-[#171e30] text-white lg:flex lg:flex-col">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_28%_14%,rgb(101_126_245/0.42),transparent_28%),linear-gradient(145deg,#151c32_0%,#202646_100%)]" />
      <div className="relative z-10 flex h-full flex-col p-10 xl:p-14">
        <Brand size="sm" showWordmark />

        <div className="flex flex-1 flex-col justify-center">
          <div className="max-w-md">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-indigo-200/80">
              Private knowledge workspace
            </p>
            <h2 className="text-3xl font-semibold leading-tight xl:text-4xl">
              让团队资料变成可追问、可引用的答案
            </h2>
            <p className="mt-4 text-sm leading-7 text-white/70">
              {APP_NAME} 面向私有知识库场景：模型密钥由你提供，文档和向量数据保留在自己的部署环境里。
            </p>
          </div>

          <div className="mt-10 max-w-md rounded-lg border border-white/12 bg-white/[0.06] p-4 shadow-2xl shadow-black/20">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">产品资料库</p>
                <p className="mt-1 text-xs text-white/55">Hybrid search · reranker on</p>
              </div>
              <span className="rounded-md bg-indigo-300/15 px-2 py-1 text-xs text-indigo-100">
                Ready
              </span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <MiniStat label="Docs" value="42" />
              <MiniStat label="Chunks" value="1.2k" />
              <MiniStat label="Hits" value="3" />
            </div>
            <div className="mt-4 space-y-2">
              <FeatureLine icon={<Search className="h-4 w-4" />} text="混合检索和重排提升命中质量" />
              <FeatureLine icon={<ShieldCheck className="h-4 w-4" />} text="API Key 加密存储，支持 BYOK" />
              <FeatureLine icon={<Database className="h-4 w-4" />} text="Postgres + Milvus Lite 本地持久化" />
            </div>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-2 text-xs text-white/60">
          <BottomPill icon={<BookOpen className="h-3.5 w-3.5" />} text="KB" />
          <BottomPill icon={<LockKeyhole className="h-3.5 w-3.5" />} text="BYOK" />
          <BottomPill icon={<CheckCircle2 className="h-3.5 w-3.5" />} text="MIT" />
        </div>
      </div>
    </div>
  );
}

function FeatureLine({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-white/10 bg-black/10 px-3 py-2 text-xs text-white/72">
      <span className="text-indigo-200">{icon}</span>
      <span>{text}</span>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-white/10 bg-black/15 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-white/45">{label}</div>
      <div className="mt-1 text-sm font-semibold">{value}</div>
    </div>
  );
}

function BottomPill({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex items-center justify-center gap-1.5 rounded-md border border-white/10 bg-white/[0.04] px-2 py-2">
      {icon}
      {text}
    </div>
  );
}
