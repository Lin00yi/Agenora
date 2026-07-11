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
  ChevronRight,
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
  type KBDetail,
  type DocumentDetail,
  type Chunk,
  type KbRole,
} from "@/lib/kb-api";
import { cn } from "@/lib/cn";
import Dialog from "@/components/Dialog";
import Select from "@/components/Select";
import {
  AdminPageShell,
  AdminPanel,
} from "@/components/kb/AdminPageShell";
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
  const [tableLoading, setTableLoading] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [enabledFilter, setEnabledFilter] = useState<"all" | "enabled" | "disabled">(
    "all"
  );
  const [editingChunk, setEditingChunk] = useState<Chunk | null>(null);
  const [editText, setEditText] = useState("");
  const [busy, setBusy] = useState(false);
  const chunksLoadedOnce = useRef(false);

  const pageSize = 20;

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
      .catch((e) => toast.error((e as Error).message))
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
    setBusy(true);
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
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onToggleChunk = async (chunk: Chunk) => {
    setBusy(true);
    try {
      await patchChunk(kbId, docId, chunk.id, { enabled: !chunk.enabled });
      await refreshChunks();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onDeleteChunk = async (chunk: Chunk) => {
    if (!confirm(`删除 chunk #${chunk.chunk_idx + 1}？`)) return;
    setBusy(true);
    try {
      await deleteChunk(kbId, docId, chunk.id);
      toast.success("已删除");
      setSelected((s) => s.filter((id) => id !== chunk.id));
      await refresh();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onSaveChunk = async (e: FormEvent) => {
    e.preventDefault();
    if (!editingChunk) return;
    setBusy(true);
    try {
      await patchChunk(kbId, docId, editingChunk.id, { text: editText });
      toast.success("已保存");
      setEditingChunk(null);
      await refreshChunks();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onReingest = async () => {
    setBusy(true);
    try {
      await reingestDocument(kbId, docId);
      toast.success("已提交重建向量");
      await refresh();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (loading || !doc || !kb) {
    return (
      <div className="admin-page flex min-h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand" />
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
                disabled={busy}
                onClick={onReingest}
              >
                <RotateCcw className="h-4 w-4" />
                重建向量
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
              className="w-[120px]"
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
            <button
              type="button"
              className="admin-btn-secondary btn-sm !px-3 !py-1.5 text-xs"
              onClick={() =>
                refresh().catch((e) => toast.error((e as Error).message))
              }
            >
              <RefreshCw
                className={cn("h-3.5 w-3.5", tableLoading && "animate-spin")}
              />
              刷新
            </button>
            {canWrite && (
              <>
                <button
                  type="button"
                  className="admin-btn-secondary btn-sm !px-3 !py-1.5 text-xs"
                  disabled={busy || selected.length === 0}
                  onClick={() => onBatchEnable(true)}
                >
                  <Eye className="h-3.5 w-3.5" />
                  批量启用
                </button>
                <button
                  type="button"
                  className="admin-btn-secondary btn-sm !px-3 !py-1.5 text-xs"
                  disabled={busy || selected.length === 0}
                  onClick={() => onBatchEnable(false)}
                >
                  <EyeOff className="h-3.5 w-3.5" />
                  批量禁用
                </button>
                <button
                  type="button"
                  className="admin-btn-secondary btn-sm !px-3 !py-1.5 text-xs"
                  disabled={busy}
                  onClick={() => onBatchEnable(true, true)}
                >
                  全量启用
                </button>
                <button
                  type="button"
                  className="admin-btn-secondary btn-sm !px-3 !py-1.5 text-xs"
                  disabled={busy}
                  onClick={() => onBatchEnable(false, true)}
                >
                  全量禁用
                </button>
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
                <th className="w-40">更新时间</th>
                {canWrite && <th className="w-44">操作</th>}
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
                    {formatAdminDate(c.updated_at ?? c.created_at)}
                  </td>
                  {canWrite && (
                    <td>
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <button
                          type="button"
                          className="inline-flex items-center gap-0.5 text-brand hover:underline"
                          disabled={busy}
                          onClick={() => {
                            setEditingChunk(c);
                            setEditText(c.text);
                          }}
                        >
                          <Pencil className="h-3 w-3" />
                          编辑
                        </button>
                        <button
                          type="button"
                          className="inline-flex items-center gap-0.5 text-muted hover:text-fg"
                          disabled={busy}
                          onClick={() => onToggleChunk(c)}
                        >
                          {c.enabled ? (
                            <>
                              <EyeOff className="h-3 w-3" />
                              禁用
                            </>
                          ) : (
                            <>
                              <Eye className="h-3 w-3" />
                              启用
                            </>
                          )}
                        </button>
                        <button
                          type="button"
                          className="inline-flex items-center gap-0.5 text-danger hover:underline"
                          disabled={busy}
                          onClick={() => onDeleteChunk(c)}
                        >
                          <Trash2 className="h-3 w-3" />
                          删除
                        </button>
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
            <button type="submit" className="admin-btn-primary btn-sm" disabled={busy}>
              保存
            </button>
          </div>
        </form>
      </Dialog>
    </AdminPageShell>
  );
}
