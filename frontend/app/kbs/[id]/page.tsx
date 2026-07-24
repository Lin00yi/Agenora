"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  ChangeEvent,
  FormEvent,
} from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Trash2,
  FileText,
  Link2,
  RefreshCw,
  AlertCircle,
  Lock,
  Hash,
  Layers,
  BookOpen,
  Sparkles,
  Users,
  Eye,
  UserPlus,
  Copy,
  X,
  Search,
  Plus,
  Play,
} from "lucide-react";
import { toast } from "sonner";

import { getToken } from "@/lib/auth";
import {
  getKb,
  uploadFile,
  uploadUrl,
  deleteDocument,
  deleteKb,
  patchKb,
  patchDocument,
  rebuildKb,
  reingestDocument,
  listMembers,
  inviteMember,
  patchMember,
  removeMember,
  listInvitations,
  createInvitation,
  deleteInvitation,
  type KBDetail,
  type Document,
  type DocStatus,
  type KbMemberListResponse,
  type KbInvitation,
  type MemberRole,
  type KbRole,
} from "@/lib/kb-api";
import { toastApiError } from "@/lib/byok-toast";
import { cn } from "@/lib/cn";
import Dialog from "@/components/Dialog";
import Select from "@/components/Select";
import { LoadingState, StateView } from "@/components/ui/state-view";
import { Switch } from "@/components/ui/switch";
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
  fileExtension,
  formatAdminDate,
  formatFileSize,
} from "@/components/kb/admin-utils";

