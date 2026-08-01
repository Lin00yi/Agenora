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
  Plus,
  ChevronLeft,
  Split,
  Merge,
} from "lucide-react";
import { toast } from "sonner";

import { getToken } from "@/lib/auth";
import {
  getKb,
  getDocument,
  listDocumentChunks,
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
} from "@/lib/kb-api";
import { toastApiError } from "@/lib/byok-toast";
import { cn } from "@/lib/cn";
import Dialog from "@/components/Dialog";
import Select from "@/components/Select";
import { StateView } from "@/components/ui/state-view";
import {
  AdminPageShell,
  AdminPanel,
} from "@/components/kb/AdminPageShell";
import {
  AdminRowAction,
  AdminToolbarButton,
} from "@/components/kb/AdminTableActions";
import {
  estimateTokens,
  formatAdminDate,
} from "@/components/kb/admin-utils";

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
              <Link href={`/kbs/${kbId}`} className="btn btn-primary btn-sm">
                返回文档列表
              </Link>
              <Link href="/kbs" className="btn btn-ghost btn-sm">
                返回知识库列表
              </Link>
            </div>
          }
        />
      </div>
    );
  }

  return (
    <AdminPageShell
      breadcrumbs={[
        { label: "首页", href: "/" },
        { label: "知识库管理", href: "/kbs" },
        { label: "文档管理", href: `/kbs/${kbId}` },
        { label: "切片管理" },
      ]}
      title="分块管理"
      subtitle={
        <>
          {doc.filename}
          <span className="mx-1.5 text-muted/50">·</span>
          <span className="text-muted">知识库: {kb.name}</span>
        </>
      }
      actions={
        <>
          <Link href={`/kbs/${kbId}`} className="admin-btn-secondary">
            返回文档
          </Link>
          {canWrite && (
            <>
              <button
                type="button"
                className="admin-btn-secondary"
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
              <button
                type="button"
                className="admin-btn-primary"
                disabled
                title="即将支持"
              >
                <Plus className="h-4 w-4" />
                新建分块
              </button>
            </>
          )}
        </>
      }
    >
      <AdminPanel
        title="Chunk 列表"
        subtitle="支持编辑、启用、批量操作"
        toolbar={
          <>
            <Select
              size="sm"
              className="w-[120px] admin-select-trigger"
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
                  icon={Eye}
                  loading={isPending("batch")}
                  disabled={
                    anyPending ||
                    selected.length === 0 ||
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
                    selected.length === 0 ||
                    (pendingKey != null && pendingKey !== "batch")
                  }
                  onClick={() => void onBatchEnable(false)}
                >
                  批量禁用
                </AdminToolbarButton>
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
        footer={
          <div className="flex items-center justify-between text-xs text-muted">
            <span>共 {total} 条</span>
            {totalPages > 1 && (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="admin-btn-secondary !px-2 !py-1 text-xs"
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
                  className="admin-btn-secondary !px-2 !py-1 text-xs"
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
        <div className="border-b border-surface-border/50 px-5 py-3">
          <div className="input-shell flex max-w-md items-center gap-2 px-3 py-2">
            <Search className="h-4 w-4 shrink-0 text-muted" />
            <input
              type="search"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="搜索 chunk 内容…"
              className="min-w-0 flex-1 bg-transparent text-sm outline-none"
            />
          </div>
        </div>

        {tableLoading && chunks.length === 0 ? (
          <div className="flex justify-center py-16">
            <Loader2 className="h-7 w-7 animate-spin text-brand" />
          </div>
        ) : chunks.length === 0 ? (
          <div className="py-16 text-center text-sm text-muted">暂无数据</div>
        ) : (
          <table className="admin-table">
            <thead>
              <tr>
                {canWrite && (
                  <th className="w-10">
                    <input
                      type="checkbox"
                      checked={allPageSelected}
                      onChange={toggleSelectAllPage}
                      className="h-4 w-4 accent-brand"
                    />
                  </th>
                )}
                <th className="w-16">序号</th>
                <th>内容</th>
                <th className="w-20">状态</th>
                <th className="w-24">字符数</th>
                <th className="w-24">Token数</th>
                <th className="w-36">创建时间</th>
                <th className="w-36">更新时间</th>
                {canWrite && <th className="w-56">操作</th>}
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
                        className="h-4 w-4 accent-brand"
                      />
                    </td>
                  )}
                  <td className="tabular-nums text-muted">{c.chunk_idx}</td>
                  <td>
                    <p className="line-clamp-2 max-w-xl text-sm leading-relaxed text-fg/90">
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
                  <td className="tabular-nums">{c.char_count.toLocaleString()}</td>
                  <td className="tabular-nums text-muted">
                    {estimateTokens(c.char_count).toLocaleString()}
                  </td>
                  <td className="text-xs text-muted">
                    {formatAdminDate(c.created_at)}
                  </td>
                  <td className="text-xs text-muted">
                    {formatAdminDate(c.updated_at ?? c.created_at)}
                  </td>
                  {canWrite && (
                    <td>
                      <div className="flex flex-wrap items-center gap-0.5">
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
                        <AdminRowAction
                          icon={Split}
                          label="切分"
                          title="按字符位置切分"
                          loading={isPending(`split:${c.id}`)}
                          disabled={
                            anyPending ||
                            c.text.length < 2 ||
                            (pendingKey != null && !isPending(`split:${c.id}`))
                          }
                          onClick={() => {
                            setSplittingChunk(c);
                            setSplitOffset(String(Math.floor(c.text.length / 2)));
                          }}
                        />
                        <AdminRowAction
                          icon={Merge}
                          label="合并"
                          title="与下一个相邻 chunk 合并"
                          loading={isPending(`merge:${c.id}`)}
                          disabled={anyPending && !isPending(`merge:${c.id}`)}
                          onClick={() => void onMergeWithNext(c)}
                        />
                        <AdminRowAction
                          icon={Trash2}
                          label="删除"
                          title="删除此 chunk"
                          variant="danger"
                          loading={isPending(`delete:${c.id}`)}
                          disabled={anyPending && !isPending(`delete:${c.id}`)}
                          onClick={() => setDeleteTarget(c)}
                        />
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
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
              className="w-full resize-y rounded-xl bg-transparent px-3 py-2.5 text-sm leading-relaxed outline-none"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="admin-btn-secondary btn-sm"
              onClick={() => setEditingChunk(null)}
            >
              取消
            </button>
            <button type="submit" className="admin-btn-primary btn-sm" disabled={anyPending}>
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
          <label className="block text-xs text-muted">
            切分位置（字符偏移，1 ~ {Math.max(0, (splittingChunk?.text.length ?? 1) - 1)}）
            <input
              type="number"
              min={1}
              max={Math.max(1, (splittingChunk?.text.length ?? 2) - 1)}
              value={splitOffset}
              onChange={(e) => setSplitOffset(e.target.value)}
              className="mt-1 block w-full rounded-md border bg-bg px-3 py-2 text-sm"
            />
          </label>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="admin-btn-secondary btn-sm"
              onClick={() => {
                setSplittingChunk(null);
                setSplitOffset("");
              }}
            >
              取消
            </button>
            <button type="submit" className="admin-btn-primary btn-sm" disabled={anyPending}>
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
