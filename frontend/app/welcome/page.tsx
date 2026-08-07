"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  FileUp,
  MessageSquareText,
  Search,
  ShieldCheck,
} from "lucide-react";

import Brand, { APP_NAME } from "@/components/Brand";
import ThemeToggle from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { getToken } from "@/lib/auth";

const GITHUB_URL = "https://github.com/Lin00yi/Agenora";

export default function WelcomePage() {
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    setSignedIn(Boolean(getToken()));
  }, []);

  return (
    <div className="app-page min-h-screen text-ink">
      <header className="app-page-header sticky top-0 z-30 border-b">
        <div className="mx-auto flex h-14 max-w-6xl items-center px-4 sm:px-6 lg:px-8">
          <Brand size="sm" showWordmark />
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
                    开始使用
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </Button>
              </>
            )}
          </div>
        </div>
      </header>

      <main>
        <section className="welcome-hero relative overflow-hidden">
          <div className="welcome-hero-wash pointer-events-none absolute inset-0" aria-hidden />
          <div className="relative mx-auto flex min-h-[min(88vh,52rem)] max-w-6xl flex-col justify-center px-4 py-16 sm:px-6 lg:px-8 lg:py-20">
            <div className="welcome-hero-enter max-w-2xl">
              <Brand size="lg" showWordmark className="welcome-hero-brand" />
              <h1 className="mt-8 text-3xl font-semibold leading-[1.12] tracking-tight text-ink sm:text-4xl lg:text-[2.75rem]">
                把你的资料变成能追问、能溯源的答案
              </h1>
              <p className="mt-5 max-w-xl text-base leading-7 text-muted sm:text-lg sm:leading-8">
                {APP_NAME} 是我做的个人项目：私有知识库 + 透明 Agent。
                上传文档或网页后直接提问，检索过程与引用来源全程可见。
              </p>
              <div className="mt-9 flex flex-col gap-3 sm:flex-row sm:items-center">
                <Button asChild className="min-h-[44px] px-5">
                  <Link href={signedIn ? "/" : "/register"}>
                    {signedIn ? "进入工作台" : "免费开始"}
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>
                {!signedIn && (
                  <Button asChild variant="outline" className="min-h-[44px] px-5">
                    <Link href="/login">已有账号</Link>
                  </Button>
                )}
                <a
                  href={GITHUB_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm text-muted underline-offset-4 transition-colors hover:text-ink hover:underline sm:ml-2"
                >
                  查看源码
                </a>
              </div>
            </div>

            <div className="welcome-hero-preview mt-14 overflow-hidden border border-surface-border/80 bg-surface shadow-soft lg:mt-16">
              <ProductPreview />
            </div>
          </div>
        </section>

        <section className="border-t border-surface-border/70">
          <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 lg:px-8">
            <h2 className="max-w-xl text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
              三步用起来
            </h2>
            <p className="mt-3 max-w-xl text-sm leading-7 text-muted">
              配置模型、导入资料、在对话里追问——答案带原文出处。
            </p>
            <ol className="mt-10 grid gap-8 sm:grid-cols-3">
              <Step
                n={1}
                icon={<FileUp className="h-4 w-4" />}
                title="导入资料"
                desc="上传 PDF / Markdown / Word，或抓取网页，自动切分并建索引。"
              />
              <Step
                n={2}
                icon={<Search className="h-4 w-4" />}
                title="混合检索"
                desc="关键词 + 向量 + 可选重排，减少漏召回；过程可在思考链里看到。"
              />
              <Step
                n={3}
                icon={<MessageSquareText className="h-4 w-4" />}
                title="透明回答"
                desc="每条答案附带引用来源与工具调用记录，方便核查。"
              />
            </ol>
          </div>
        </section>

        <section className="border-t border-surface-border/70 bg-surface-2/30">
          <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-14 sm:flex-row sm:items-end sm:justify-between sm:px-6 lg:px-8">
            <div className="max-w-lg">
              <div className="flex items-center gap-2 text-brand">
                <ShieldCheck className="h-4 w-4" />
                <span className="text-xs font-semibold tracking-wide">本地优先</span>
              </div>
              <h2 className="mt-3 text-xl font-semibold tracking-tight text-ink sm:text-2xl">
                数据留在你自己的环境
              </h2>
              <p className="mt-3 text-sm leading-7 text-muted">
                自托管部署，模型密钥 BYOK，账号与向量库都在你的机器或服务器上。适合个人笔记、研究资料与私有文档。
              </p>
            </div>
            <Button asChild className="min-h-[44px] shrink-0 px-5">
              <Link href={signedIn ? "/" : "/register"}>
                {signedIn ? "打开工作台" : "创建账号"}
                <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
        </section>
      </main>

      <footer className="border-t border-surface-border/70 bg-surface">
        <div className="mx-auto flex max-w-6xl flex-col items-center gap-4 px-4 py-8 sm:flex-row sm:justify-between sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <Brand size="sm" showWordmark={false} />
            <span className="text-sm text-muted">
              © {new Date().getFullYear()} {APP_NAME} · 个人项目 · MIT
            </span>
          </div>
          <div className="flex items-center gap-1 text-sm text-muted">
            <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="app-nav-link">
              GitHub
            </a>
            <Link href={signedIn ? "/" : "/login"} className="app-nav-link">
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
    <div className="flex min-h-[18rem] flex-col sm:min-h-[22rem]">
      <div className="flex h-12 shrink-0 items-center gap-3 border-b border-surface-border/70 px-4 sm:h-14 sm:px-5">
        <Brand size="sm" showWordmark={false} />
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-ink">研究笔记库</div>
          <div className="text-[11px] text-muted">混合检索 · 引用来源可见</div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4 p-4 sm:p-6">
        <div className="welcome-preview-user ml-auto max-w-[90%] rounded-2xl bg-surface-2 px-4 py-3 text-sm leading-6 text-ink">
          这篇笔记里，上下文压缩是怎么工作的？
        </div>

        <div className="welcome-preview-assistant mr-auto max-w-[95%] space-y-3">
          <div className="rounded-2xl border border-surface-border/80 bg-canvas px-4 py-3 text-sm leading-7 text-ink">
            <div className="mb-2 flex items-center gap-2 text-xs font-medium text-ink">
              <CheckCircle2 className="h-3.5 w-3.5" />
              命中 2 个来源
            </div>
            长对话会先摘要再注入长期记忆；检索命中时优先引用原文段落，并在回答中标出来源。
          </div>
          <div className="flex flex-wrap gap-2">
            <SourceChip title="memory-system.md" meta="§生命周期" />
            <SourceChip title="设计笔记" meta="MD · 第 3 节" />
          </div>
          <div className="flex items-center gap-2 text-xs text-muted">
            <Search className="h-3.5 w-3.5" />
            检索 420ms · 重排 310ms · 生成完成
          </div>
        </div>
      </div>
    </div>
  );
}

function Step({
  n,
  icon,
  title,
  desc,
}: {
  n: number;
  icon: React.ReactNode;
  title: string;
  desc: string;
}) {
  return (
    <li className="welcome-step">
      <div className="flex items-center gap-3">
        <span className="flex size-8 items-center justify-center rounded-md bg-brand text-sm font-semibold text-on-brand">
          {n}
        </span>
        <span className="text-muted">{icon}</span>
      </div>
      <h3 className="mt-4 font-semibold text-ink">{title}</h3>
      <p className="mt-2 text-sm leading-7 text-muted">{desc}</p>
    </li>
  );
}

function SourceChip({ title, meta }: { title: string; meta: string }) {
  return (
    <div className="border border-surface-border/80 bg-surface px-3 py-2 text-xs">
      <div className="flex items-center gap-1.5 font-medium text-ink">
        <CheckCircle2 className="h-3.5 w-3.5" />
        {title}
      </div>
      <div className="mt-1 text-muted">{meta}</div>
    </div>
  );
}
