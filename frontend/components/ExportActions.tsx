"use client";

import { useState } from "react";
import { Copy, Image as ImageIcon } from "lucide-react";
import { toast } from "@/lib/toast";

import ShareCardDialog from "@/components/ShareCardDialog";

type Props = {
  markdown: string;
  cost?: number | null;
  /** Optional user question that triggered this assistant answer. */
  question?: string;
};

export default function ExportActions({
  markdown,
  cost,
  question,
}: Props) {
  const [shareOpen, setShareOpen] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(markdown);
      toast.success("已复制 Markdown 到剪贴板");
    } catch {
      toast.error("复制失败");
    }
  };

  return (
    <>
      <div className="kf-export-actions mt-4 flex flex-wrap items-center gap-2 text-sm">
        <button onClick={copy} className={exportActionClass} type="button">
          <Copy className="h-4 w-4" />
          复制 Markdown
        </button>
        <button onClick={() => setShareOpen(true)} className={exportActionClass} type="button">
          <ImageIcon className="h-4 w-4" />
          分享
        </button>
        {cost != null && (
          <span className="kf-export-cost basis-full text-xs tabular-nums sm:ml-auto sm:basis-auto">
            本次已跟踪成本约 ${cost.toFixed(4)}
          </span>
        )}
      </div>

      <ShareCardDialog
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        markdown={markdown}
        question={question}
      />
    </>
  );
}

const exportActionClass =
  "kf-export-action inline-flex h-[var(--control-h)] cursor-pointer items-center gap-2 rounded-lg border px-3 text-sm font-medium transition-[background-color,border-color,color,box-shadow] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30";
