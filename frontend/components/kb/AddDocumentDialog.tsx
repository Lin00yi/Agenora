"use client";

import { useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { FileUp, Link2, Upload } from "lucide-react";

import AppModal from "@/components/AppModal";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

const ACCEPT = ".md,.markdown,.txt,.pdf,.docx";

type AddDocumentDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  uploading: boolean;
  submittingUrl: boolean;
  onUploadFiles: (files: File[]) => Promise<void> | void;
  onSubmitUrl: (url: string) => Promise<void> | void;
};

export function AddDocumentDialog({
  open,
  onOpenChange,
  uploading,
  submittingUrl,
  onUploadFiles,
  onSubmitUrl,
}: AddDocumentDialogProps) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<"file" | "url">("file");
  const [url, setUrl] = useState("");
  const [pendingNames, setPendingNames] = useState<string[]>([]);
  const busy = uploading || submittingUrl;

  const resetLocal = () => {
    setMode("file");
    setUrl("");
    setPendingNames([]);
    if (fileInput.current) fileInput.current.value = "";
  };

  const handleOpenChange = (next: boolean) => {
    if (busy) return;
    if (!next) resetLocal();
    onOpenChange(next);
  };

  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (!files.length) return;
    setPendingNames(files.map((f) => f.name));
    try {
      await onUploadFiles(files);
      resetLocal();
      onOpenChange(false);
    } catch {
      // Parent shows toast; keep dialog open for retry.
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const handleUrlSubmit = async (e?: FormEvent) => {
    e?.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) return;
    try {
      await onSubmitUrl(trimmed);
      resetLocal();
      onOpenChange(false);
    } catch {
      // Parent shows toast.
    }
  };

  return (
    <AppModal
      open={open}
      onOpenChange={handleOpenChange}
      busy={busy}
      size="md"
      title="添加文档"
      description="本地文件与网页 URL 共用同一入口，先选方式再提交。"
      icon={
        <span className="admin-icon-tile admin-icon-tile-brand">
          <Upload className="h-4 w-4" />
        </span>
      }
      footer={
        mode === "url" ? (
          <>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => handleOpenChange(false)}
            >
              取消
            </Button>
            <Button
              type="button"
              disabled={!url.trim() || busy}
              onClick={() => void handleUrlSubmit()}
            >
              {submittingUrl ? "提交中…" : "开始抓取"}
            </Button>
          </>
        ) : (
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => handleOpenChange(false)}
          >
            取消
          </Button>
        )
      }
    >
      <div className="flex flex-col gap-4">
        {/* Segmented mode switch — always on top, full width */}
        <div
          role="tablist"
          aria-label="添加方式"
          className="grid grid-cols-2 gap-1 rounded-xl border border-surface-border/80 bg-surface-2/80 p-1"
        >
          <button
            type="button"
            role="tab"
            aria-selected={mode === "file"}
            disabled={busy}
            onClick={() => setMode("file")}
            className={cn(
              "inline-flex h-10 items-center justify-center gap-1.5 rounded-lg text-sm font-medium transition",
              mode === "file"
                ? "bg-surface text-ink shadow-sm ring-1 ring-surface-border/70"
                : "text-muted hover:text-ink"
            )}
          >
            <FileUp className="h-3.5 w-3.5" />
            本地上传
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "url"}
            disabled={busy}
            onClick={() => setMode("url")}
            className={cn(
              "inline-flex h-10 items-center justify-center gap-1.5 rounded-lg text-sm font-medium transition",
              mode === "url"
                ? "bg-surface text-ink shadow-sm ring-1 ring-surface-border/70"
                : "text-muted hover:text-ink"
            )}
          >
            <Link2 className="h-3.5 w-3.5" />
            抓取 URL
          </button>
        </div>

        {mode === "file" ? (
          <div>
            <input
              ref={fileInput}
              type="file"
              multiple
              accept={ACCEPT}
              onChange={(e) => void handleFileChange(e)}
              className="hidden"
            />
            <button
              type="button"
              disabled={busy}
              onClick={() => fileInput.current?.click()}
              className={cn(
                "flex min-h-[11rem] w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-surface-border/90 bg-surface-2/35 px-4 py-8 text-center transition",
                busy
                  ? "cursor-not-allowed opacity-60"
                  : "hover:border-brand/40 hover:bg-surface-2/65"
              )}
            >
              <span className="admin-icon-tile admin-icon-tile-brand shadow-none">
                <FileUp className="h-4 w-4" />
              </span>
              <div className="text-sm font-medium">
                {uploading ? "正在上传…" : "点击选择文件"}
              </div>
              <p className="max-w-sm text-xs leading-5 text-muted">
                支持 .md / .txt / .pdf / .docx，可多选。上传后在后台 ingest。
              </p>
              {pendingNames.length > 0 && (
                <p className="mt-1 max-w-full truncate px-2 text-xs text-muted">
                  {pendingNames.join("、")}
                </p>
              )}
            </button>
          </div>
        ) : (
          <form
            onSubmit={(e) => void handleUrlSubmit(e)}
            className="space-y-3 rounded-xl border border-surface-border/80 bg-surface-2/35 p-4"
          >
            <label className="block text-xs font-medium text-ink">
              网页地址
              <input
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://example.com/article"
                disabled={busy}
                className="admin-input mt-1.5 w-full"
                autoFocus
              />
            </label>
            <p className="text-xs leading-5 text-muted">
              将抓取页面正文并写入知识库，适合帮助文档、公告等公开网页。
            </p>
          </form>
        )}
      </div>
    </AppModal>
  );
}
