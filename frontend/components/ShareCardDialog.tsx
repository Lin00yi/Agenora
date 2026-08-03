"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Download, Copy, X, Loader2, Image as ImageIcon, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { APP_NAME } from "@/components/Brand";

type Props = {
  open: boolean;
  onClose: () => void;
  markdown: string;
  /** Optional user question that triggered this answer. */
  question?: string;
};

/**
 * Renders the assistant answer into a branded PNG card for sharing.
 */
export default function ShareCardDialog({
  open,
  onClose,
  markdown,
  question,
}: Props) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [rendering, setRendering] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !rendering) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, rendering]);

  if (!open || !mounted) return null;

  const toCanvas = async (): Promise<HTMLCanvasElement | null> => {
    const el = cardRef.current;
    if (!el) return null;
    const html2canvas = (await import("html2canvas")).default;
    return html2canvas(el, {
      backgroundColor: null,
      scale: 2,
      useCORS: true,
      logging: false,
    });
  };

  const onDownload = async () => {
    setRendering(true);
    try {
      const canvas = await toCanvas();
      if (!canvas) {
        toast.error("找不到可导出的卡片内容");
        return;
      }
      const link = document.createElement("a");
      const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      link.download = `${APP_NAME.toLowerCase()}-${ts}.png`;
      link.href = canvas.toDataURL("image/png");
      link.click();
      toast.success("图片已下载");
    } catch (e) {
      toast.error((e as Error).message || "导出失败");
    } finally {
      setRendering(false);
    }
  };

  const onCopy = async () => {
    setRendering(true);
    try {
      const canvas = await toCanvas();
      if (!canvas) {
        toast.error("找不到可复制的卡片内容");
        return;
      }
      if (typeof ClipboardItem === "undefined" || !navigator.clipboard.write) {
        toast.warning("当前浏览器不支持复制图片，已切换为下载");
        await onDownload();
        return;
      }
      canvas.toBlob(async (blob) => {
        if (!blob) {
          toast.error("图片生成失败");
          setRendering(false);
          return;
        }
        try {
          await navigator.clipboard.write([
            new ClipboardItem({ "image/png": blob }),
          ]);
          toast.success("图片已复制到剪贴板");
        } catch (e) {
          toast.error(`复制失败：${(e as Error).message}`);
        } finally {
          setRendering(false);
        }
      }, "image/png");
    } catch (e) {
      toast.error((e as Error).message || "复制失败");
      setRendering(false);
    }
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      onClick={() => !rendering && onClose()}
    >
      <div className="app-modal-overlay absolute inset-0" />
      <div
        onClick={(e) => e.stopPropagation()}
        className="relative flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-surface-border/80 bg-surface shadow-[0_24px_70px_rgb(15_23_42/0.22)]"
      >
        <header className="flex min-h-14 shrink-0 items-center justify-between gap-3 border-b border-surface-border/70 bg-surface px-5">
          <div className="flex min-w-0 items-center gap-3">
            <span className="admin-icon-tile admin-icon-tile-brand">
              <ImageIcon className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <h2 className="truncate text-base font-semibold">分享卡片</h2>
              <p className="text-xs text-muted">生成高清 PNG，可复制或下载</p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={rendering}
            className="admin-icon-action admin-icon-action-lg"
            aria-label="关闭分享卡片弹窗"
            type="button"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="max-h-[66vh] overflow-y-auto bg-surface-2/45 p-4 sm:p-6">
          <div
            ref={cardRef}
            className="mx-auto w-full max-w-[560px] overflow-hidden rounded-lg border border-surface-border/80 bg-surface shadow-[0_14px_36px_rgb(15_23_42/0.12)]"
          >
            <div className="app-share-card-brandbar flex items-center gap-2.5 px-5 py-3.5">
              <div className="app-share-card-brandmark flex min-h-[40px] min-w-[40px] items-center justify-center rounded-lg border">
                <Sparkles className="h-4 w-4" />
              </div>
              <div className="leading-tight">
                <div className="text-sm font-bold">{APP_NAME}</div>
                <div className="app-share-card-muted text-[10px]">你的私有知识库 · 一句话提问</div>
              </div>
            </div>

            {question && (
              <div className="border-b border-surface-border/70 bg-surface-2/45 px-5 py-3">
                <div className="text-[10px] font-medium uppercase tracking-wider text-muted">
                  问题
                </div>
                <div className="mt-1 text-sm text-fg">{question}</div>
              </div>
            )}

            <div className="px-5 py-5">
              <article className="prose-tg max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {markdown.replace(/\\n/g, "\n")}
                </ReactMarkdown>
              </article>
            </div>

            <div className="flex items-center justify-between border-t border-surface-border/70 bg-surface-2/45 px-5 py-3 text-[10px] text-muted">
              <span>
                由 <b className="text-fg">{APP_NAME}</b> 生成 · 上传文档，秒级问答
              </span>
              <span>{new Date().toLocaleDateString("zh-CN")}</span>
            </div>
          </div>
        </div>

        <footer className="flex shrink-0 flex-col gap-3 border-t border-surface-border/70 bg-surface px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted">适合朋友圈、群聊、Slack 等场景分享</p>
          <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
            <button
              type="button"
              onClick={onCopy}
              disabled={rendering}
              className={secondaryActionClass}
            >
              {rendering ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Copy className="h-4 w-4" />
              )}
              复制到剪贴板
            </button>
            <button
              type="button"
              onClick={onDownload}
              disabled={rendering}
              className={primaryActionClass}
            >
              {rendering ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              下载图片
            </button>
          </div>
        </footer>
      </div>
    </div>,
    document.body
  );
}

const primaryActionClass =
  "admin-btn-primary min-h-[40px] w-full shrink-0 px-4 text-sm sm:w-auto";

const secondaryActionClass =
  "admin-btn-secondary min-h-[40px] w-full shrink-0 px-3 text-sm sm:w-auto";
