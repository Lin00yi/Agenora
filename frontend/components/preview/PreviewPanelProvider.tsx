"use client";

import { ArrowLeft, Braces, GitBranch, XIcon } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ConversationExecutionOverview } from "@/components/chat/ConversationExecutionOverview";
import type { TraceNodePreview } from "@/components/admin/SpanWaterfall";
import { cn } from "@/lib/cn";

const MIN_PREVIEW_WIDTH = 360;
const MAX_PREVIEW_RATIO = 0.72;
const DEFAULT_PREVIEW_WIDTH = 520;

type TextPreview = {
  kind: "text";
  title: string;
  subtitle?: string;
  language?: "json" | "jsonl" | "text";
  content: string;
};

type TraceIoPreview = {
  kind: "trace-io";
  title: string;
  subtitle?: string;
  input?: string | null;
  output?: string | null;
  error?: string | null;
  metadata?: Record<string, unknown> | null;
};

type ExecutionOverviewPreview = {
  kind: "execution-overview";
  title: string;
  subtitle?: string;
  conversationId: string | null;
};

export type PreviewPayload = TextPreview | TraceIoPreview | ExecutionOverviewPreview;

type PreviewPanelContextValue = {
  preview: PreviewPayload | null;
  openPreview: (payload: PreviewPayload) => void;
  pushPreview: (payload: PreviewPayload) => void;
  closePreview: () => void;
  canGoBack: boolean;
};

const PreviewPanelContext = createContext<PreviewPanelContextValue | null>(null);

