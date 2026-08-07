"use client";

import { useState } from "react";
import { Copy, FileText, Image as ImageIcon } from "lucide-react";
import { toast } from "sonner";

import ShareCardDialog from "@/components/ShareCardDialog";

type Props = {
  markdown: string;
  cost?: number | null;
  /** Optional user question that triggered this assistant answer. */
  question?: string;
  /** DOM id of the answer to export. */
  reportId?: string;
};

export default function ExportActions({
  markdown,
  cost,
  question,
  reportId = "report-output",
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

  const downloadPdf = async () => {
    const html2pdf = (await import("html2pdf.js")).default;
    const el = document.getElementById(reportId);
    if (!el) {
      toast.error("找不到报告内容");
      return;
    }
    html2pdf().set({ filename: "agenora-report.pdf", margin: 10 }).from(el).save();
  };

  return (
    <>
      <div className="kf-export-actions mt-4 flex flex-wrap items-center gap-2 text-sm">
        <button onClick={copy} className={exportActionClass} type="button">
          <Copy className="h-4 w-4" />
          复制 Markdown
        </button>
        <button onClick={downloadPdf} className={exportActionClass} type="button">
          <FileText className="h-4 w-4" />
          导出 PDF
        </button>
        <button onClick={() => setShareOpen(true)} className={exportActionClass} type="button">
          <ImageIcon className="h-4 w-4" />
          分享
        </button>
        {cost != null && (
          <span className="kf-export-cost basis-full text-xs tabular-nums sm:ml-auto sm:basis-auto">
            本次成本约 ${cost.toFixed(4)}
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
