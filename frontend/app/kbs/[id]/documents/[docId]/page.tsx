"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  FormEvent,
  ChangeEvent,
} from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  RefreshCw,
  RotateCcw,
  Trash2,
  Pencil,
  Eye,
  EyeOff,
  Loader2,
  Search,
  Split,
  Merge,
  MoreHorizontal,
} from "lucide-react";
import { toast } from "sonner";

import { getToken } from "@/lib/auth";
import {
  getKb,
  getDocument,
  listDocumentChunks,
  patchDocument,
  patchChunk,
  deleteChunk,
  batchPatchChunks,
  batchPatchAllChunks,
  reingestDocument,
  splitChunk,
  mergeChunks,
  type KBDetail,
  type DocumentDetail,
  type Chunk,
  type KbRole,
  type ChunkStrategy,
} from "@/lib/kb-api";
import { toastApiError } from "@/lib/byok-toast";
import { cn } from "@/lib/cn";
import Dialog from "@/components/Dialog";
import Select from "@/components/Select";
import { StateView } from "@/components/ui/state-view";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AdminPageShell,
  AdminPanel,
} from "@/components/kb/AdminPageShell";
import {
  AdminRowAction,
  AdminToolbarButton,
} from "@/components/kb/AdminTableActions";
import {
  DOC_STATUS_UI,
  estimateTokens,
  formatAdminDate,
  formatFileSize,
} from "@/components/kb/admin-utils";

const CHUNK_STRATEGY_OPTIONS: { value: ChunkStrategy; label: string }[] = [
  { value: "recursive", label: "递归文本切分" },
  { value: "markdown_heading", label: "Markdown 标题切分" },
  { value: "semantic", label: "轻量语义切分" },
  { value: "table_aware", label: "表格感知切分" },
  { value: "code", label: "代码感知切分" },
  { value: "parent_child", label: "轻量父子切分" },
];

