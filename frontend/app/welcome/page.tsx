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
  Zap,
} from "lucide-react";

import Brand, { APP_NAME } from "@/components/Brand";
import ThemeToggle from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { getToken } from "@/lib/auth";

export default function WelcomePage() {
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    setSignedIn(Boolean(getToken()));
  }, []);

  return (
    <div className="app-page min-h-screen text-ink">
      <header className="app-page-header sticky top-0 z-30 border-b">
        <div className="mx-auto flex h-14 max-w-7xl items-center px-4 sm:px-6 lg:px-8">
          <Brand size="sm" showWordmark />
          <nav className="ml-8 hidden items-center gap-1 text-sm text-muted md:flex">
            <a href="#features" className="app-nav-link">能力</a>
            <a href="#workflow" className="app-nav-link">流程</a>
            <a href="#scenarios" className="app-nav-link">场景</a>
            <a
              href="https://github.com/GU-Cryptography/anykb"
              target="_blank"
              rel="noreferrer"
              className="app-nav-link"
            >
              开源
            </a>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            {signedIn ? (
              <Button asChild>
                <Link href="/">
                  进入工作台
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </Button>
            ) : (
              <>
                <Button asChild variant="outline" className="hidden sm:inline-flex">
                  <Link href="/login">登录</Link>
                </Button>
                <Button asChild>
                  <Link href="/register">
                    免费开始
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </Button>
              </>
            )}
          </div>
        </div>
      </header>

      <main>
        {/* Hero budget: Brand + headline + one sentence + CTA + one product visual */}
        <section className="welcome-hero relative overflow-hidden border-b border-surface-border/70">
          <div className="welcome-hero-wash pointer-events-none absolute inset-0" aria-hidden />
          <div className="relative mx-auto grid max-w-7xl lg:min-h-[min(72vh,40rem)] lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
            <div className="flex flex-col justify-center px-4 py-14 sm:px-6 lg:px-8 lg:py-20">
              <Brand size="lg" showWordmark className="welcome-hero-brand" />
              <h1 className="mt-8 max-w-xl text-3xl font-semibold leading-[1.15] tracking-tight text-ink sm:text-4xl lg:text-[2.5rem]">
                把分散资料变成可追问、可溯源的知识工作台
              </h1>
              <p className="mt-5 max-w-lg text-base leading-7 text-muted sm:leading-8">
                上传文档、抓取网页后直接提问。{APP_NAME} 展示检索过程与引用来源，答案可核查。
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                <Button asChild className="min-h-[44px] px-5">
                  <Link href={signedIn ? "/" : "/register"}>
                    {signedIn ? "进入工作台" : "免费开始"}
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>
                {!signedIn && (
                  <Button asChild variant="outline" className="min-h-[44px] px-5">
                    <Link href="/login">已有账号，去登录</Link>
                  </Button>
                )}
              </div>
            </div>

            <div className="welcome-hero-visual relative min-h-[22rem] border-t border-surface-border/70 lg:min-h-full lg:border-l lg:border-t-0">
              <ProductPreview />
            </div>
          </div>
        </section>

        <section id="features" className="border-b border-surface-border/70">
          <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
            <SectionHeading
              eyebrow="能力"
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

        <section id="workflow" className="border-b border-surface-border/70 bg-surface-2/25">
          <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
            <SectionHeading
              eyebrow="流程"
              title="三步把资料接入问答流"
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
            <SectionHeading eyebrow="场景" title="适合需要可信答案的团队和个人" />
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
          <div className="flex items-center gap-1 text-sm text-muted">
            <a
              href="https://github.com/GU-Cryptography/anykb"
              target="_blank"
              rel="noreferrer"
              className="app-nav-link"
            >
              GitHub
            </a>
            <Link
              href={signedIn ? "/" : "/login"}
              className="app-nav-link"
            >
              {signedIn ? "工作台" : "登录"}
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}

