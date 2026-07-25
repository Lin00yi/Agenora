"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Database,
  FileText,
  Globe2,
  KeyRound,
  Layers,
  MessageSquareText,
  NotebookText,
  PenLine,
  Search,
  ShieldCheck,
  UsersRound,
  Workflow,
  Zap,
} from "lucide-react";

import Brand, { APP_NAME } from "@/components/Brand";
import ThemeToggle from "@/components/ThemeToggle";
import { getToken } from "@/lib/auth";

export default function WelcomePage() {
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    setSignedIn(Boolean(getToken()));
  }, []);

  return (
    <div className="app-page min-h-screen text-fg">
      <header className="app-page-header sticky top-0 z-30 border-b">
        <div className="mx-auto flex h-14 max-w-7xl items-center px-4 sm:px-6 lg:px-8">
          <Brand size="sm" showWordmark />
          <nav className="ml-8 hidden items-center gap-6 text-sm text-muted md:flex">
            <a href="#features" className="transition hover:text-fg">能力</a>
            <a href="#workflow" className="transition hover:text-fg">流程</a>
            <a href="#scenarios" className="transition hover:text-fg">场景</a>
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
            {signedIn ? (
              <Link href="/" className="btn btn-primary btn-sm">
                进入工作台
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            ) : (
              <>
                <Link href="/login" className="btn btn-ghost btn-sm hidden sm:inline-flex">
                  登录
                </Link>
                <Link href="/register" className="btn btn-primary btn-sm">
                  免费开始
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </>
            )}
          </div>
        </div>
      </header>

      <main>
        <section className="border-b border-surface-border/70 bg-surface/35">
          <div className="mx-auto grid max-w-7xl items-center gap-10 px-4 py-14 sm:px-6 lg:grid-cols-[0.92fr_1.08fr] lg:px-8">
            <div>
              <div className="inline-flex items-center gap-2 rounded-lg border border-surface-border/70 bg-surface px-3 py-1.5 text-xs font-medium text-muted shadow-soft">
                <Database className="h-3.5 w-3.5 text-brand" />
                私有知识库 · BYOK · 可自托管
              </div>
              <h1 className="mt-6 max-w-2xl text-3xl font-semibold leading-tight tracking-tight sm:text-5xl">
                把分散资料变成可追问、可溯源的知识工作台
              </h1>
              <p className="mt-5 max-w-xl text-base leading-8 text-muted">
                上传文档、抓取网页、选择知识库后直接提问。{APP_NAME} 会展示检索过程、引用来源和生成状态，方便排查答案质量。
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                <Link href={signedIn ? "/" : "/register"} className="btn btn-primary h-11 px-5 text-sm">
                  {signedIn ? "进入工作台" : "免费开始"}
                  <ArrowRight className="h-4 w-4" />
                </Link>
                {!signedIn && (
                  <Link href="/login" className="btn btn-ghost h-11 px-5 text-sm">
                    已有账号，去登录
                  </Link>
                )}
              </div>
              <div className="mt-7 grid max-w-xl grid-cols-1 gap-2 text-xs text-muted sm:grid-cols-3">
                <TrustPill icon={<ShieldCheck className="h-3.5 w-3.5" />} text="密钥加密存储" />
                <TrustPill icon={<KeyRound className="h-3.5 w-3.5" />} text="本地账号体系" />
                <TrustPill icon={<Workflow className="h-3.5 w-3.5" />} text="Docker 自托管" />
              </div>
            </div>

            <ProductPreview />
          </div>
        </section>

        <section id="features" className="border-b border-surface-border/70">
          <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
            <SectionHeading
              eyebrow="Core"
              title="不是普通聊天页，是可控的知识检索工作台"
              desc="从知识库隔离、混合检索、重排到工具调用记录，关键过程都能被查看和排查。"
            />
            <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <FeatureCard icon={<Search className="h-5 w-5" />} title="混合检索" desc="结合关键词、向量和重排，减少漏召回与误命中。" />
              <FeatureCard icon={<BookOpen className="h-5 w-5" />} title="多源知识库" desc="支持文档、网页、笔记等资料接入，并按知识库隔离管理。" />
              <FeatureCard icon={<MessageSquareText className="h-5 w-5" />} title="透明回答过程" desc="检索、重排、工具调用和生成状态实时展示。" />
              <FeatureCard icon={<Layers className="h-5 w-5" />} title="独立配置" desc="每个知识库可独立设置 embedding、reranker 和处理策略。" />
              <FeatureCard icon={<Globe2 className="h-5 w-5" />} title="Web Search 兜底" desc="知识库命中不足时，可补充网络检索。" />
              <FeatureCard icon={<ShieldCheck className="h-5 w-5" />} title="数据自托管" desc="账号、密钥、资料和向量数据都留在你的部署环境中。" />
            </div>
          </div>
        </section>

        <section id="workflow" className="border-b border-surface-border/70 bg-surface/35">
          <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
            <SectionHeading
              eyebrow="Workflow"
              title="三步把资料接入问答流程"
              desc="配置模型、创建知识库、在会话中选择知识库后开始追问。"
            />
            <div className="mt-10 grid gap-4 md:grid-cols-3">
              <StepCard n={1} icon={<KeyRound className="h-5 w-5" />} title="配置模型" desc="填写 OpenAI-compatible 模型服务，支持系统默认或个人 BYOK。" />
              <StepCard n={2} icon={<FileText className="h-5 w-5" />} title="上传资料" desc="上传文档或导入网页，系统自动切分、向量化并建立索引。" />
              <StepCard n={3} icon={<Zap className="h-5 w-5" />} title="开始追问" desc="在会话中选择知识库，答案会附带来源和过程记录。" />
            </div>
          </div>
        </section>

        <section id="scenarios" className="border-b border-surface-border/70">
          <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
            <SectionHeading eyebrow="Use cases" title="适合需要可信答案的团队和个人" />
            <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <ScenarioCard icon={<NotebookText className="h-5 w-5" />} title="研究笔记" desc="把论文、访谈和笔记沉淀成可检索资料库。" />
              <ScenarioCard icon={<UsersRound className="h-5 w-5" />} title="团队 Wiki" desc="统一查询流程说明、技术文档和设计记录。" />
              <ScenarioCard icon={<PenLine className="h-5 w-5" />} title="内容素材" desc="把收藏文章和灵感材料结构化，创作时快速提取。" />
              <ScenarioCard icon={<ShieldCheck className="h-5 w-5" />} title="私有资料" desc="在自托管环境中处理敏感文档和内部知识。" />
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
            <Link href={signedIn ? "/" : "/login"} className="transition hover:text-fg">
              {signedIn ? "工作台" : "登录"}
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
        <div className="text-[11px] text-muted">knowflow.local · 产品资料库</div>
      </div>
      <div className="grid gap-0 md:grid-cols-[240px_1fr]">
        <aside className="border-b border-surface-border/70 bg-bg/60 p-4 md:border-b-0 md:border-r">
          <div className="mb-3 text-xs font-semibold uppercase text-muted">知识库</div>
          <div className="space-y-2">
            <PreviewKbItem icon={<Database className="h-3.5 w-3.5" />} label="产品资料库" count={42} active />
            <PreviewKbItem icon={<BookOpen className="h-3.5 w-3.5" />} label="研发规范" count={18} />
            <PreviewKbItem icon={<UsersRound className="h-3.5 w-3.5" />} label="团队 Wiki" count={147} />
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
            KnowFlow 如何保证企业数据安全？
          </div>
          <div className="mt-3 rounded-lg border border-brand/25 bg-brand/5 p-4 text-sm leading-7">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-xs font-medium text-brand">
                <CheckCircle2 className="h-3.5 w-3.5" />
                命中 3 个来源
              </div>
              <span className="rounded-md border border-brand/25 bg-surface px-2 py-0.5 text-[11px] text-muted">
                1.2s
              </span>
            </div>
            系统会按知识库隔离数据，并展示引用来源。自托管部署时，资料、向量和密钥都保留在你的环境中。
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <SourceChip title="安全白皮书" meta="PDF · p.8" />
              <SourceChip title="权限管理说明" meta="MD · §2.1" />
            </div>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            <PreviewStat label="Documents" value="42" />
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

function SectionHeading({ eyebrow, title, desc }: { eyebrow: string; title: string; desc?: string }) {
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