export default function KbDetailPage({ params }: { params: { id: string } }) {
  const { id } = params;
  const router = useRouter();

  const [kb, setKb] = useState<KBDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  const [uploadingFiles, setUploadingFiles] = useState<string[]>([]);
  const [url, setUrl] = useState("");
  const [submittingUrl, setSubmittingUrl] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const [pendingDelete, setPendingDelete] = useState<Document | null>(null);
  const [deleting, setDeleting] = useState(false);

  // v3-M1: owner-only KB-level deletion (danger zone at page bottom)
  const [pendingDeleteKb, setPendingDeleteKb] = useState(false);
  const [deletingKb, setDeletingKb] = useState(false);
  // v3-M3: advanced settings + index rebuild
  const [groupingBusy, setGroupingBusy] = useState(false);
  const [chunkBusy, setChunkBusy] = useState(false);
  const [chunkTarget, setChunkTarget] = useState("1500");
  const [chunkMaxSize, setChunkMaxSize] = useState("1800");
  const [chunkOverlap, setChunkOverlap] = useState("150");
  const [pendingRebuild, setPendingRebuild] = useState(false);
  const [rebuildingKb, setRebuildingKb] = useState(false);
  const [docSearch, setDocSearch] = useState("");
  const [docStatusFilter, setDocStatusFilter] = useState<
    "all" | DocStatus
  >("all");
  const [docPage, setDocPage] = useState(1);
  const [docToggleBusy, setDocToggleBusy] = useState<string | null>(null);
  const [listRefreshing, setListRefreshing] = useState(false);
  const [reingestingDocId, setReingestingDocId] = useState<string | null>(null);
  const docPageSize = 10;

  const refresh = useCallback(async () => {
    try {
      const data = await getKb(id);
      setKb(data);
    } catch (e) {
      toast.error((e as Error).message);
      setNotFound(true);
    }
  }, [id]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    refresh().finally(() => setLoading(false));
  }, [refresh, router]);

  useEffect(() => {
    if (!kb) return;
    setChunkTarget(String(kb.chunk_target ?? 1500));
    setChunkMaxSize(String(kb.chunk_max_size ?? 1800));
    setChunkOverlap(String(kb.chunk_overlap ?? 150));
  }, [kb?.chunk_target, kb?.chunk_max_size, kb?.chunk_overlap, kb?.id]);

  const onSaveChunkSettings = async (e: FormEvent) => {
    e.preventDefault();
    setChunkBusy(true);
    try {
      const updated = await patchKb(id, {
        chunk_target: parseInt(chunkTarget, 10),
        chunk_max_size: parseInt(chunkMaxSize, 10),
        chunk_overlap: parseInt(chunkOverlap, 10),
      });
      setKb((cur) =>
        cur
          ? {
              ...cur,
              chunk_target: updated.chunk_target,
              chunk_max_size: updated.chunk_max_size,
              chunk_overlap: updated.chunk_overlap,
            }
          : cur
      );
      toast.success("分块参数已保存（对新 ingest / 重新 ingest 生效）");
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setChunkBusy(false);
    }
  };

  // Poll while any doc is pending/ingesting
  useEffect(() => {
    if (!kb) return;
    const inflight = kb.documents.some(
      (d) => d.status === "pending" || d.status === "ingesting"
    );
    if (!inflight) return;
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [kb, refresh]);

  const onFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (!files.length) return;
    setUploadingFiles(files.map((f) => f.name));
    try {
      for (const f of files) {
        await uploadFile(id, f);
      }
      toast.success(`已上传 ${files.length} 个文件，正在后台 ingest`);
      await refresh();
    } catch (err) {
      toastApiError(err, (p) => router.push(p));
    } finally {
      setUploadingFiles([]);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const onSubmitUrl = async (e: FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;
    setSubmittingUrl(true);
    try {
      await uploadUrl(id, url.trim());
      toast.success("已提交 URL，正在抓取并 ingest");
      setUrl("");
      await refresh();
    } catch (err) {
      toastApiError(err, (p) => router.push(p));
    } finally {
      setSubmittingUrl(false);
    }
  };

  const confirmDeleteDoc = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteDocument(id, pendingDelete.id);
      toast.success("已删除文档");
      setPendingDelete(null);
      await refresh();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setDeleting(false);
    }
  };

  // v3-M1: KB-level deletion (owner only). Backend cascades members + invitations.
  const confirmDeleteKb = async () => {
    setDeletingKb(true);
    try {
      await deleteKb(id);
      toast.success(`已删除知识库：${kb?.name ?? ""}`);
      router.replace("/kbs");
    } catch (err) {
      toast.error((err as Error).message);
      setDeletingKb(false);
    }
  };

  // v3-M3: toggle grouping_enabled. Optimistic: update UI immediately, revert on error.
  const onToggleGrouping = async (e: ChangeEvent<HTMLInputElement>) => {
    if (!kb) return;
    const next = e.target.checked;
    setGroupingBusy(true);
    // Optimistic local update so the checkbox doesn't lag while PATCH runs.
    setKb({ ...kb, grouping_enabled: next });
    try {
      const updated = await patchKb(id, { grouping_enabled: next });
      // Server is source of truth — splice in only the toggleable field to
      // avoid clobbering documents[] (PATCH response is bare KB without docs).
      setKb((cur) =>
        cur ? { ...cur, grouping_enabled: updated.grouping_enabled } : cur
      );
      toast.success(next ? "已开启 grouping" : "已关闭 grouping");
    } catch (err) {
      setKb((cur) => (cur ? { ...cur, grouping_enabled: !next } : cur));
      toast.error((err as Error).message);
    } finally {
      setGroupingBusy(false);
    }
  };

  // v3-M3: rebuild collection (owner only). Drops + re-ingests every document.
  // After confirm, polling loop in refresh() will surface ingest status.
  const confirmRebuildKb = async () => {
    setRebuildingKb(true);
    try {
      const res = await rebuildKb(id);
      toast.success(`已开始重建：${res.doc_count} 篇文档正在重新 ingest`);
      setPendingRebuild(false);
      // Trigger an immediate refresh so the doc-list polling picks up
      // the pending → ingesting transition without waiting for the timer.
      await refresh();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setRebuildingKb(false);
    }
  };

  const onRefreshList = async () => {
    setListRefreshing(true);
    try {
      await refresh();
    } finally {
      setListRefreshing(false);
    }
  };

  const onToggleDocEnabled = async (doc: Document, enabled: boolean) => {
    const prevEnabled = doc.enabled !== false;
    setDocToggleBusy(doc.id);
    setKb((cur) =>
      cur
        ? {
            ...cur,
            documents: cur.documents.map((d) =>
              d.id === doc.id ? { ...d, enabled } : d
            ),
          }
        : cur
    );
    try {
      const updated = await patchDocument(id, doc.id, { enabled });
      setKb((cur) =>
        cur
          ? {
              ...cur,
              documents: cur.documents.map((d) =>
                d.id === doc.id ? { ...d, enabled: updated.enabled } : d
              ),
            }
          : cur
      );
      toast.success(enabled ? "文档已启用，参与检索" : "文档已禁用，不再参与检索");
    } catch (err) {
      setKb((cur) =>
        cur
          ? {
              ...cur,
              documents: cur.documents.map((d) =>
                d.id === doc.id ? { ...d, enabled: prevEnabled } : d
              ),
            }
          : cur
      );
      toastApiError(err, (p) => router.push(p));
    } finally {
      setDocToggleBusy(null);
    }
  };

  const filteredDocuments = useMemo(() => {
    if (!kb) return [];
    const q = docSearch.trim().toLowerCase();
    return kb.documents.filter((d) => {
      if (docStatusFilter !== "all" && d.status !== docStatusFilter) return false;
      if (!q) return true;
      return (
        d.filename.toLowerCase().includes(q) ||
        (d.source_url?.toLowerCase().includes(q) ?? false)
      );
    });
  }, [kb, docSearch, docStatusFilter]);

  useEffect(() => {
    setDocPage(1);
  }, [docSearch, docStatusFilter]);

  if (loading) {
    return (
      <div className="flex min-h-dvh items-center justify-center px-4">
        <LoadingState label="正在打开知识库" description="正在读取文档、处理状态和成员权限。" className="w-full max-w-md" />
      </div>
    );
  }

  if (notFound || !kb) {
    return (
      <div className="flex min-h-dvh items-center justify-center px-4">
        <StateView
          variant="error"
          title="找不到这个知识库"
          description="它可能已被删除、你没有访问权限，或链接已失效。"
          action={<Link href="/kbs" className="btn btn-ghost btn-sm">返回知识库列表</Link>}
          className="w-full max-w-md"
        />
      </div>
    );
  }

  // v2-M9: per-KB effective role drives every write button.
  const myRole: KbRole = kb.my_role ?? (kb.is_system ? "viewer" : "owner");
  const isOwner = myRole === "owner";
  const canWrite = (isOwner || myRole === "editor") && !kb.is_system;

  const docTotalPages = Math.max(
    1,
    Math.ceil(filteredDocuments.length / docPageSize)
  );
  const pagedDocuments = filteredDocuments.slice(
    (docPage - 1) * docPageSize,
    docPage * docPageSize
  );

  return (
    <AdminPageShell
      breadcrumbs={[
        { label: "首页", href: "/" },
        { label: "知识库管理", href: "/kbs" },
        { label: "文档管理" },
      ]}
      title="文档管理"
      subtitle={`${kb.name}（${kb.id.slice(0, 8)}…）`}
      actions={
        <>
          <Link href="/kbs" className="admin-btn-secondary">
            返回知识库
          </Link>
          {canWrite && !kb.is_system && (
            <>
              <input
                ref={fileInput}
                type="file"
                multiple
                accept=".md,.markdown,.txt,.pdf,.docx"
                onChange={onFileChange}
                className="hidden"
              />
              <button
                type="button"
                className="admin-btn-primary"
                disabled={uploadingFiles.length > 0}
                onClick={() => fileInput.current?.click()}
              >
                <Plus className="h-4 w-4" />
                上传文档
              </button>
            </>
          )}
        </>
      }
    >
        {/* v2-M9: role banner for non-owner / non-system access */}
        {!kb.is_system && myRole === "editor" && (
          <div className="card mb-4 border-info/30 bg-info/10 p-3 text-sm">
            <div className="flex items-center gap-2 text-info">
              <Users className="h-4 w-4" />
              <span className="font-medium">你是协作者（editor）</span>
            </div>
            <p className="mt-1 text-xs text-info/90">
              可以上传 / 删除文档；不能删除 KB 或管理成员。
            </p>
          </div>
        )}
        {!kb.is_system && myRole === "viewer" && (
          <div className="card mb-4 border-border bg-surface p-3 text-sm">
            <div className="flex items-center gap-2 text-muted">
              <Eye className="h-4 w-4" />
              <span className="font-medium">你是只读访问者（viewer）</span>
            </div>
            <p className="mt-1 text-xs text-muted">
              可以在对话中选用这个 KB，但不能上传 / 删除内容。
            </p>
          </div>
        )}

        {/* Meta + stats */}
        <div className="card mb-6 p-4">
          <div className="flex items-center gap-2">
            {kb.is_system && <Lock className="h-4 w-4 text-warning" />}
            <span className="text-base font-medium">{kb.name}</span>
            {kb.is_system && (
              <span className="chip border-warning/30 bg-warning/10 text-warning">
                示例 · 只读
              </span>
            )}
          </div>
          {kb.description && (
            <div className="mt-1 text-sm text-muted">{kb.description}</div>
          )}
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat icon={FileText} label="文档" value={kb.documents.length} />
            <Stat icon={Hash} label="chunks" value={kb.chunks_count} />
            <Stat icon={Layers} label="embedding" value={kb.embedding_model || "—"} />
            <Stat icon={BookOpen} label="维度" value={kb.vector_size} />
          </div>
        </div>

        {kb.is_system ? (
          <div className="card mb-6 border-warning/40 bg-warning/10 p-4 text-sm">
            <div className="flex items-center gap-2 font-medium text-warning">
              <Lock className="h-4 w-4" />
              系统内置示例库
            </div>
            <p className="mt-1 text-xs text-warning/90">
              这是 AnyKB 内置的旅行演示知识库（4 城本地餐厅策展数据）。所有用户都能在对话中选中它，体验完整的旅行 Agent 工具链（天气 + POI + 报告生成）。
              本演示库 <strong>只读</strong>：不能上传 / 删除内容。要管理你自己的内容，请回到列表新建一个属于你的 KB。
            </p>
          </div>
        ) : canWrite ? (
          <form
            onSubmit={onSubmitUrl}
            className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-surface-border/60 bg-surface px-4 py-3"
          >
            <Link2 className="h-4 w-4 text-muted" />
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="从 URL 抓取并 ingest…"
              className="min-w-[200px] flex-1 bg-transparent text-sm outline-none"
            />
            <button
              type="submit"
              disabled={!url.trim() || submittingUrl}
              className="admin-btn-secondary btn-sm !py-1.5 text-xs"
            >
              {submittingUrl ? "提交中…" : "抓取"}
            </button>
          </form>
        ) : null}

        <AdminPanel
          title="文档列表"
          subtitle="支持筛选与分块管理"
          toolbar={
            <>
              <div className="input-shell flex items-center gap-2 px-3 py-1.5">
                <Search className="h-3.5 w-3.5 text-muted" />
                <input
                  type="search"
                  value={docSearch}
                  onChange={(e) => setDocSearch(e.target.value)}
                  placeholder="搜索文档名称"
                  className="w-36 bg-transparent text-xs outline-none sm:w-44"
                />
              </div>
              <Select
                size="sm"
                className="w-[110px] admin-select-trigger"
                value={docStatusFilter}
                onChange={(e) =>
                  setDocStatusFilter(e.target.value as typeof docStatusFilter)
                }
                options={[
                  { value: "all", label: "全部状态" },
                  { value: "done", label: "完成" },
                  { value: "ingesting", label: "处理中" },
                  { value: "pending", label: "排队" },
                  { value: "failed", label: "失败" },
                ]}
              />
              <AdminToolbarButton
                icon={RefreshCw}
                loading={listRefreshing}
                onClick={() => void onRefreshList()}
              >
                刷新
              </AdminToolbarButton>
            </>
          }
          footer={
            <div className="flex items-center justify-between text-xs text-muted">
              <span>共 {filteredDocuments.length} 条</span>
              {docTotalPages > 1 && (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    className="admin-btn-secondary !px-2 !py-1 text-xs"
                    disabled={docPage <= 1}
                    onClick={() => setDocPage((p) => Math.max(1, p - 1))}
                  >
                    上一页
                  </button>
                  <span>
                    {docPage} / {docTotalPages}
                  </span>
                  <button
                    type="button"
                    className="admin-btn-secondary !px-2 !py-1 text-xs"
                    disabled={docPage >= docTotalPages}
                    onClick={() => setDocPage((p) => p + 1)}
                  >
                    下一页
                  </button>
                </div>
              )}
            </div>
          }
        >
          {kb.documents.length === 0 ? (
            <div className="px-4 py-16 text-center text-sm text-muted">
              {kb.is_system ? (
                <>示例库文档不在此列表展示</>
              ) : (
                <div className="inline-flex flex-col items-center gap-2">
                  <FileText className="h-8 w-8 text-muted/40" />
                  <div>还没有文档，点击右上角上传</div>
                </div>
              )}
            </div>
          ) : filteredDocuments.length === 0 ? (
            <div className="py-16 text-center text-sm text-muted">没有匹配的文档</div>
          ) : (
            <table className="admin-table">
              <thead>
                <tr>
                  <th>文档</th>
                  <th className="w-24">来源</th>
                  <th className="w-20">处理模式</th>
                  <th className="w-28">状态</th>
                  <th className="w-16">启用</th>
                  <th className="w-16">分块数</th>
                  <th className="w-20">类型</th>
                  <th className="w-24">大小</th>
                  <th className="w-36">创建时间</th>
                  <th className="w-36">更新时间</th>
                  <th className="w-32">操作</th>
                </tr>
              </thead>
              <tbody>
                {pagedDocuments.map((d) => {
                  const st = DOC_STATUS_UI[d.status];
                  return (
                    <tr key={d.id}>
                      <td>
                        <Link
                          href={`/kbs/${id}/documents/${d.id}`}
                          className="inline-flex max-w-xs items-center gap-2 truncate font-medium text-brand hover:underline"
                        >
                          <FileText className="h-4 w-4 shrink-0 text-muted" />
                          <span className="truncate">{d.filename}</span>
                        </Link>
                      </td>
                      <td className="text-xs text-muted">
                        {d.source_type === "url" ? "URL" : "Local File"}
                      </td>
                      <td className="text-xs text-muted">chunk</td>
                      <td>
                        <span className="inline-flex items-center gap-1.5 text-xs">
                          <span className={cn("h-2 w-2 rounded-full", st.dot)} />
                          {st.label}
                        </span>
                      </td>
                      <td>
                        <Switch
                          size="sm"
                          checked={d.enabled !== false}
                          loading={docToggleBusy === d.id}
                          disabled={!canWrite || d.status !== "done"}
                          onCheckedChange={(checked) =>
                            onToggleDocEnabled(d, checked)
                          }
                          title={
                            docToggleBusy === d.id
                              ? "更新中…"
                              : d.status !== "done"
                                ? "ingest 完成后才可启用检索"
                                : d.enabled !== false
                                  ? "禁用后整篇文档不参与检索"
                                  : "启用后文档 chunks 可参与检索"
                          }
                        />
                      </td>
                      <td className="tabular-nums">{d.chunks_count}</td>
                      <td className="text-xs text-muted">
                        {fileExtension(d.filename)}
                      </td>
                      <td className="text-xs text-muted">
                        {formatFileSize(d.size_bytes)}
                      </td>
                      <td className="text-xs text-muted">
                        {formatAdminDate(d.created_at)}
                      </td>
                      <td className="text-xs text-muted">
                        {formatAdminDate(d.updated_at ?? d.created_at)}
                      </td>
                      <td>
                        <div className="flex items-center gap-0.5">
                          {canWrite && d.status === "done" && (
                            <AdminRowAction
                              icon={Play}
                              title="重新 ingest"
                              variant="brand"
                              loading={reingestingDocId === d.id}
                              disabled={reingestingDocId != null}
                              onClick={async () => {
                                setReingestingDocId(d.id);
                                try {
                                  await reingestDocument(id, d.id);
                                  toast.success("已提交重新 ingest");
                                  await refresh();
                                } catch (e) {
                                  toastApiError(e, (p) => router.push(p));
                                } finally {
                                  setReingestingDocId(null);
                                }
                              }}
                            />
                          )}
                          <AdminRowAction
                            icon={Layers}
                            title="分块管理"
                            variant="brand"
                            href={`/kbs/${id}/documents/${d.id}`}
                          />
                          {canWrite && (
                            <AdminRowAction
                              icon={Trash2}
                              title="删除"
                              variant="danger"
                              onClick={() => setPendingDelete(d)}
                            />
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </AdminPanel>

        <div className="mt-6 space-y-6">
        {!kb.is_system && (
          <MembersSection kbId={kb.id} isOwner={isOwner} />
        )}

        {/* v3-M3: owner-only advanced settings — grouping toggle + hybrid rebuild. */}
        {isOwner && !kb.is_system && (
          <section className="card mt-6 p-4">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Sparkles className="h-4 w-4 text-brand" />
              高级设置
            </div>

            <label className="mt-3 flex cursor-pointer items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={kb.grouping_enabled}
                disabled={groupingBusy}
                onChange={onToggleGrouping}
                className="mt-0.5 h-4 w-4 cursor-pointer accent-accent"
              />
              <span>
                <span className="font-medium">Grouping search</span>
                <span className="ml-1 text-xs text-muted">
                  每篇文档至多返回 1 个最相关 chunk，避免长文档独占 top-k。
                </span>
              </span>
            </label>

            <form onSubmit={onSaveChunkSettings} className="mt-4 border-t border-border pt-3">
              <div className="text-sm font-medium">分块参数（KB 默认）</div>
              <p className="mt-1 text-xs text-muted">
                单位：字符。仅对新上传 / 重新 ingest 的文档生效；单篇文档可在详情页覆盖。
              </p>
              <div className="mt-2 grid grid-cols-3 gap-2">
                <label className="text-xs">
                  <span className="text-muted">target</span>
                  <input
                    type="number"
                    value={chunkTarget}
                    onChange={(e) => setChunkTarget(e.target.value)}
                    className="mt-1 block w-full rounded-md border bg-bg px-2 py-1.5 text-sm"
                  />
                </label>
                <label className="text-xs">
                  <span className="text-muted">max_size</span>
                  <input
                    type="number"
                    value={chunkMaxSize}
                    onChange={(e) => setChunkMaxSize(e.target.value)}
                    className="mt-1 block w-full rounded-md border bg-bg px-2 py-1.5 text-sm"
                  />
                </label>
                <label className="text-xs">
                  <span className="text-muted">overlap</span>
                  <input
                    type="number"
                    value={chunkOverlap}
                    onChange={(e) => setChunkOverlap(e.target.value)}
                    className="mt-1 block w-full rounded-md border bg-bg px-2 py-1.5 text-sm"
                  />
                </label>
              </div>
              <button
                type="submit"
                disabled={chunkBusy}
                className="btn btn-secondary btn-sm mt-2"
              >
                保存分块参数
              </button>
            </form>

            <div className="mt-4 border-t border-border pt-3">
              <div className="text-sm font-medium">混合检索索引</div>
              <p className="mt-1 text-xs text-muted">
                启用后会用 BM25 + 向量两路融合检索，关键词查询命中明显改善。
                重建会丢弃当前 chunks 并重新 ingest 所有文档（约 30-90 秒），期间该 KB 临时无召回。
              </p>
              <button
                onClick={() => setPendingRebuild(true)}
                disabled={rebuildingKb}
                className="btn btn-secondary btn-sm mt-2"
                type="button"
              >
                <RefreshCw className={cn("h-4 w-4", rebuildingKb && "animate-spin")} />
                重建索引（启用混合检索）
              </button>
            </div>
          </section>
        )}

        {/* v3-M1: owner-only danger zone for KB deletion. */}
        {isOwner && !kb.is_system && (
          <div className="card mt-6 border-danger/30 p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-danger">
              <AlertCircle className="h-4 w-4" />
              危险操作
            </div>
            <p className="mt-1 text-xs text-muted">
              删除知识库会清除所有文档、chunks、成员关系和邀请链接。该操作不可逆。
            </p>
            <button
              onClick={() => setPendingDeleteKb(true)}
              disabled={deletingKb}
              className="btn btn-danger btn-sm mt-3"
              type="button"
            >
              <Trash2 className="h-4 w-4" />
              删除整个知识库
            </button>
          </div>
        )}
        </div>

      <Dialog
        open={pendingDelete != null}
        onOpenChange={(o) => !o && setPendingDelete(null)}
        title={`删除文档「${pendingDelete?.filename ?? ""}」？`}
        description="该文档及其所有 chunks 都会从 Qdrant 中清除。该操作不可逆。"
        variant="danger"
        confirmLabel="确认删除"
        onConfirm={confirmDeleteDoc}
        busy={deleting}
      />

      <Dialog
        open={pendingDeleteKb}
        onOpenChange={(o) => !o && setPendingDeleteKb(false)}
        title={`删除知识库「${kb.name}」？`}
        description="所有文档、chunks、成员关系和邀请链接都会一并清除。该操作不可逆。"
        variant="danger"
        confirmLabel="确认删除整个 KB"
        onConfirm={confirmDeleteKb}
        busy={deletingKb}
      />

      <Dialog
        open={pendingRebuild}
        onOpenChange={(o) => !o && setPendingRebuild(false)}
        title={`重建索引「${kb.name}」？`}
        description="所有文档会被重新 ingest 以启用混合检索 (BM25 + 向量)。约 30-90 秒，期间该 KB 聊天会临时无召回；文档原始文件保留。"
        confirmLabel="确认重建"
        onConfirm={confirmRebuildKb}
        busy={rebuildingKb}
      />
    </AdminPageShell>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof FileText;
  label: string;
  value: string | number;
}) {
  return (
    <div className="flex items-start gap-2 rounded-lg bg-surface-2 px-3 py-2">
      <Icon className="mt-0.5 h-3.5 w-3.5 flex-none text-muted" />
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
        <div className="truncate text-sm">{value}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// v2-M9: Members section
// ---------------------------------------------------------------------------
function MembersSection({ kbId, isOwner }: { kbId: string; isOwner: boolean }) {
  const [data, setData] = useState<KbMemberListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [pendingRemove, setPendingRemove] = useState<{
    user_id: string;
    email: string;
  } | null>(null);
  const [removing, setRemoving] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const d = await listMembers(kbId);
      setData(d);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [kbId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onChangeRole = async (userId: string, role: MemberRole) => {
    try {
      await patchMember(kbId, userId, role);
      toast.success("已更新角色");
      await refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const confirmRemove = async () => {
    if (!pendingRemove) return;
    setRemoving(true);
    try {
      await removeMember(kbId, pendingRemove.user_id);
      toast.success(`已移除 ${pendingRemove.email}`);
      setPendingRemove(null);
      await refresh();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setRemoving(false);
    }
  };

  return (
    <div className="card mt-6 overflow-hidden">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <div className="text-sm font-medium">
          成员（{(data?.members?.length ?? 0) + (data?.owner ? 1 : 0)}）
        </div>
        {isOwner && (
          <button
            onClick={() => setInviteOpen(true)}
            className="btn btn-primary btn-sm"
            type="button"
          >
            <UserPlus className="h-3 w-3" />
            邀请
          </button>
        )}
      </div>
      {loading ? (
        <div className="px-4 py-6 text-center text-sm text-muted">加载中…</div>
      ) : (
        <ul className="divide-y">
          {data?.owner && (
            <li className="flex items-center gap-3 px-4 py-3">
              <BookOpen className="h-4 w-4 flex-none text-brand" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm">{data.owner.email}</div>
                <div className="text-xs text-muted">
                  {data.owner.display_name || "—"}
                </div>
              </div>
              <span className="chip border-brand/30 bg-brand/10 text-brand">
                owner
              </span>
            </li>
          )}
          {data?.members.map((m) => (
            <li key={m.user_id} className="flex items-center gap-3 px-4 py-3">
              {m.role === "editor" ? (
                <Users className="h-4 w-4 flex-none text-info" />
              ) : (
                <Eye className="h-4 w-4 flex-none text-muted" />
              )}
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm">{m.email}</div>
                <div className="text-xs text-muted">
                  {m.display_name || "—"}
                  {m.invited_by_email && (
                    <> · 由 {m.invited_by_email} 邀请</>
                  )}
                </div>
              </div>
              {isOwner ? (
                <>
                  <Select
                    size="sm"
                    value={m.role}
                    onChange={(e) =>
                      onChangeRole(m.user_id, e.target.value as MemberRole)
                    }
                    options={[
                      { value: "editor", label: "editor" },
                      { value: "viewer", label: "viewer" },
                    ]}
                    className="w-[100px]"
                  />
                  <button
                    onClick={() =>
                      setPendingRemove({ user_id: m.user_id, email: m.email })
                    }
                    className="rounded-md p-1.5 text-muted transition hover:bg-danger/15 hover:text-danger"
                    aria-label="移除成员"
                    type="button"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </>
              ) : (
                <span
                  className={cn(
                    "chip",
                    m.role === "editor"
                      ? "border-info/30 bg-info/10 text-info"
                      : "border-border bg-surface text-muted"
                  )}
                >
                  {m.role}
                </span>
              )}
            </li>
          ))}
          {data?.members.length === 0 && !data?.owner && (
            <li className="px-4 py-6 text-center text-sm text-muted">
              暂无成员
            </li>
          )}
        </ul>
      )}

      {isOwner && (
        <InviteDialog
          kbId={kbId}
          open={inviteOpen}
          onClose={() => setInviteOpen(false)}
          onInvited={refresh}
        />
      )}

      <Dialog
        open={pendingRemove != null}
        onOpenChange={(o) => !o && setPendingRemove(null)}
        title={`移除 ${pendingRemove?.email ?? ""}？`}
        description="该用户将失去对此 KB 的访问。可重新邀请。"
        variant="danger"
        confirmLabel="确认移除"
        onConfirm={confirmRemove}
        busy={removing}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// v2-M9: Invite dialog — two tabs (by email, by link)
// ---------------------------------------------------------------------------
function InviteDialog({
  kbId,
  open,
  onClose,
  onInvited,
}: {
  kbId: string;
  open: boolean;
  onClose: () => void;
  onInvited: () => void;
}) {
  const [tab, setTab] = useState<"email" | "link">("email");
  const [email, setEmail] = useState("");
  const [emailRole, setEmailRole] = useState<MemberRole>("editor");
  const [emailBusy, setEmailBusy] = useState(false);

  const [linkRole, setLinkRole] = useState<MemberRole>("viewer");
  const [linkExpiresHours, setLinkExpiresHours] = useState<string>("");
  const [linkMaxUses, setLinkMaxUses] = useState<string>("");
  const [linkBusy, setLinkBusy] = useState(false);
  const [invitations, setInvitations] = useState<KbInvitation[]>([]);

  const reload = useCallback(async () => {
    try {
      const list = await listInvitations(kbId);
      setInvitations(list);
    } catch (e) {
      console.warn("listInvitations failed (non-fatal)", e);
    }
  }, [kbId]);

  useEffect(() => {
    if (open) {
      setTab("email");
      setEmail("");
      setEmailRole("editor");
      setLinkRole("viewer");
      setLinkExpiresHours("");
      setLinkMaxUses("");
      void reload();
    }
  }, [open, reload]);

  const onInviteEmail = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setEmailBusy(true);
    try {
      await inviteMember(kbId, email.trim().toLowerCase(), emailRole);
      toast.success(`已邀请 ${email.trim()} 为 ${emailRole}`);
      setEmail("");
      onInvited();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setEmailBusy(false);
    }
  };

  const onCreateLink = async () => {
    setLinkBusy(true);
    try {
      const hours = linkExpiresHours.trim() ? Number(linkExpiresHours) : null;
      const maxUses = linkMaxUses.trim() ? Number(linkMaxUses) : null;
      const expires_at =
        hours && hours > 0
          ? new Date(Date.now() + hours * 3600 * 1000).toISOString()
          : null;
      await createInvitation(kbId, {
        role: linkRole,
        expires_at,
        max_uses: maxUses,
      });
      toast.success("已生成分享链接");
      await reload();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setLinkBusy(false);
    }
  };

  const onRevoke = async (invId: string) => {
    try {
      await deleteInvitation(kbId, invId);
      toast.success("已撤销链接");
      await reload();
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  const buildUrl = (token: string) => {
    if (typeof window === "undefined") return `/invite/${token}`;
    return `${window.location.origin}/invite/${token}`;
  };

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("已复制");
    } catch {
      toast.error("复制失败");
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="card w-full max-w-lg overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div className="text-sm font-medium">邀请协作者</div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-muted hover:bg-surface-2"
            aria-label="关闭"
            type="button"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex border-b">
          <button
            type="button"
            onClick={() => setTab("email")}
            className={cn(
              "flex-1 px-4 py-2 text-sm transition",
              tab === "email"
                ? "border-b-2 border-brand text-fg"
                : "text-muted hover:text-fg"
            )}
          >
            按邮箱邀请
          </button>
          <button
            type="button"
            onClick={() => setTab("link")}
            className={cn(
              "flex-1 px-4 py-2 text-sm transition",
              tab === "link"
                ? "border-b-2 border-brand text-fg"
                : "text-muted hover:text-fg"
            )}
          >
            生成分享链接
          </button>
        </div>

        <div className="p-4">
          {tab === "email" ? (
            <form onSubmit={onInviteEmail} className="space-y-3">
              <div className="text-xs text-muted">
                被邀请者必须先在 AnyKB 注册一个账号，再用该邮箱邀请。
              </div>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="bob@example.com"
                className="block w-full rounded-md border bg-bg px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
              />
              <div className="flex items-center gap-2">
                <label className="text-xs text-muted">角色</label>
                <Select
                  size="sm"
                  value={emailRole}
                  onChange={(e) => setEmailRole(e.target.value as MemberRole)}
                  options={[
                    { value: "editor", label: "editor（读+写文档）" },
                    { value: "viewer", label: "viewer（只读）" },
                  ]}
                  className="flex-1"
                />
              </div>
              <button
                type="submit"
                disabled={emailBusy || !email.trim()}
                className="btn btn-primary w-full"
              >
                {emailBusy ? "邀请中…" : "发送邀请"}
              </button>
            </form>
          ) : (
            <div className="space-y-4">
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <label className="text-xs text-muted w-16">角色</label>
                  <Select
                    size="sm"
                    value={linkRole}
                    onChange={(e) => setLinkRole(e.target.value as MemberRole)}
                    options={[
                      { value: "viewer", label: "viewer（只读）" },
                      { value: "editor", label: "editor（读+写）" },
                    ]}
                    className="flex-1"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <label className="text-xs text-muted w-16">有效期</label>
                  <input
                    type="number"
                    min="0"
                    value={linkExpiresHours}
                    onChange={(e) => setLinkExpiresHours(e.target.value)}
                    placeholder="留空 = 永不过期"
                    className="flex-1 rounded-md border bg-bg px-3 py-1.5 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
                  />
                  <span className="text-xs text-muted">小时</span>
                </div>
                <div className="flex items-center gap-2">
                  <label className="text-xs text-muted w-16">最大次数</label>
                  <input
                    type="number"
                    min="1"
                    value={linkMaxUses}
                    onChange={(e) => setLinkMaxUses(e.target.value)}
                    placeholder="留空 = 不限"
                    className="flex-1 rounded-md border bg-bg px-3 py-1.5 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
                  />
                  <span className="text-xs text-muted">次</span>
                </div>
                <button
                  onClick={onCreateLink}
                  disabled={linkBusy}
                  className="btn btn-primary w-full"
                  type="button"
                >
                  {linkBusy ? "生成中…" : "生成新链接"}
                </button>
              </div>

              {invitations.length > 0 && (
                <div className="mt-4 border-t pt-3">
                  <div className="mb-2 text-xs font-medium text-muted">
                    现有链接
                  </div>
                  <ul className="space-y-2">
                    {invitations.map((inv) => (
                      <li
                        key={inv.id}
                        className={cn(
                          "rounded-md border bg-surface-2 p-2 text-xs",
                          inv.revoked && "opacity-50"
                        )}
                      >
                        <div className="flex items-center gap-1.5">
                          <span className="chip border-border bg-surface text-muted">
                            {inv.role}
                          </span>
                          {inv.max_uses != null && (
                            <span className="text-muted">
                              {inv.uses_count}/{inv.max_uses} 次
                            </span>
                          )}
                          {inv.expires_at && (
                            <span className="text-muted">
                              到期 {new Date(inv.expires_at).toLocaleString()}
                            </span>
                          )}
                          {inv.revoked && (
                            <span className="text-danger">已撤销</span>
                          )}
                          <div className="flex-1" />
                          {!inv.revoked && (
                            <>
                              <button
                                onClick={() => copy(buildUrl(inv.id))}
                                className="rounded p-1 hover:bg-brand/15 hover:text-brand"
                                title="复制链接"
                                type="button"
                              >
                                <Copy className="h-3 w-3" />
                              </button>
                              <button
                                onClick={() => onRevoke(inv.id)}
                                className="rounded p-1 hover:bg-danger/15 hover:text-danger"
                                title="撤销"
                                type="button"
                              >
                                <X className="h-3 w-3" />
                              </button>
                            </>
                          )}
                        </div>
                        {!inv.revoked && (
                          <div className="mt-1 break-all font-mono text-[10px] text-muted">
                            {buildUrl(inv.id)}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
