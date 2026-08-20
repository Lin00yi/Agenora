"use client";

import { cn } from "@/lib/cn";
import { EMPTY_PROMPTS } from "./constants";

export function EmptyWorkbench({
  currentKbName,
  onPick,
  centered = false,
}: {
  currentKbName: string | null;
  onPick: (q: string) => void;
  centered?: boolean;
}) {
  const kbBound = Boolean(currentKbName);
  return (
    <div className={cn("flex items-center justify-center", centered ? "pt-12 sm:pt-20" : "min-h-full py-2")}>
      <section className="kf-empty-workbench w-full max-w-[720px] px-5 py-8 sm:px-10">
        <div className="text-center">
          {kbBound ? (
            <div className="text-sm font-medium text-[color:var(--chat-muted)]">
              {"\u5df2\u8fde\u63a5 "}
              <span className="text-[color:var(--chat-ink)]">{currentKbName}</span>
            </div>
          ) : null}
          <h1 className={cn("kf-empty-heading text-3xl font-semibold tracking-[-0.04em] sm:text-4xl", kbBound && "mt-4")}>
            {"\u628a\u95ee\u9898\u53d8\u6210"}<span>{"\u6e05\u6670\u7b54\u6848"}</span>
          </h1>
          <p className="kf-empty-description mx-auto mt-4 max-w-lg text-sm leading-6">
            {kbBound
              ? "从知识库中检索、推理并引用可追溯的答案。"
              : "直接开始对话，清晰地描述你的问题或目标。"}
          </p>
        </div>

        {!centered && (
          <div className="mt-8 flex flex-wrap justify-center gap-2">
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
        )}
      </section>
    </div>
  );
}
