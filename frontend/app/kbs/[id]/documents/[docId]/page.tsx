"use client";

import {
  useCallback,
  useEffect,
  useState,
  FormEvent,
  ChangeEvent,
} from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ChevronLeft,
  RefreshCw,
  Download,
  RotateCcw,
  Trash2,
  Scissors,
  Merge,
  Eye,
  EyeOff,
  Save,
  AlertCircle,
  FileText,
} from "lucide-react";
import { toast } from "sonner";

import { getToken } from "@/lib/auth";
import {
  getKb,
  getDocument,
  listDocumentChunks,
  patchChunk,
  deleteChunk,
  splitChunk,
  mergeChunks,
  reingestDocument,
  downloadDocumentFile,
  type KBDetail,
  type DocumentDetail,
  type Chunk,
  type KbRole,
} from "@/lib/kb-api";
import { cn } from "@/lib/cn";
import Dialog from "@/components/Dialog";
import ThemeToggle from "@/components/ThemeToggle";

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
  const [showParsed, setShowParsed] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [editingChunk, setEditingChunk] = useState<Chunk | null>(null);
  const [editText, setEditText] = useState("");
  const [splitTarget, setSplitTarget] = useState<Chunk | null>(null);
  const [splitOffset, setSplitOffset] = useState("");
  const [busy, setBusy] = useState(false);

  const pageSize = 10;

  const refresh = useCallback(async () => {
    const [kbData, docData, chunkData] = await Promise.all([
      getKb(kbId),
      getDocument(kbId, docId, { includeParsedText: showParsed }),
      listDocumentChunks(kbId, docId, page, pageSize),
    ]);
    setKb(kbData);
    setDoc(docData);
    setChunks(chunkData.items);
    setTotal(chunkData.total);
  }, [kbId, docId, page, showParsed]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    refresh()
      .catch((e) => toast.error((e as Error).message))
      .finally(() => setLoading(false));
  }, [refresh, router]);

  useEffect(() => {
    if (!doc) return;
    const inflight = doc.status === "pending" || doc.status === "ingesting";
    if (!inflight) return;
    const t = setInterval(() => {
      refresh().catch(() => {});
    }, 2000);
    return () => clearInterval(t);
  }, [doc, refresh]);

  const myRole: KbRole = kb?.my_role ?? (kb?.is_system ? "viewer" : "owner");
  const canWrite = (myRole === "owner" || myRole === "editor") && !kb?.is_system;

  const onReingest = async () => {
    setBusy(true);
    try {
      await reingestDocument(kbId, docId);
      toast.success("已提交重新 ingest");
      await refresh();
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
      toast.success("chunk 已更新");
      setEditingChunk(null);
      await refresh();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onDeleteChunk = async (chunk: Chunk) => {
    if (!confirm(`删除 chunk #${chunk.chunk_idx + 1}？`)) return;
    setBusy(true);
    try {
      await deleteChunk(kbId, docId, chunk.id);
      toast.success("已删除 chunk");
      setSelected((s) => s.filter((id) => id !== chunk.id));
      await refresh();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onSplit = async (e: FormEvent) => {
    e.preventDefault();
    if (!splitTarget) return;
    const offset = parseInt(splitOffset, 10);
    if (!offset || offset <= 0) {
      toast.error("请输入有效的切分位置");
      return;
    }
    setBusy(true);
    try {
      await splitChunk(kbId, docId, splitTarget.id, offset);
      toast.success("切分成功");
      setSplitTarget(null);
      setSplitOffset("");
      await refresh();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onMerge = async () => {
    if (selected.length !== 2) {
      toast.error("请选择相邻的两个 chunk 进行合并");
      return;
    }
    const a = chunks.find((c) => c.id === selected[0]);
    const b = chunks.find((c) => c.id === selected[1]);
    if (!a || !b || Math.abs(a.chunk_idx - b.chunk_idx) !== 1) {
      toast.error("只能合并相邻的两个 chunk");
      return;
    }
    setBusy(true);
    try {
      await mergeChunks(kbId, docId, [selected[0], selected[1]]);
      toast.success("合并成功");
      setSelected([]);
      await refresh();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const toggleSelect = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id].slice(-2)
    );
  };

  if (loading || !doc || !kb) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted">
        加载中...
      </div>
    );
  }

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="min-h-screen bg-bg text-fg">
      <header className="border-b bg-bg/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-5xl items-center gap-3 px-4 sm:px-6">
          <Link
            href={`/kbs/${kbId}`}
            className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg"
          >
            <ChevronLeft className="h-4 w-4" />
            {kb.name}
          </Link>
          <div className="min-w-0 flex-1 truncate text-sm font-medium">
            {doc.filename}
          </div>
          <button
            type="button"
            onClick={() => refresh().catch(() => {})}
            className="rounded-md p-2 hover:bg-surface-2"
            aria-label="refresh"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
          <ThemeToggle />
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-6 px-4 py-6 sm:px-6">
        <div className="card p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 text-base font-medium">
                <FileText className="h-4 w-4" />
                {doc.filename}
              </div>
              <div className="mt-2 flex flex-wrap gap-3 text-xs text-muted">
                <span>状态: {doc.status}</span>
                <span>{doc.chunks_count} chunks</span>
                {doc.parsed_text_length > 0 && (
                  <span>解析文本 {doc.parsed_text_length} 字符</span>
                )}
              </div>
              {doc.status === "failed" && doc.error && (
                <div className="mt-2 flex items-start gap-1 text-xs text-danger">
                  <AlertCircle className="mt-0.5 h-3 w-3" />
                  {doc.error}
                </div>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              {doc.source_type === "file" && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await downloadDocumentFile(kbId, docId, doc.filename);
                    } catch (e) {
                      toast.error((e as Error).message);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  <Download className="h-3.5 w-3.5" />
                  下载原文件
                </button>
              )}
              {canWrite && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={busy}
                  onClick={onReingest}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  重新 ingest
                </button>
              )}
            </div>
          </div>

          {doc.parsed_text_length > 0 && (
            <div className="mt-4 border-t pt-3">
              <button
                type="button"
                className="text-sm text-brand hover:underline"
                onClick={async () => {
                  const next = !showParsed;
                  setShowParsed(next);
                  if (next && !doc.parsed_text) {
                    const d = await getDocument(kbId, docId, {
                      includeParsedText: true,
                    });
                    setDoc(d);
                  } else {
                    setShowParsed(next);
                  }
                }}
              >
                {showParsed ? "隐藏" : "查看"}解析后全文
              </button>
              {showParsed && doc.parsed_text && (
                <pre className="mt-2 max-h-64 overflow-auto rounded-md bg-surface-2 p-3 text-xs whitespace-pre-wrap">
                  {doc.parsed_text}
                </pre>
              )}
            </div>
          )}
        </div>

        <div className="card overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
            <div className="text-sm font-medium">
              分块管理（{total}）
            </div>
            {canWrite && selected.length === 2 && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={busy}
                onClick={onMerge}
              >
                <Merge className="h-3.5 w-3.5" />
                合并选中
              </button>
            )}
          </div>

          {chunks.length === 0 ? (
            <div className="px-4 py-10 text-center text-sm text-muted">
              {doc.status === "done" ? "暂无 chunks" : "ingest 完成后显示 chunks"}
            </div>
          ) : (
            <ul className="divide-y">
              {chunks.map((c) => (
                <li
                  key={c.id}
                  className={cn(
                    "px-4 py-3",
                    !c.enabled && "opacity-60 bg-surface/50"
                  )}
                >
                  <div className="flex items-start gap-3">
                    {canWrite && (
                      <input
                        type="checkbox"
                        checked={selected.includes(c.id)}
                        onChange={() => toggleSelect(c.id)}
                        className="mt-1"
                      />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                        <span className="font-medium text-fg">
                          #{c.chunk_idx + 1}
                        </span>
                        <span>{c.char_count} 字符</span>
                        {!c.enabled && (
                          <span className="chip border-warning/30 bg-warning/10 text-warning">
                            已禁用
                          </span>
                        )}
                      </div>
                      <p className="mt-1 line-clamp-3 text-sm whitespace-pre-wrap">
                        {c.text}
                      </p>
                    </div>
                    {canWrite && (
                      <div className="flex shrink-0 gap-1">
                        <button
                          type="button"
                          title={c.enabled ? "禁用" : "启用"}
                          className="rounded p-1.5 hover:bg-surface-2"
                          disabled={busy}
                          onClick={() => onToggleChunk(c)}
                        >
                          {c.enabled ? (
                            <EyeOff className="h-3.5 w-3.5" />
                          ) : (
                            <Eye className="h-3.5 w-3.5" />
                          )}
                        </button>
                        <button
                          type="button"
                          title="编辑"
                          className="rounded p-1.5 hover:bg-surface-2"
                          disabled={busy}
                          onClick={() => {
                            setEditingChunk(c);
                            setEditText(c.text);
                          }}
                        >
                          <Save className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          title="切分"
                          className="rounded p-1.5 hover:bg-surface-2"
                          disabled={busy}
                          onClick={() => {
                            setSplitTarget(c);
                            setSplitOffset(String(Math.floor(c.char_count / 2)));
                          }}
                        >
                          <Scissors className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          title="删除"
                          className="rounded p-1.5 hover:bg-danger/15 hover:text-danger"
                          disabled={busy}
                          onClick={() => onDeleteChunk(c)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 border-t px-4 py-3">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                上一页
              </button>
              <span className="text-xs text-muted">
                {page} / {totalPages}
              </span>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                下一页
              </button>
            </div>
          )}
        </div>
      </main>

      <Dialog
        open={editingChunk != null}
        onOpenChange={(o) => !o && setEditingChunk(null)}
        title={`编辑 chunk #${(editingChunk?.chunk_idx ?? 0) + 1}`}
        description="修改后会自动重新 embedding 并更新向量库。"
        confirmLabel="保存"
        onConfirm={() => {}}
      >
        <form onSubmit={onSaveChunk} className="space-y-3">
          <textarea
            value={editText}
            onChange={(e: ChangeEvent<HTMLTextAreaElement>) =>
              setEditText(e.target.value)
            }
            rows={8}
            className="w-full rounded-md border bg-bg px-3 py-2 text-sm"
          />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => setEditingChunk(null)}
            >
              取消
            </button>
            <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>
              保存
            </button>
          </div>
        </form>
      </Dialog>

      <Dialog
        open={splitTarget != null}
        onOpenChange={(o) => !o && setSplitTarget(null)}
        title={`切分 chunk #${(splitTarget?.chunk_idx ?? 0) + 1}`}
        description="输入字符偏移量（从 0 开始），在该位置将 chunk 一分为二。"
        confirmLabel="切分"
        onConfirm={() => {}}
      >
        <form onSubmit={onSplit} className="space-y-3">
          <input
            type="number"
            min={1}
            max={(splitTarget?.char_count ?? 1) - 1}
            value={splitOffset}
            onChange={(e) => setSplitOffset(e.target.value)}
            className="w-full rounded-md border bg-bg px-3 py-2 text-sm"
            placeholder="offset"
          />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => setSplitTarget(null)}
            >
              取消
            </button>
            <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>
              切分
            </button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
