"use client";

import type { ReactNode } from "react";
import { BookOpen, Database, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/cn";
import { EMPTY_PROMPTS } from "./constants";

export function EmptyWorkbench({
  currentKbName,
  onPick,
  centered = false,
}: {
  currentKbName: string;
  onPick: (q: string) => void;
  centered?: boolean;
}) {
  return (
    <div className={cn("flex items-center justify-center", centered ? "pt-12 sm:pt-20" : "min-h-full py-2")}>
      <section className="kf-empty-workbench w-full max-w-[720px] px-5 py-8 sm:px-10">
        <div className="text-center">
          <div className="text-sm font-medium text-[color:var(--chat-muted)]">
            {"\u5df2\u8fde\u63a5 "}
            <span className="text-[color:var(--chat-ink)]">{currentKbName}</span>
          </div>
          <h1 className="kf-empty-heading mt-4 text-3xl font-semibold tracking-[-0.04em] sm:text-4xl">
            {"\u628a\u95ee\u9898\u53d8\u6210"}<span>{"\u6e05\u6670\u7b54\u6848"}</span>
          </h1>
          <p className="kf-empty-description mx-auto mt-4 max-w-lg text-sm leading-6">
            {"\u4ece\u77e5\u8bc6\u5e93\u4e2d\u68c0\u7d22\u3001\u63a8\u7406\u5e76\u5f15\u7528\u53ef\u8ffd\u6eaf\u7684\u7b54\u6848\u3002"}
          </p>
        </div>

        {!centered && (
          <>
            <div className="mt-8 grid gap-3 sm:grid-cols-3">
              <EmptyStat icon={<Database className="h-4 w-4" />} label="知识库" value={currentKbName} />
              <EmptyStat icon={<SlidersHorizontal className="h-4 w-4" />} label="检索模式" value="混合检索" />
              <EmptyStat icon={<ShieldCheck className="h-4 w-4" />} label="数据策略" value="BYOK / 私有化" />
            </div>

            <div className="mt-5 flex flex-wrap gap-2">
              {EMPTY_PROMPTS.map((item) => (
                <button
                  className="kf-empty-prompt rounded-lg border px-3 py-2 text-sm transition"
                  key={item}
                  onClick={() => onPick(item)}
                  type="button"
                >
                  {item}
                </button>
              ))}
            </div>
          </>
        )}
      </section>
    </div>
  );
}

export function StarterPromptCards({ onPick }: { onPick: (q: string) => void }) {
  const cards = [
    { icon: <BookOpen className="h-4 w-4" />, title: "资料总结", prompt: EMPTY_PROMPTS[1] },
    { icon: <ShieldCheck className="h-4 w-4" />, title: "权限与安全", prompt: EMPTY_PROMPTS[2] },
    { icon: <SlidersHorizontal className="h-4 w-4" />, title: "开始探索", prompt: EMPTY_PROMPTS[0] },
  ];
  return (
    <div className="kf-starter-prompts grid gap-3 pb-8 sm:grid-cols-3">
      {cards.map((card) => (
        <button key={card.title} className="kf-starter-card text-left" onClick={() => onPick(card.prompt)} type="button">
          <span className="kf-starter-icon">{card.icon}</span>
          <span className="min-w-0">
            <span className="block text-sm font-medium">{card.title}</span>
            <span className="mt-1 block truncate text-xs">{card.prompt}</span>
          </span>
        </button>
      ))}
    </div>
  );
}

export function EmptyStat({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="kf-empty-stat rounded-lg border px-3 py-3">
      <div className="flex items-center gap-2 text-xs">
        <span className="kf-empty-stat-icon">{icon}</span>
        {label}
      </div>
      <div className="kf-empty-stat-value mt-2 truncate text-sm font-medium" title={value}>
        {value}
      </div>
    </div>
  );
}