export default function DocumentDetailPage({
  params,
}: {
  params: { id: string; docId: string };
}) {
  const { id: kbId, docId } = params;
  const router = useRouter();

  const [kb, setKb] = useState<KBDetail | null>(null);
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tableLoading, setTableLoading] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [enabledFilter, setEnabledFilter] = useState<"all" | "enabled" | "disabled">(
    "all"
  );
  const [editingChunk, setEditingChunk] = useState<Chunk | null>(null);
  const [splittingChunk, setSplittingChunk] = useState<Chunk | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Chunk | null>(null);
  const [mergeTarget, setMergeTarget] = useState<{
    chunk: Chunk;
    next: Chunk;
  } | null>(null);
  const [splitOffset, setSplitOffset] = useState("");
  const [editText, setEditText] = useState("");
  const [docChunkStrategy, setDocChunkStrategy] = useState<ChunkStrategy | "">("");
  const [docChunkTarget, setDocChunkTarget] = useState("");
  const [docChunkMaxSize, setDocChunkMaxSize] = useState("");
  const [docChunkOverlap, setDocChunkOverlap] = useState("");
  /** Granular action key, e.g. `refresh`, `batch`, `toggle:uuid`, `merge:uuid`. */
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const chunksLoadedOnce = useRef(false);

  const pageSize = 20;
  const isPending = (key: string) => pendingKey === key;
  const anyPending = pendingKey != null;

  useEffect(() => {
    setPage(1);
    setSelected([]);
    setSearchInput("");
    setDebouncedSearch("");
    setEnabledFilter("all");
    chunksLoadedOnce.current = false;
    setLoading(true);
  }, [docId]);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(searchInput), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    setPage(1);
    setSelected([]);
  }, [debouncedSearch, enabledFilter]);

  const listOpts = useMemo(
    () => ({
      q: debouncedSearch || undefined,
      enabled:
        enabledFilter === "all"
          ? null
          : enabledFilter === "enabled",
    }),
    [debouncedSearch, enabledFilter]
  );

  const refreshDoc = useCallback(async () => {
    const [kbData, docData] = await Promise.all([
      getKb(kbId),
      getDocument(kbId, docId),
    ]);
    setKb(kbData);
    setDoc(docData);
    setLoadError(null);
  }, [kbId, docId]);

  const refreshChunks = useCallback(async () => {
    const chunkData = await listDocumentChunks(
      kbId,
      docId,
      page,
      pageSize,
      listOpts
    );
    setChunks(chunkData.items);
    setTotal(chunkData.total);
  }, [kbId, docId, page, pageSize, listOpts]);

  const refresh = useCallback(async () => {
    await Promise.all([refreshDoc(), refreshChunks()]);
  }, [refreshDoc, refreshChunks]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    refresh()
      .catch((e) => {
        const message = (e as Error).message || "document not found";
        setLoadError(message);
        setKb(null);
        setDoc(null);
        setChunks([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, [kbId, docId, router]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (loading) return;
    if (!chunksLoadedOnce.current) {
      chunksLoadedOnce.current = true;
      return;
    }
    setTableLoading(true);
    refreshChunks()
      .catch((e) => toast.error((e as Error).message))
      .finally(() => setTableLoading(false));
  }, [page, debouncedSearch, enabledFilter, loading, refreshChunks]);

  useEffect(() => {
    if (!doc) return;
    if (doc.status !== "pending" && doc.status !== "ingesting") return;
    const t = setInterval(() => refresh().catch(() => {}), 2000);
    return () => clearInterval(t);
  }, [doc, refresh]);

  useEffect(() => {
    if (!doc) return;
    setDocChunkStrategy(doc.chunk_strategy ?? "");
    setDocChunkTarget(doc.chunk_target == null ? "" : String(doc.chunk_target));
    setDocChunkMaxSize(doc.chunk_max_size == null ? "" : String(doc.chunk_max_size));
    setDocChunkOverlap(doc.chunk_overlap == null ? "" : String(doc.chunk_overlap));
  }, [
    doc?.id,
    doc?.chunk_strategy,
    doc?.chunk_target,
    doc?.chunk_max_size,
    doc?.chunk_overlap,
  ]);

  const myRole: KbRole = kb?.my_role ?? (kb?.is_system ? "viewer" : "owner");
  const canWrite = (myRole === "owner" || myRole === "editor") && !kb?.is_system;

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const allPageSelected =
    chunks.length > 0 && chunks.every((c) => selected.includes(c.id));

  const toggleSelect = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const toggleSelectAllPage = () => {
    if (allPageSelected) {
      setSelected((prev) => prev.filter((id) => !chunks.some((c) => c.id === id)));
    } else {
      setSelected((prev) => [...new Set([...prev, ...chunks.map((c) => c.id)])]);
    }
  };

  const onBatchEnable = async (enabled: boolean, all = false) => {
    const key = all ? (enabled ? "batch-all-on" : "batch-all-off") : "batch";
    setPendingKey(key);
    try {
      if (all) {
        const res = await batchPatchAllChunks(kbId, docId, enabled);
        toast.success(
          `已${enabled ? "启用" : "禁用"}全部 ${res.updated} 个 chunk`
        );
      } else {
        if (selected.length === 0) return;
        const res = await batchPatchChunks(kbId, docId, selected, enabled);
        toast.success(`已${enabled ? "启用" : "禁用"} ${res.updated} 个 chunk`);
      }
      setSelected([]);
      await refreshChunks();
    } catch (e) {
      toastApiError(e, (p) => router.push(p));
    } finally {
      setPendingKey(null);
    }
  };

  const onToggleChunk = async (chunk: Chunk) => {
    const key = `toggle:${chunk.id}`;
    setPendingKey(key);
    try {
      await patchChunk(kbId, docId, chunk.id, { enabled: !chunk.enabled });
      await refreshChunks();
    } catch (e) {
      toastApiError(e, (p) => router.push(p));
    } finally {
      setPendingKey(null);
    }
  };

  const confirmDeleteChunk = async () => {
    if (!deleteTarget) return;
    const key = `delete:${deleteTarget.id}`;
    setPendingKey(key);
    try {
      await deleteChunk(kbId, docId, deleteTarget.id);
      toast.success("已删除");
      setSelected((s) => s.filter((id) => id !== deleteTarget.id));
      setDeleteTarget(null);
      await refresh();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setPendingKey(null);
    }
  };

  const onSaveChunk = async (e: FormEvent) => {
    e.preventDefault();
    if (!editingChunk) return;
    setPendingKey(`edit:${editingChunk.id}`);
    try {
      await patchChunk(kbId, docId, editingChunk.id, { text: editText });
      toast.success("已保存");
      setEditingChunk(null);
      await refreshChunks();
    } catch (err) {
      toastApiError(err, (p) => router.push(p));
    } finally {
      setPendingKey(null);
    }
  };

  const onReingest = async () => {
    setPendingKey("reingest");
    try {
      await reingestDocument(kbId, docId);
      toast.success("已提交重建向量");
      await refresh();
    } catch (e) {
      toastApiError(e, (p) => router.push(p));
    } finally {
      setPendingKey(null);
    }
  };

  const onSaveDocChunkSettings = async (e: FormEvent) => {
    e.preventDefault();
    const parseOptionalInt = (value: string) => {
      const trimmed = value.trim();
      if (!trimmed) return null;
      const parsed = parseInt(trimmed, 10);
      return Number.isFinite(parsed) ? parsed : null;
    };
    setPendingKey("doc-chunk-settings");
    try {
      const updated = await patchDocument(kbId, docId, {
        chunk_strategy: docChunkStrategy || null,
        chunk_target: parseOptionalInt(docChunkTarget),
        chunk_max_size: parseOptionalInt(docChunkMaxSize),
        chunk_overlap: parseOptionalInt(docChunkOverlap),
      });
      setDoc((cur) => (cur ? { ...cur, ...updated } : cur));
      toast.success("分块策略已保存，重新入库后对现有分块生效");
    } catch (e) {
      toastApiError(e, (p) => router.push(p));
    } finally {
      setPendingKey(null);
    }
  };

  const onRefreshAll = async () => {
    setPendingKey("refresh");
    try {
      await refresh();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setPendingKey(null);
    }
  };

  const onSplitChunk = async (e: FormEvent) => {
    e.preventDefault();
    if (!splittingChunk) return;
    const offset = parseInt(splitOffset, 10);
    if (!Number.isFinite(offset) || offset <= 0 || offset >= splittingChunk.text.length) {
      toast.error("切分位置无效");
      return;
    }
    setPendingKey(`split:${splittingChunk.id}`);
    try {
      await splitChunk(kbId, docId, splittingChunk.id, offset);
      toast.success("已切分为两个 chunk");
      setSplittingChunk(null);
      setSplitOffset("");
      await refresh();
    } catch (err) {
      toastApiError(err, (p) => router.push(p));
    } finally {
      setPendingKey(null);
    }
  };

  const onMergeWithNext = async (chunk: Chunk) => {
    try {
      let next = chunks.find((c) => c.chunk_idx === chunk.chunk_idx + 1);
      if (!next) {
        const data = await listDocumentChunks(kbId, docId, 1, 500);
        next = data.items.find((c) => c.chunk_idx === chunk.chunk_idx + 1);
      }
      if (!next) {
        toast.error("只能与相邻的下一个 chunk 合并");
        return;
      }
      setMergeTarget({ chunk, next });
    } catch (err) {
      toastApiError(err, (p) => router.push(p));
    }
  };

  const confirmMergeChunks = async () => {
    if (!mergeTarget) return;
    setPendingKey(`merge:${mergeTarget.chunk.id}`);
    try {
      await mergeChunks(kbId, docId, [mergeTarget.chunk.id, mergeTarget.next.id]);
      toast.success("已合并");
      setMergeTarget(null);
      await refresh();
    } catch (err) {
      toastApiError(err, (p) => router.push(p));
    } finally {
      setPendingKey(null);
    }
  };

  if (loading) {
    return (
      <div className="admin-page flex min-h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand" />
      </div>
    );
  }

  if (loadError || !doc || !kb) {
    return (
      <div className="flex min-h-dvh items-center justify-center px-4">
        <StateView
          variant="error"
          title="找不到这个文档"
          description="它可能已被删除、你没有访问权限，或链接已经失效。"
          className="w-full max-w-md"
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Link href={`/kbs/${kbId}`} className="admin-btn-primary">
                返回文档列表
              </Link>
              <Link href="/kbs" className="admin-btn-secondary">
                返回知识库列表
              </Link>
            </div>
          }
        />
      </div>
    );
  }

  const docStatus = DOC_STATUS_UI[doc.status];
  const enabledOnPage = chunks.filter((c) => c.enabled).length;
  const selectedText =
    selected.length > 0 ? `已选择 ${selected.length} 个 chunk` : "";

  const effectiveStrategy = doc.effective_chunk_strategy ?? kb.chunk_strategy;
  const effectiveStrategyLabel =
    CHUNK_STRATEGY_OPTIONS.find((option) => option.value === effectiveStrategy)?.label ??
    effectiveStrategy;
  const hasDocChunkOverride =
    doc.chunk_strategy != null ||
    doc.chunk_target != null ||
    doc.chunk_max_size != null ||
    doc.chunk_overlap != null;

  return (
    <AdminPageShell
      breadcrumbs={[
        { label: "首页", href: "/" },
        { label: "知识库管理", href: "/kbs" },
        { label: "文档管理", href: `/kbs/${kbId}` },
        { label: "分块管理" },
      ]}
      title="分块管理"
      subtitle={
        <>
          {doc.filename}
          <span className="mx-1.5 text-muted/50">·</span>
          <span className="text-muted">{kb.name}</span>
        </>
      }
      actions={
        <>
          <Link href={`/kbs/${kbId}`} className="admin-btn-secondary">
            返回文档
          </Link>
          {canWrite && (
            <button
              type="button"
              className="admin-btn-primary"
              disabled={anyPending}
              onClick={() => void onReingest()}
            >
              <RotateCcw
                className={cn(
                  "h-4 w-4",
                  isPending("reingest") && "animate-spin"
                )}
              />
              {isPending("reingest") ? "重建中…" : "重建向量"}
            </button>
          )}
        </>
      }
    >
      <section className="admin-panel mb-4 overflow-hidden">
        <div className="flex flex-col gap-2 bg-surface-2/35 px-5 py-3.5 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <span className={cn("chip", docStatus.badge)}>{docStatus.label}</span>
            <span className="text-sm text-muted">
              <span className="font-semibold tabular-nums text-fg">{doc.chunks_count}</span> 分块
            </span>
            <span aria-hidden className="text-surface-border">·</span>
            <span className="text-sm tabular-nums text-muted">
              {doc.parsed_text_length.toLocaleString()} 字符
            </span>
            <span aria-hidden className="text-surface-border">·</span>
            <span className="text-sm text-muted">{formatFileSize(doc.size_bytes)}</span>
          </div>
          <p className="shrink-0 text-xs text-muted">
            更新于 {formatAdminDate(doc.updated_at ?? doc.created_at)}
          </p>
        </div>
      </section>

      {canWrite && (
        <AdminPanel
          title="入库切分设置"
          subtitle={`当前生效：${effectiveStrategyLabel} · 目标 ${
            doc.effective_chunk_target ?? kb.chunk_target
          } · 最大 ${doc.effective_chunk_max_size ?? kb.chunk_max_size} · 重叠 ${
            doc.effective_chunk_overlap ?? kb.chunk_overlap
          }${hasDocChunkOverride ? " · 文档级覆盖" : " · 继承 KB 默认"}`}
          className="mb-4"
          bodyClassName="bg-surface/35"
        >
          <form
            onSubmit={onSaveDocChunkSettings}
            className="grid gap-4 border-b border-surface-border/70 p-4 md:grid-cols-[1.25fr_repeat(3,minmax(0,1fr))_auto]"
          >
            <label className="space-y-1.5 text-xs font-medium text-muted">
              <span>切分策略</span>
              <Select
                value={docChunkStrategy}
                onChange={(e) => setDocChunkStrategy(e.target.value as ChunkStrategy | "")}
                placeholderOption={{ value: "", label: "继承 KB 默认" }}
                options={CHUNK_STRATEGY_OPTIONS}
                className="h-[40px] w-full admin-select-trigger"
                contentAlign="start"
                contentPosition="popper"
              />
            </label>
            <label className="space-y-1.5 text-xs font-medium text-muted">
              <span>目标长度</span>
              <input
                type="number"
                min={200}
                max={8000}
                placeholder={String(kb.chunk_target)}
                value={docChunkTarget}
                onChange={(e) => setDocChunkTarget(e.target.value)}
                className={docInputClass}
              />
            </label>
            <label className="space-y-1.5 text-xs font-medium text-muted">
              <span>最大长度</span>
              <input
                type="number"
                min={200}
                max={10000}
                placeholder={String(kb.chunk_max_size)}
                value={docChunkMaxSize}
                onChange={(e) => setDocChunkMaxSize(e.target.value)}
                className={docInputClass}
              />
            </label>
            <label className="space-y-1.5 text-xs font-medium text-muted">
              <span>重叠长度</span>
              <input
                type="number"
                min={0}
                max={2000}
                placeholder={String(kb.chunk_overlap)}
                value={docChunkOverlap}
                onChange={(e) => setDocChunkOverlap(e.target.value)}
                className={docInputClass}
              />
            </label>
            <div className="flex items-end gap-2 md:justify-end">
              <button
                type="submit"
                className="admin-btn-secondary h-[40px]"
                disabled={anyPending}
              >
                {isPending("doc-chunk-settings") ? "保存中..." : "保存"}
              </button>
              <button
                type="button"
                className="admin-btn-primary h-[40px]"
                disabled={anyPending}
                onClick={() => void onReingest()}
                title="重新入库后，已保存的切分策略才会应用到现有分块。"
              >
                <RotateCcw
                  className={cn("h-4 w-4", isPending("reingest") && "animate-spin")}
                />
                重新 ingest
              </button>
            </div>
          </form>
          <p className="px-4 py-3 text-xs leading-5 text-muted">
            留空表示继承知识库默认。保存后仅影响新的入库；已有分块需要重新入库或重建整个知识库后才会变化。
          </p>
        </AdminPanel>
      )}

      <AdminPanel
        title="Chunk 列表"
        subtitle={`当前页 ${chunks.length} 条，启用 ${enabledOnPage} 条`}
        toolbarClassName="w-full sm:w-auto"
        toolbar={
          <>
            <div className="input-shell flex h-[40px] min-w-0 flex-1 items-center gap-2 px-3 sm:w-72 sm:flex-none">
              <Search className="h-3.5 w-3.5 shrink-0 text-muted" />
              <input
                type="search"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="搜索 chunk 内容…"
                className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted/70"
              />
            </div>
            <Select
              className="h-[40px] min-h-[40px] w-[132px] admin-select-trigger"
              value={enabledFilter}
              onChange={(e) =>
                setEnabledFilter(e.target.value as typeof enabledFilter)
              }
              options={[
                { value: "all", label: "全部状态" },
                { value: "enabled", label: "已启用" },
                { value: "disabled", label: "已禁用" },
              ]}
            />
            <AdminToolbarButton
              icon={RefreshCw}
              loading={isPending("refresh") || tableLoading}
              disabled={anyPending && !isPending("refresh")}
              onClick={() => void onRefreshAll()}
            >
              刷新
            </AdminToolbarButton>
            {canWrite && (
              <>
                <AdminToolbarButton
                  loading={isPending("batch-all-on")}
                  disabled={anyPending && !isPending("batch-all-on")}
                  onClick={() => void onBatchEnable(true, true)}
                >
                  全量启用
                </AdminToolbarButton>
                <AdminToolbarButton
                  loading={isPending("batch-all-off")}
                  disabled={anyPending && !isPending("batch-all-off")}
                  onClick={() => void onBatchEnable(false, true)}
                >
                  全量禁用
                </AdminToolbarButton>
              </>
            )}
          </>
        }
        selectionBar={
          canWrite && selected.length > 0 ? (
            <div className="flex flex-col gap-2 text-xs sm:flex-row sm:items-center sm:justify-between">
              <span className="font-medium text-brand">{selectedText}</span>
              <div className="flex flex-wrap items-center gap-2">
                <AdminToolbarButton
                  icon={Eye}
                  loading={isPending("batch")}
                  disabled={
                    anyPending ||
                    (pendingKey != null && pendingKey !== "batch")
                  }
                  onClick={() => void onBatchEnable(true)}
                >
                  批量启用
                </AdminToolbarButton>
                <AdminToolbarButton
                  icon={EyeOff}
                  loading={isPending("batch")}
                  disabled={
                    anyPending ||
                    (pendingKey != null && pendingKey !== "batch")
                  }
                  onClick={() => void onBatchEnable(false)}
                >
                  批量禁用
                </AdminToolbarButton>
                <button
                  type="button"
                  className="admin-toolbar-btn"
                  onClick={() => setSelected([])}
                >
                  清空选择
                </button>
              </div>
            </div>
          ) : null
        }
        footer={
          <div className="flex items-center justify-between text-xs text-muted">
            <span>共 {total} 条</span>
            {totalPages > 1 && (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="admin-toolbar-btn"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  上一页
                </button>
                <span>
                  {page} / {totalPages}
                </span>
                <button
                  type="button"
                  className="admin-toolbar-btn"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  下一页
                </button>
              </div>
            )}
          </div>
        }
      >
        {tableLoading && chunks.length === 0 ? (
          <div className="flex justify-center py-16">
            <Loader2 className="h-7 w-7 animate-spin text-brand" />
          </div>
        ) : chunks.length === 0 ? (
          <div className="py-16 text-center text-sm text-muted">暂无数据</div>
        ) : (
          <>
          <div className="space-y-3 p-3 md:hidden">
            {chunks.map((c) => (
              <article
                key={c.id}
                className="rounded-lg border border-surface-border/70 bg-surface px-3 py-3"
              >
                <div className="flex items-start gap-3">
                  {canWrite && (
                    <input
                      type="checkbox"
                      checked={selected.includes(c.id)}
                      onChange={() => toggleSelect(c.id)}
                      aria-label={`选择 chunk #${c.chunk_idx + 1}`}
                      className="mt-1 h-4 w-4 cursor-pointer accent-brand"
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium text-muted">
                        Chunk #{c.chunk_idx + 1}
                      </span>
                      <span
                        className={cn(
                          "status-tag",
                          c.enabled ? "status-tag-enabled" : "status-tag-disabled"
                        )}
                      >
                        {c.enabled ? "启用" : "禁用"}
                      </span>
                    </div>
                    <p className="mt-2 line-clamp-4 rounded-md border border-surface-border/55 bg-surface-2/35 px-3 py-2 text-sm leading-relaxed text-fg">
                      {c.text}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                      <span>{c.char_count.toLocaleString()} 字符</span>
                      <span>≈ {estimateTokens(c.char_count).toLocaleString()} tokens</span>
                      <span>{formatAdminDate(c.updated_at ?? c.created_at)}</span>
                    </div>
                  </div>
                </div>

                {canWrite && (
                  <div className="mt-3 flex items-center justify-end gap-1.5 border-t border-surface-border/60 pt-3">
                    <AdminRowAction
                      icon={Pencil}
                      label="编辑"
                      title="编辑内容"
                      variant="brand"
                      loading={isPending(`edit:${c.id}`)}
                      disabled={anyPending && !isPending(`edit:${c.id}`)}
                      onClick={() => {
                        setEditingChunk(c);
                        setEditText(c.text);
                      }}
                    />
                    <AdminRowAction
                      icon={c.enabled ? EyeOff : Eye}
                      label={c.enabled ? "禁用" : "启用"}
                      title={c.enabled ? "禁用此 chunk" : "启用此 chunk"}
                      loading={isPending(`toggle:${c.id}`)}
                      disabled={anyPending && !isPending(`toggle:${c.id}`)}
                      onClick={() => void onToggleChunk(c)}
                    />
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button
                          type="button"
                          className="admin-row-action"
                          title="更多操作"
                          aria-label={`chunk #${c.chunk_idx + 1} 更多操作`}
                          disabled={anyPending}
                        >
                          <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-36">
                        <DropdownMenuItem
                          className="cursor-pointer"
                          disabled={
                            anyPending ||
                            c.text.length < 2 ||
                            (pendingKey != null && !isPending(`split:${c.id}`))
                          }
                          onSelect={() => {
                            setSplittingChunk(c);
                            setSplitOffset(String(Math.floor(c.text.length / 2)));
                          }}
                        >
                          <Split className="h-4 w-4" />
                          切分
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          className="cursor-pointer"
                          disabled={anyPending && !isPending(`merge:${c.id}`)}
                          onSelect={() => void onMergeWithNext(c)}
                        >
                          <Merge className="h-4 w-4" />
                          合并
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          className="cursor-pointer"
                          variant="destructive"
                          disabled={anyPending && !isPending(`delete:${c.id}`)}
                          onSelect={() => setDeleteTarget(c)}
                        >
                          <Trash2 className="h-4 w-4" />
                          删除
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                )}
              </article>
            ))}
          </div>

          <div className="hidden md:block">
          <table className="admin-table admin-table-chunks">
            <thead>
              <tr>
                {canWrite && (
                  <th className="w-10">
                    <input
                      type="checkbox"
                      checked={allPageSelected}
                      onChange={toggleSelectAllPage}
                      aria-label="选择当前页全部 chunk"
                      className="h-4 w-4 cursor-pointer accent-brand"
                    />
                  </th>
                )}
                <th className="w-16">序号</th>
                <th>内容</th>
                <th className="w-20">状态</th>
                <th className="w-28">规模</th>
                <th className="w-36">更新时间</th>
                {canWrite && <th className="w-36">操作</th>}
              </tr>
            </thead>
            <tbody className={cn(tableLoading && "opacity-60")}>
              {chunks.map((c) => (
                <tr key={c.id}>
                  {canWrite && (
                    <td>
                      <input
                        type="checkbox"
                        checked={selected.includes(c.id)}
                        onChange={() => toggleSelect(c.id)}
                        aria-label={`选择 chunk #${c.chunk_idx + 1}`}
                        className="h-4 w-4 cursor-pointer accent-brand"
                      />
                    </td>
                  )}
                  <td className="tabular-nums text-muted">{c.chunk_idx}</td>
                  <td>
                      <p className="line-clamp-3 max-w-3xl text-sm leading-relaxed text-fg">
                        {c.text}
                      </p>
                  </td>
                  <td>
                    <span
                      className={cn(
                        "status-tag",
                        c.enabled ? "status-tag-enabled" : "status-tag-disabled"
                      )}
                    >
                      {c.enabled ? "启用" : "禁用"}
                    </span>
                  </td>
                  <td className="text-xs">
                    <div className="tabular-nums">{c.char_count.toLocaleString()} 字符</div>
                    <div className="tabular-nums text-muted">
                      ≈ {estimateTokens(c.char_count).toLocaleString()} tokens
                    </div>
                  </td>
                  <td className="text-xs text-muted">
                    {formatAdminDate(c.updated_at ?? c.created_at)}
                  </td>
                  {canWrite && (
                    <td>
                        <div className="flex items-center gap-1.5">
                        <AdminRowAction
                          icon={Pencil}
                          label="编辑"
                          title="编辑内容"
                          variant="brand"
                          loading={isPending(`edit:${c.id}`)}
                          disabled={anyPending && !isPending(`edit:${c.id}`)}
                          onClick={() => {
                            setEditingChunk(c);
                            setEditText(c.text);
                          }}
                        />
                        <AdminRowAction
                          icon={c.enabled ? EyeOff : Eye}
                          label={c.enabled ? "禁用" : "启用"}
                          title={c.enabled ? "禁用此 chunk" : "启用此 chunk"}
                          loading={isPending(`toggle:${c.id}`)}
                          disabled={anyPending && !isPending(`toggle:${c.id}`)}
                          onClick={() => void onToggleChunk(c)}
                        />
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              type="button"
                              className="admin-row-action"
                              title="更多操作"
                              aria-label={`chunk #${c.chunk_idx + 1} 更多操作`}
                              disabled={anyPending}
                            >
                              <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-36">
                            <DropdownMenuItem
                              className="cursor-pointer"
                              disabled={
                                anyPending ||
                                c.text.length < 2 ||
                                (pendingKey != null && !isPending(`split:${c.id}`))
                              }
                              onSelect={() => {
                                setSplittingChunk(c);
                                setSplitOffset(String(Math.floor(c.text.length / 2)));
                              }}
                            >
                              <Split className="h-4 w-4" />
                              切分
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              className="cursor-pointer"
                              disabled={anyPending && !isPending(`merge:${c.id}`)}
                              onSelect={() => void onMergeWithNext(c)}
                            >
                              <Merge className="h-4 w-4" />
                              合并
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              className="cursor-pointer"
                              variant="destructive"
                              disabled={anyPending && !isPending(`delete:${c.id}`)}
                              onSelect={() => setDeleteTarget(c)}
                            >
                              <Trash2 className="h-4 w-4" />
                              删除
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          </>
        )}
      </AdminPanel>

      <Dialog
        open={editingChunk != null}
        onOpenChange={(o) => !o && setEditingChunk(null)}
        title={`编辑 chunk #${(editingChunk?.chunk_idx ?? 0) + 1}`}
        description="修改后会自动重新 embedding 并更新向量库。"
        confirmLabel="保存"
        onConfirm={() => {}}
      >
        <form onSubmit={onSaveChunk} className="space-y-4">
          <div className="input-shell">
            <textarea
              value={editText}
              onChange={(e: ChangeEvent<HTMLTextAreaElement>) =>
                setEditText(e.target.value)
              }
              rows={12}
              className="w-full resize-y rounded-md bg-transparent px-3 py-2.5 text-sm leading-relaxed outline-none"
            />
          </div>
          <div className="flex flex-col justify-end gap-2 sm:flex-row">
            <button
              type="button"
              className="admin-btn-secondary"
              onClick={() => setEditingChunk(null)}
            >
              取消
            </button>
            <button type="submit" className="admin-btn-primary" disabled={anyPending}>
              {isPending(`edit:${editingChunk?.id ?? ""}`) ? "保存中…" : "保存"}
            </button>
          </div>
        </form>
      </Dialog>

      <Dialog
        open={splittingChunk != null}
        onOpenChange={(o) => {
          if (!o) {
            setSplittingChunk(null);
            setSplitOffset("");
          }
        }}
        title={`切分 chunk #${(splittingChunk?.chunk_idx ?? 0) + 1}`}
        description="在指定字符位置切分为两个 chunk（会重新 embedding）。"
        confirmLabel="切分"
        onConfirm={() => {}}
      >
        <form onSubmit={onSplitChunk} className="space-y-4">
          <p className="max-h-32 overflow-y-auto rounded-lg border border-surface-border/60 bg-surface-2 p-3 text-xs leading-relaxed text-muted">
            {splittingChunk?.text}
          </p>
          <label className="block space-y-1.5 text-xs font-medium text-muted">
            <span>
              切分位置（字符偏移，1 ~ {Math.max(0, (splittingChunk?.text.length ?? 1) - 1)}）
            </span>
            <input
              type="number"
              min={1}
              max={Math.max(1, (splittingChunk?.text.length ?? 2) - 1)}
              value={splitOffset}
              onChange={(e) => setSplitOffset(e.target.value)}
              className={docInputClass}
            />
          </label>
          <div className="flex flex-col justify-end gap-2 sm:flex-row">
            <button
              type="button"
              className="admin-btn-secondary"
              onClick={() => {
                setSplittingChunk(null);
                setSplitOffset("");
              }}
            >
              取消
            </button>
            <button type="submit" className="admin-btn-primary" disabled={anyPending}>
              {splittingChunk && isPending(`split:${splittingChunk.id}`)
                ? "切分中…"
                : "切分"}
            </button>
          </div>
        </form>
      </Dialog>

      <Dialog
        open={deleteTarget != null}
        onOpenChange={(open) => {
          if (!open && !isPending(`delete:${deleteTarget?.id ?? ""}`)) {
            setDeleteTarget(null);
          }
        }}
        title={`删除 chunk #${(deleteTarget?.chunk_idx ?? 0) + 1}？`}
        description="删除后会从该文档的分块列表和向量检索中移除。"
        confirmLabel="删除"
        variant="danger"
        busy={deleteTarget != null && isPending(`delete:${deleteTarget.id}`)}
        onConfirm={confirmDeleteChunk}
      />

      <Dialog
        open={mergeTarget != null}
        onOpenChange={(open) => {
          if (!open && !isPending(`merge:${mergeTarget?.chunk.id ?? ""}`)) {
            setMergeTarget(null);
          }
        }}
        title={`合并 chunk #${mergeTarget?.chunk.chunk_idx ?? ""} 与 #${mergeTarget?.next.chunk_idx ?? ""}？`}
        description="合并后会重新生成该段内容的向量，并移除被合并的相邻 chunk。"
        confirmLabel="合并"
        busy={mergeTarget != null && isPending(`merge:${mergeTarget.chunk.id}`)}
        onConfirm={confirmMergeChunks}
      />
    </AdminPageShell>
  );
}

const docInputClass =
  "admin-input";