export function PreviewPanelProvider({ children }: { children: ReactNode }) {
  const [previewStack, setPreviewStack] = useState<PreviewPayload[]>([]);
  const [width, setWidth] = useState(DEFAULT_PREVIEW_WIDTH);
  const [isDesktop, setIsDesktop] = useState(false);
  const dragging = useRef(false);

  const openPreview = useCallback((payload: PreviewPayload) => {
    setPreviewStack([payload]);
  }, []);

  const pushPreview = useCallback((payload: PreviewPayload) => {
    setPreviewStack((current) => [...current, payload]);
  }, []);

  const closePreview = useCallback(() => {
    setPreviewStack((current) => (current.length > 1 ? current.slice(0, -1) : []));
  }, []);

  const preview = previewStack.at(-1) ?? null;
  const canGoBack = previewStack.length > 1;

  const clampWidth = useCallback((next: number) => {
    const max = Math.max(MIN_PREVIEW_WIDTH, Math.floor(window.innerWidth * MAX_PREVIEW_RATIO));
    return Math.min(max, Math.max(MIN_PREVIEW_WIDTH, next));
  }, []);

  useEffect(() => {
    const onResize = () => setWidth((current) => clampWidth(current));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [clampWidth]);

  useEffect(() => {
    const query = window.matchMedia("(min-width: 768px)");
    const sync = () => setIsDesktop(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    if (!preview) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closePreview();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [preview, closePreview]);

  const onResizePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragging.current = true;
    const startX = event.clientX;
    const startWidth = width;
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const onMove = (moveEvent: PointerEvent) => {
      if (!dragging.current) return;
      setWidth(clampWidth(startWidth + (startX - moveEvent.clientX)));
    };
    const onUp = () => {
      dragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const value = useMemo(
    () => ({ preview, openPreview, pushPreview, closePreview, canGoBack }),
    [preview, openPreview, pushPreview, closePreview, canGoBack]
  );

  const open = preview != null;
  const useMobileExecutionDrawer =
    !isDesktop && previewStack.some((item) => item.kind === "execution-overview");

  return (
    <PreviewPanelContext.Provider value={value}>
      <div className="flex h-dvh w-full overflow-hidden">
        <div className="preview-main min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto">
          {children}
        </div>
        {!useMobileExecutionDrawer ? (
          <aside
            aria-hidden={!open}
            data-state={open ? "open" : "closed"}
            className={cn(
              "relative flex h-dvh shrink-0 flex-col overflow-hidden border-l border-surface-border/80 bg-surface duration-surface ease-ui-drawer data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-right-4 motion-reduce:animate-none",
              open ? "opacity-100" : "pointer-events-none border-l-transparent opacity-0"
            )}
            style={{ width: open ? width : 0 }}
          >
            {open ? (
              <>
                <div
                  role="separator"
                  aria-orientation="vertical"
                  aria-label="调整预览宽度"
                  onPointerDown={onResizePointerDown}
                  className="absolute inset-y-0 left-0 z-10 w-1.5 cursor-col-resize bg-transparent hover:bg-brand/30"
                />
                <PreviewPane preview={preview} onClose={closePreview} canGoBack={canGoBack} />
              </>
            ) : null}
          </aside>
        ) : null}
      </div>
      {useMobileExecutionDrawer ? (
        <MobilePreviewDrawer preview={preview} onClose={closePreview} canGoBack={canGoBack} />
      ) : null}
    </PreviewPanelContext.Provider>
  );
}

export function usePreviewPanel() {
  const context = useContext(PreviewPanelContext);
  if (!context) {
    throw new Error("usePreviewPanel must be used within PreviewPanelProvider");
  }
  return context;
}

function PreviewPane({
  preview,
  onClose,
  canGoBack,
}: {
  preview: PreviewPayload;
  onClose: () => void;
  canGoBack: boolean;
}) {
  if (preview.kind === "execution-overview") {
    return <ExecutionOverviewPreviewPanel preview={preview} onClose={onClose} canGoBack={canGoBack} />;
  }
  if (preview.kind === "trace-io") {
    return <TraceIoPreviewPanel preview={preview} onClose={onClose} canGoBack={canGoBack} />;
  }
  return <TextPreviewPanel preview={preview} onClose={onClose} canGoBack={canGoBack} />;
}

function ExecutionOverviewPreviewPanel({
  preview,
  onClose,
  canGoBack,
}: {
  preview: ExecutionOverviewPreview;
  onClose: () => void;
  canGoBack: boolean;
}) {
  const [activeTab, setActiveTab] = useState<"trace" | "node">("trace");
  const [nodePreview, setNodePreview] = useState<TraceNodePreview | null>(null);

  useEffect(() => {
    setActiveTab("trace");
    setNodePreview(null);
  }, [preview.conversationId]);

  const handleNodePreview = useCallback((next: TraceNodePreview | null) => {
    setNodePreview(next);
    if (next) setActiveTab("node");
  }, []);

  return (
    <>
      <PreviewHeader
        icon={<GitBranch className="h-4 w-4" />}
        title={preview.title}
        subtitle={preview.subtitle ?? "按回复轮次查看工具、耗时与失败原因"}
        onClose={onClose}
        canGoBack={canGoBack}
      />
      <Tabs
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as "trace" | "node")}
        className="min-h-0 flex-1 gap-0"
      >
        <TabsList size="small" aria-label="执行详情分区" className="mx-4 mt-3 self-start">
          <TabsTrigger value="trace">执行链路</TabsTrigger>
          <TabsTrigger value="node" disabled={!nodePreview}>节点详情</TabsTrigger>
        </TabsList>
        <TabsContent value="trace" className="m-0 min-h-0 flex-1 overflow-auto p-4">
          <ConversationExecutionOverview
            conversationId={preview.conversationId}
            onNodePreview={handleNodePreview}
          />
        </TabsContent>
        <TabsContent value="node" className="m-0 min-h-0 flex-1 overflow-auto p-4">
          {nodePreview ? (
            <div className="space-y-4">
              <div>
                <p className="text-sm font-medium text-ink">{nodePreview.title}</p>
                <p className="mt-0.5 text-xs text-muted">{nodePreview.subtitle}</p>
              </div>
              <TraceIoPreviewContent preview={nodePreview} />
            </div>
          ) : null}
        </TabsContent>
      </Tabs>
    </>
  );
}

function MobilePreviewDrawer({
  preview,
  onClose,
  canGoBack,
}: {
  preview: PreviewPayload | null;
  onClose: () => void;
  canGoBack: boolean;
}) {
  return (
    <Dialog open={preview != null} onOpenChange={(next) => !next && onClose()}>
      <DialogContent
        aria-describedby={undefined}
        className="!bottom-0 !top-auto !max-h-[min(80dvh,720px)] !max-w-none !-translate-x-1/2 !translate-y-0 rounded-b-none rounded-t-[1.25rem] border-x-0 border-b-0 p-0 md:hidden"
        showCloseButton={false}
      >
        <DialogTitle className="sr-only">{preview?.title ?? "预览"}</DialogTitle>
        {preview ? (
          <div className="flex min-h-0 max-h-[min(80dvh,720px)] flex-col pb-[max(1rem,env(safe-area-inset-bottom))]">
            <PreviewPane preview={preview} onClose={onClose} canGoBack={canGoBack} />
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function PreviewHeader({
  icon,
  title,
  subtitle,
  extra,
  onClose,
  canGoBack = false,
}: {
  icon: ReactNode;
  title: string;
  subtitle?: string;
  extra?: ReactNode;
  onClose: () => void;
  canGoBack?: boolean;
}) {
  return (
    <header className="flex items-center gap-3 border-b border-surface-border/70 px-4 py-3">
      <span className="admin-icon-tile admin-icon-tile-brand">{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-ink">{title}</div>
        {subtitle ? <p className="mt-0.5 truncate text-xs text-muted">{subtitle}</p> : null}
      </div>
      {extra}
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        className="app-dialog-close shrink-0 rounded-full text-muted hover:bg-surface-2 hover:text-ink"
        aria-label={canGoBack ? "返回执行链路" : "关闭"}
        title={canGoBack ? "返回执行链路" : "关闭"}
        onClick={onClose}
      >
        {canGoBack ? <ArrowLeft /> : <XIcon />}
        <span className="sr-only">{canGoBack ? "返回执行链路" : "关闭"}</span>
      </Button>
    </header>
  );
}

function TextPreviewPanel({
  preview,
  onClose,
  canGoBack,
}: {
  preview: TextPreview;
  onClose: () => void;
  canGoBack: boolean;
}) {
  return (
    <>
      <PreviewHeader
        icon={<Braces className="h-4 w-4" />}
        title={preview.title}
        subtitle={preview.subtitle ?? (preview.language === "jsonl" ? "JSONL" : preview.language === "json" ? "JSON" : "文本")}
        onClose={onClose}
        canGoBack={canGoBack}
      />
      <div className="min-h-0 flex-1 overflow-auto p-4">
        <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-ink">
          {formatPreviewText(preview.content, preview.language)}
        </pre>
      </div>
    </>
  );
}

function TraceIoPreviewPanel({
  preview,
  onClose,
  canGoBack,
}: {
  preview: TraceIoPreview;
  onClose: () => void;
  canGoBack: boolean;
}) {
  return (
    <>
      <PreviewHeader
        icon={<Braces className="h-4 w-4" />}
        title={preview.title}
        subtitle={preview.subtitle ?? "输入 / 输出"}
        onClose={onClose}
        canGoBack={canGoBack}
      />
      <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
        <TraceIoPreviewContent preview={preview} />
      </div>
    </>
  );
}

function TraceIoPreviewContent({ preview }: { preview: TraceIoPreview | TraceNodePreview }) {
  return (
    <>
        {preview.input ? (
          <section className="rounded-lg border border-surface-border/80 bg-surface-2/30 p-3">
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">输入</h3>
            <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-ink">
              {formatPreviewText(preview.input, "json")}
            </pre>
          </section>
        ) : null}
        {preview.output ? (
          <section className="rounded-lg border border-surface-border/80 bg-surface-2/30 p-3">
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">输出</h3>
            <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-ink">
              {formatPreviewText(preview.output, "json")}
            </pre>
          </section>
        ) : null}
        {preview.error ? (
          <section className="rounded-lg border border-danger/30 bg-danger/5 p-3">
            <h3 className="mb-2 text-[11px] font-semibold uppercase text-danger">错误</h3>
            <p className="text-pretty break-words text-sm leading-6 text-danger">{preview.error}</p>
          </section>
        ) : null}
        {preview.metadata && Object.keys(preview.metadata).length > 0 ? (
          <section className="rounded-lg border border-surface-border/80 bg-surface-2/30 p-3">
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Metadata</h3>
            <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-ink">
              {formatPreviewText(JSON.stringify(preview.metadata, null, 2), "json")}
            </pre>
          </section>
        ) : null}
        {!preview.input && !preview.output && !preview.error && !(preview.metadata && Object.keys(preview.metadata).length > 0) ? (
          <p className="text-sm text-muted">
            没有可预览的输入或输出。若为新 Trace，请确认后端已开启 TRACE_STORE_IO。
          </p>
        ) : null}
    </>
  );
}

function formatPreviewText(content: string, language?: "json" | "jsonl" | "text") {
  const trimmed = content.trim();
  if (!trimmed) return content;
  if (language === "jsonl") {
    return trimmed
      .split(/\r?\n/)
      .map((line) => {
        try {
          return JSON.stringify(JSON.parse(line), null, 2);
        } catch {
          return line;
        }
      })
      .join("\n\n");
  }
  if (language === "json" || language === undefined) {
    try {
      return JSON.stringify(JSON.parse(trimmed), null, 2);
    } catch {
      return content;
    }
  }
  return content;
}