/** Edge-aligned product plane — one conversation scene, no stat strip. */
function ProductPreview() {
  return (
    <div className="flex h-full min-h-[22rem] flex-col bg-surface lg:min-h-full">
      <div className="flex h-14 shrink-0 items-center gap-3 border-b border-surface-border/70 px-5">
        <Brand size="sm" showWordmark={false} />
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-ink">产品资料库</div>
          <div className="text-[11px] text-muted">混合检索 · 引用来源可见</div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4 p-5 sm:p-6">
        <div className="ml-auto max-w-[90%] rounded-lg border border-brand/25 bg-brand/8 px-4 py-3 text-sm leading-6 text-ink">
          Agenora 如何保证企业数据安全？
        </div>

        <div className="mr-auto max-w-[95%] space-y-3">
          <div className="rounded-lg border border-surface-border/80 bg-canvas px-4 py-3 text-sm leading-7 text-ink">
            <div className="mb-2 flex items-center gap-2 text-xs font-medium text-brand">
              <CheckCircle2 className="h-3.5 w-3.5" />
              命中 2 个来源
            </div>
            系统按知识库隔离数据，并展示引用来源。自托管时，资料、向量和密钥都保留在你的环境中。
          </div>
          <div className="flex flex-wrap gap-2">
            <SourceChip title="安全白皮书" meta="PDF · p.8" />
            <SourceChip title="权限管理说明" meta="MD · §2.1" />
          </div>
          <div className="flex items-center gap-2 text-xs text-muted">
            <Search className="h-3.5 w-3.5 text-brand" />
            检索 420ms · 重排 310ms · 生成完成
          </div>
        </div>
      </div>
    </div>
  );
}

function SectionHeading({ eyebrow, title, desc }: { eyebrow: string; title: string; desc?: string }) {
  return (
    <div className="max-w-2xl">
      <div className="text-xs font-semibold tracking-wide text-brand">{eyebrow}</div>
      <h2 className="mt-2 text-2xl font-semibold tracking-tight text-ink sm:text-3xl">{title}</h2>
      {desc && <p className="mt-3 text-sm leading-7 text-muted">{desc}</p>}
    </div>
  );
}

function FeatureCard({ icon, title, desc }: { icon: React.ReactNode; title: string; desc: string }) {
  return (
    <div className="rounded-lg border border-surface-border/80 bg-surface p-5 shadow-soft transition-[background-color,border-color,box-shadow] hover:border-brand/35 hover:bg-surface-2/35 hover:shadow-md">
      <div className="admin-icon-tile admin-icon-tile-brand mb-4">
        {icon}
      </div>
      <h3 className="font-semibold text-ink">{title}</h3>
      <p className="mt-2 text-sm leading-7 text-muted">{desc}</p>
    </div>
  );
}

function StepCard({ n, icon, title, desc }: { n: number; icon: React.ReactNode; title: string; desc: string }) {
  return (
    <div className="rounded-lg border border-surface-border/80 bg-surface p-5 shadow-soft">
      <div className="mb-4 flex items-center gap-3">
        <span className="flex size-[var(--control-h)] items-center justify-center rounded-lg bg-brand text-sm font-semibold text-on-brand shadow-sm">
          {n}
        </span>
        <span className="text-brand">{icon}</span>
      </div>
      <h3 className="font-semibold text-ink">{title}</h3>
      <p className="mt-2 text-sm leading-7 text-muted">{desc}</p>
    </div>
  );
}

function ScenarioCard({ icon, title, desc }: { icon: React.ReactNode; title: string; desc: string }) {
  return (
    <div className="rounded-lg border border-surface-border/80 bg-surface p-5 shadow-soft transition-[background-color,border-color,box-shadow] hover:border-brand/35 hover:bg-surface-2/35 hover:shadow-md">
      <div className="admin-icon-tile admin-icon-tile-muted mb-4 text-brand">
        {icon}
      </div>
      <h3 className="font-semibold text-ink">{title}</h3>
      <p className="mt-2 text-sm leading-7 text-muted">{desc}</p>
    </div>
  );
}

function SourceChip({ title, meta }: { title: string; meta: string }) {
  return (
    <div className="rounded-lg border border-surface-border/80 bg-surface px-3 py-2 text-xs shadow-sm">
      <div className="flex items-center gap-1.5 font-medium text-ink">
        <CheckCircle2 className="h-3.5 w-3.5 text-brand" />
        {title}
      </div>
      <div className="mt-1 text-muted">{meta}</div>
    </div>
  );
}
