"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  BookOpen,
  Brain,
  CheckCircle2,
  FileText,
  Globe2,
  KeyRound,
  Layers,
  MessageSquareText,
  NotebookText,
  PenLine,
  Search,
  ShieldCheck,
  Sparkles,
  Store,
  UserRoundCheck,
  UsersRound,
  Workflow,
  Zap,
} from "lucide-react";

import Brand, { APP_NAME } from "@/components/Brand";
import ThemeToggle from "@/components/ThemeToggle";
import { getToken } from "@/lib/auth";

export default function WelcomePage() {
  const router = useRouter();

  useEffect(() => {
    if (getToken()) router.replace("/");
  }, [router]);

  return (
    <div className="min-h-screen bg-bg text-fg">
      <header className="sticky top-0 z-30 border-b border-surface-border/70 bg-surface/90 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-7xl items-center px-4 sm:px-6 lg:px-8">
          <Brand size="sm" showWordmark />
          <nav className="ml-8 hidden items-center gap-6 text-sm text-muted md:flex">
            <a href="#features" className="transition hover:text-fg">
              能力
            </a>
            <a href="#how" className="transition hover:text-fg">
              工作流
            </a>
            <a href="#scenarios" className="transition hover:text-fg">
              场景
            </a>
            <a
              href="https://github.com/GU-Cryptography/anykb"
              target="_blank"
              rel="noreferrer"
              className="transition hover:text-fg"
            >
              开源
            </a>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            <Link href="/login" className="btn btn-ghost btn-sm hidden sm:inline-flex">
              登录
            </Link>
            <Link href="/register" className="btn btn-primary btn-sm">
              免费开始
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      </header>

      <main>
        <section className="border-b border-surface-border/70 bg-surface/35">
          <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 sm:py-16 lg:px-8">
            <div className="grid items-center gap-10 lg:grid-cols-[0.92fr_1.08fr]">
              <div>
                <div className="inline-flex items-center gap-2 rounded-lg border border-surface-border/70 bg-surface px-3 py-1.5 text-xs font-medium text-muted shadow-soft">
                  <Sparkles className="h-3.5 w-3.5 text-brand" />
                  私有 RAG 知识库 · BYOK · 可自托管
                </div>
                <h1 className="mt-6 max-w-2xl text-3xl font-semibold leading-tight tracking-tight sm:text-5xl">
                  把散落的资料，整理成一个能追问的知识工作台
                </h1>
                <p className="mt-5 max-w-xl text-base leading-8 text-muted">
                  上传文档、抓取网页、绑定知识库，然后直接提问。AnyKB 会保留检索过程、引用来源和可导出的 Markdown 报告。
                </p>
                <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                  <Link href="/register" className="btn btn-primary h-11 px-5 text-sm">
                    免费开始
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                  <Link href="/login" className="btn btn-ghost h-11 px-5 text-sm">
                    已有账号，去登录
                  </Link>
                </div>
                <div className="mt-7 grid max-w-xl grid-cols-1 gap-2 text-xs text-muted sm:grid-cols-3">
                  <TrustPill icon={<ShieldCheck className="h-3.5 w-3.5" />} text="API Key 加密存储" />
                  <TrustPill icon={<KeyRound className="h-3.5 w-3.5" />} text="本地账号体系" />
                  <TrustPill icon={<Workflow className="h-3.5 w-3.5" />} text="MIT 开源" />
                </div>
              </div>

              <ProductPreview />
            </div>
          </div>
        </section>

        <section id="features" className="border-b border-surface-border/70">
          <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
            <SectionHeading
              eyebrow="Core"
              title="不是聊天壳，是可控的知识检索平台"
              desc="从向量库、重排、Web 兜底到答案导出，关键流程都能看见、配置和替换。"
            />
            <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <FeatureCard icon={<Brain className="h-5 w-5" />} title="混合检索 + 重排" desc="稠密向量、关键词召回和 Cross-encoder reranker 组合，减少漏召回和误命中。" />
              <FeatureCard icon={<BookOpen className="h-5 w-5" />} title="多源知识库" desc="支持文档上传、网页抓取、自动分块、向量化和按知识库隔离管理。" />
              <FeatureCard icon={<MessageSquareText className="h-5 w-5" />} title="透明 Agent" desc="工具调用、检索命中、耗时和生成过程实时可见，方便排查答案质量。" />
              <FeatureCard icon={<Layers className="h-5 w-5" />} title="按 KB 独立配置" desc="每个知识库可单独指定 embedding 和 reranker，适配不同资料类型。" />
              <FeatureCard icon={<Globe2 className="h-5 w-5" />} title="Web Search 兜底" desc="知识库命中不足时可补充网络检索，答案按 KB / Web 来源分段标注。" />
              <FeatureCard icon={<ShieldCheck className="h-5 w-5" />} title="数据自托管" desc="账号、密钥和知识库数据都在你的部署环境内，适合私有资料场景。" />
            </div>
          </div>
        </section>

        <section id="how" className="border-b border-surface-border/70 bg-surface/35">
          <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
            <SectionHeading
              eyebrow="Workflow"
              title="三步把资料接进来"
              desc="先配置模型，再创建知识库，最后在对话中选择知识库提问。"
            />
            <div className="mt-10 grid gap-4 md:grid-cols-3">
              <StepCard n={1} icon={<KeyRound className="h-5 w-5" />} title="配置 LLM" desc="填写 base_url、api_key 和默认模型，支持 OpenAI-compatible / Claude 等接口。" />
              <StepCard n={2} icon={<FileText className="h-5 w-5" />} title="创建知识库" desc="上传文档或粘贴网址，系统自动 ingest、chunk、embed，并显示处理状态。" />
              <StepCard n={3} icon={<Zap className="h-5 w-5" />} title="开始追问" desc="绑定知识库后直接提问，生成带引用的答案，并可导出为报告。" />
            </div>
          </div>
        </section>

        <section id="scenarios" className="border-b border-surface-border/70">
          <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
            <SectionHeading
              eyebrow="Use cases"
              title="适合需要可追溯答案的团队和个人"
            />
            <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <ScenarioCard icon={<NotebookText className="h-5 w-5" />} title="研究笔记" desc="把论文和笔记沉淀成可检索资料库，写综述时快速定位论点和页码。" />
              <ScenarioCard icon={<UserRoundCheck className="h-5 w-5" />} title="产品资料" desc="集中调研、访谈、竞品分析，做决策时直接追问历史材料。" />
              <ScenarioCard icon={<UsersRound className="h-5 w-5" />} title="团队 Wiki" desc="统一搜索技术文档、流程说明和设计记录，降低新人查找成本。" />
              <ScenarioCard icon={<PenLine className="h-5 w-5" />} title="内容素材" desc="把收藏文章和灵感材料结构化，创作时快速提取可引用内容。" />
            </div>
          </div>
        </section>

        <section className="bg-surface/35">
          <div className="mx-auto max-w-4xl px-4 py-16 text-center sm:px-6 lg:px-8">
            <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
              让知识库从“存起来”变成“问得出来”
            </h2>
            <p className="mx-auto mt-4 max-w-2xl text-sm leading-7 text-muted">
              注册后即可开始配置模型和知识库。部署在本地 Docker 中时，数据仍留在你的环境里。
            </p>
            <div className="mt-7 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Link href="/register" className="btn btn-primary h-11 px-6">
                立即免费开始
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link href="/login" className="btn btn-ghost h-11 px-6">
                登录已有账号
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-surface-border/70 bg-surface">
        <div className="mx-auto flex max-w-7xl flex-col items-center gap-4 px-4 py-8 sm:flex-row sm:justify-between sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <Brand size="sm" showWordmark={false} />
            <span className="text-sm text-muted">
              © {new Date().getFullYear()} {APP_NAME} · MIT License
            </span>
          </div>
          <div className="flex items-center gap-5 text-sm text-muted">
            <a href="https://github.com/GU-Cryptography/anykb" target="_blank" rel="noreferrer" className="transition hover:text-fg">
              GitHub
            </a>
            <Link href="/login" className="transition hover:text-fg">
              登录
            </Link>
            <Link href="/register" className="transition hover:text-fg">
              注册
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}

function ProductPreview() {
  return (
    <div className="rounded-lg border border-surface-border/80 bg-surface shadow-lift">
      <div className="flex h-10 items-center justify-between border-b border-surface-border/70 bg-surface-2 px-4">
        <div className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-danger/60" />
          <span className="h-2.5 w-2.5 rounded-full bg-warning/60" />
          <span className="h-2.5 w-2.5 rounded-full bg-success/60" />
        </div>
        <div className="text-[11px] text-muted">anykb.local · 我的论文库</div>
      </div>
      <div className="grid gap-0 md:grid-cols-[240px_1fr]">
        <aside className="border-b border-surface-border/70 bg-bg/60 p-4 md:border-b-0 md:border-r">
          <div className="mb-3 text-xs font-semibold uppercase text-muted">知识库</div>
          <div className="space-y-2">
            <PreviewKbItem icon={<NotebookText className="h-3.5 w-3.5" />} label="论文笔记" count={32} active />
            <PreviewKbItem icon={<Store className="h-3.5 w-3.5" />} label="上海餐厅" count={18} />
            <PreviewKbItem icon={<UsersRound className="h-3.5 w-3.5" />} label="公司 Wiki" count={147} />
            <PreviewKbItem icon={<BookOpen className="h-3.5 w-3.5" />} label="收藏文章" count={56} />
          </div>
          <div className="mt-4 rounded-lg border border-surface-border/70 bg-surface p-3 text-xs text-muted">
            <div className="mb-2 flex items-center gap-2 font-medium text-fg">
              <Search className="h-3.5 w-3.5 text-brand" />
              检索配置
            </div>
            Hybrid search · reranker on
          </div>
        </aside>
        <section className="p-4 sm:p-5">
          <div className="rounded-lg border border-surface-border/70 bg-bg px-4 py-3 text-sm">
            <span className="text-muted">你：</span>
            Transformer 里的 Q/K/V 分别代表什么？
          </div>
          <div className="mt-3 rounded-lg border border-brand/25 bg-brand/5 p-4 text-sm leading-7">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-xs font-medium text-brand">
                <Sparkles className="h-3.5 w-3.5" />
                AnyKB · 命中 3 篇论文
              </div>
              <span className="rounded-md border border-brand/25 bg-surface px-2 py-0.5 text-[11px] text-muted">
                1.2s
              </span>
            </div>
            Q 是当前位置提出的查询，K 是其他位置提供的索引特征，V 是实际参与加权汇总的内容表示。
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <SourceChip title="Attention Is All You Need" meta="p.3" />
              <SourceChip title="Transformer 综述" meta="§2.1" />
            </div>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            <PreviewStat label="Documents" value="32" />
            <PreviewStat label="Chunks" value="1,284" />
            <PreviewStat label="Sources" value="3" />
          </div>
        </section>
      </div>
    </div>
  );
}

function TrustPill({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-surface-border/70 bg-surface px-3 py-2 shadow-soft">
      <span className="text-brand">{icon}</span>
      <span>{text}</span>
    </div>
  );
}

function SectionHeading({
  eyebrow,
  title,
  desc,
}: {
  eyebrow: string;
  title: string;
  desc?: string;
}) {
  return (
    <div className="max-w-2xl">
      <div className="text-xs font-semibold uppercase tracking-wide text-brand">{eyebrow}</div>
      <h2 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h2>
      {desc && <p className="mt-3 text-sm leading-7 text-muted">{desc}</p>}
    </div>
  );
}

function FeatureCard({ icon, title, desc }: { icon: React.ReactNode; title: string; desc: string }) {
  return (
    <div className="rounded-lg border border-surface-border/80 bg-surface p-5 shadow-soft transition hover:border-brand/35 hover:shadow-lift">
      <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-brand/10 text-brand">
        {icon}
      </div>
      <h3 className="font-semibold">{title}</h3>
      <p className="mt-2 text-sm leading-7 text-muted">{desc}</p>
    </div>
  );
}

function StepCard({ n, icon, title, desc }: { n: number; icon: React.ReactNode; title: string; desc: string }) {
  return (
    <div className="rounded-lg border border-surface-border/80 bg-surface p-5 shadow-soft">
      <div className="mb-4 flex items-center gap-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand text-sm font-semibold text-white">
          {n}
        </span>
        <span className="text-brand">{icon}</span>
      </div>
      <h3 className="font-semibold">{title}</h3>
      <p className="mt-2 text-sm leading-7 text-muted">{desc}</p>
    </div>
  );
}

function ScenarioCard({ icon, title, desc }: { icon: React.ReactNode; title: string; desc: string }) {
  return (
    <div className="rounded-lg border border-surface-border/80 bg-surface p-5 shadow-soft transition hover:border-brand/35 hover:shadow-lift">
      <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-surface-2 text-brand">
        {icon}
      </div>
      <h3 className="font-semibold">{title}</h3>
      <p className="mt-2 text-sm leading-7 text-muted">{desc}</p>
    </div>
  );
}

function PreviewKbItem({
  icon,
  label,
  count,
  active,
}: {
  icon: React.ReactNode;
  label: string;
  count: number;
  active?: boolean;
}) {
  return (
    <div
      className={`flex items-center justify-between rounded-lg border px-3 py-2 text-xs ${
        active ? "border-brand/45 bg-brand/10 text-fg" : "border-surface-border/70 bg-surface text-muted"
      }`}
    >
      <span className="flex items-center gap-2">
        <span className={active ? "text-brand" : "text-muted"}>{icon}</span>
        {label}
      </span>
      <span>{count}</span>
    </div>
  );
}

function SourceChip({ title, meta }: { title: string; meta: string }) {
  return (
    <div className="rounded-lg border border-surface-border/70 bg-surface px-3 py-2 text-xs">
      <div className="flex items-center gap-1.5 font-medium text-fg">
        <CheckCircle2 className="h-3.5 w-3.5 text-brand" />
        {title}
      </div>
      <div className="mt-1 text-muted">{meta}</div>
    </div>
  );
}

function PreviewStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-surface-border/70 bg-bg px-3 py-2">
      <div className="text-[11px] uppercase text-muted">{label}</div>
      <div className="mt-1 text-sm font-semibold">{value}</div>
    </div>
  );
}
