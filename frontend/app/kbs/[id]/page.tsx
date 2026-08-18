"use client";

import { toast } from "@/lib/toast";
import {
  AlertCircle,
  BookOpen,
  ClipboardList,
  Copy,
  Eye,
  FileText,
  Layers,
  Link2,
  Lock,
  Play,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Trash2,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  FormEvent,
  use,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import AppModal from "@/components/AppModal";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { AddDocumentDialog } from "@/components/kb/AddDocumentDialog";
import {
  DOC_STATUS_UI,
  fileExtension,
  formatAdminDate,
  formatFileSize,
} from "@/components/kb/admin-utils";
import {
  AdminPageShell,
  AdminPanel,
  AdminSection,
  AdminSectionNav,
} from "@/components/kb/AdminPageShell";
import {
  AdminRowAction,
  AdminRowMoreTrigger,
  AdminToolbarButton,
} from "@/components/kb/AdminTableActions";
import { KbEvalSection } from "@/components/kb/KbEvalSection";
import Select from "@/components/Select";
import { Button } from "@/components/ui/button";
import { Pagination } from "@/components/ui/pagination";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { LoadingState, StateView } from "@/components/ui/state-view";
import { Switch } from "@/components/ui/switch";
import { getToken } from "@/lib/auth";
import { toastApiError } from "@/lib/byok-toast";
import { cn } from "@/lib/cn";
import {
  createInvitation,
  deleteDocument,
  deleteInvitation,
  deleteKb,
  formatKbRole,
  getKb,
  inviteMember,
  listInvitations,
  listMembers,
  patchDocument,
  patchKb,
  patchMember,
  rebuildKb,
  reingestDocument,
  removeMember,
  uploadFile,
  uploadUrl,
  type ChunkStrategy,
  type DocStatus,
  type Document,
  type KBDetail,
  type KbInvitation,
  type KbMemberListResponse,
  type KbRole,
  type MemberRole,
} from "@/lib/kb-api";

const CHUNK_STRATEGY_OPTIONS: { value: ChunkStrategy; label: string }[] = [
  { value: "recursive", label: "递归文本切分" },
  { value: "markdown_heading", label: "Markdown 标题切分" },
  { value: "semantic", label: "轻量语义切分" },
  { value: "table_aware", label: "表格感知切分" },
  { value: "code", label: "代码感知切分" },
  { value: "parent_child", label: "轻量父子切分" },
];

const kbDetailInputClass =
  "admin-input";

export default function KbDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();

  const [kb, setKb] = useState<KBDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  const [uploadingFiles, setUploadingFiles] = useState<string[]>([]);
  const [addDocOpen, setAddDocOpen] = useState(false);
  const [submittingUrl, setSubmittingUrl] = useState(false);

  const [pendingDelete, setPendingDelete] = useState<Document | null>(null);
  const [deleting, setDeleting] = useState(false);

  // v3-M1: owner-only KB-level deletion (danger zone at page bottom)
  const [pendingDeleteKb, setPendingDeleteKb] = useState(false);
  const [deletingKb, setDeletingKb] = useState(false);
  // v3-M3: advanced settings + index rebuild
  const [groupingBusy, setGroupingBusy] = useState(false);
  const [kgBusy, setKgBusy] = useState(false);
  const [chunkBusy, setChunkBusy] = useState(false);
  const [chunkStrategy, setChunkStrategy] = useState<ChunkStrategy>("recursive");
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
    setChunkStrategy(kb.chunk_strategy ?? "recursive");
    setChunkTarget(String(kb.chunk_target ?? 1500));
    setChunkMaxSize(String(kb.chunk_max_size ?? 1800));
    setChunkOverlap(String(kb.chunk_overlap ?? 150));
    // Sync form fields from KB chunk settings only — not every kb object identity change.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional field deps
  }, [kb?.chunk_strategy, kb?.chunk_target, kb?.chunk_max_size, kb?.chunk_overlap, kb?.id]);

  const onSaveChunkSettings = async (e: FormEvent) => {
    e.preventDefault();
    setChunkBusy(true);
    try {
      const updated = await patchKb(id, {
        chunk_strategy: chunkStrategy,
        chunk_target: parseInt(chunkTarget, 10),
        chunk_max_size: parseInt(chunkMaxSize, 10),
        chunk_overlap: parseInt(chunkOverlap, 10),
      });
      setKb((cur) =>
        cur
          ? {
              ...cur,
              chunk_strategy: updated.chunk_strategy,
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

  const onUploadFiles = async (files: File[]) => {
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
      throw err;
    } finally {
      setUploadingFiles([]);
    }
  };

  const onSubmitUrl = async (rawUrl: string) => {
    const trimmed = rawUrl.trim();
    if (!trimmed) return;
    setSubmittingUrl(true);
    try {
      await uploadUrl(id, trimmed);
      toast.success("已提交 URL，正在抓取并 ingest");
      await refresh();
    } catch (err) {
      toastApiError(err, (p) => router.push(p));
      throw err;
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
      toast.success(`已删除知识库 ${kb?.name ?? ""}`);
      router.replace("/kbs");
    } catch (err) {
      toast.error((err as Error).message);
      setDeletingKb(false);
    }
  };

  // v3-M3: toggle grouping_enabled. Optimistic: update UI immediately, revert on error.
  const onToggleGrouping = async (next: boolean) => {
    if (!kb) return;
    setGroupingBusy(true);
    // Optimistic local update so the checkbox doesn't lag while PATCH runs.
    setKb({ ...kb, grouping_enabled: next });
    try {
      const updated = await patchKb(id, { grouping_enabled: next });
      // Server is source of truth - splice in only the toggleable field to
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

  const onToggleKg = async (next: boolean) => {
    if (!kb) return;
    setKgBusy(true);
    setKb({ ...kb, kg_enabled: next });
    try {
      const updated = await patchKb(id, { kg_enabled: next });
      setKb((cur) => (cur ? { ...cur, kg_enabled: updated.kg_enabled } : cur));
      toast.success(
        next
          ? "已开启知识图谱召回（将同步已入库文档到 LightRAG）"
          : "已关闭知识图谱召回"
      );
    } catch (err) {
      setKb((cur) => (cur ? { ...cur, kg_enabled: !next } : cur));
      toast.error((err as Error).message);
    } finally {
      setKgBusy(false);
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
      // the pending -> ingesting transition without waiting for the timer.
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

  const onReingestDoc = async (doc: Document) => {
    setReingestingDocId(doc.id);
    try {
      await reingestDocument(id, doc.id);
      toast.success("已提交重新 ingest");
      await refresh();
    } catch (e) {
      toastApiError(e, (p) => router.push(p));
    } finally {
      setReingestingDocId(null);
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

  type KbSectionId = "documents" | "members" | "evaluation" | "retrieval" | "danger";
  const [activeSection, setActiveSection] = useState<KbSectionId>("documents");

  // Allow flags used only for section mounting logic.
  // Keep them safe during initial renders when `kb` is still null/undefined,
  // so Hook order stays stable (no conditional early returns).
  const allowMembers = !kb?.is_system;
  const allowEvaluation = (() => {
    if (!kb) return false;
    const myRole = kb.my_role ?? (kb.is_system ? "viewer" : "owner");
    const isOwner = myRole === "owner";
    return (isOwner || myRole === "editor") && !kb.is_system;
  })();
  const allowRetrieval = (() => {
    if (!kb) return false;
    const myRole = kb.my_role ?? (kb.is_system ? "viewer" : "owner");
    return myRole === "owner" && !kb.is_system;
  })();
  const allowDanger = allowRetrieval;

  useEffect(() => {
    const resolve = (): KbSectionId => {
      const raw = window.location.hash.replace(/^#/, "");
      const next = raw as KbSectionId;
      if (next === "documents") return "documents";
      if (next === "members" && allowMembers) return "members";
      if (next === "evaluation" && allowEvaluation) return "evaluation";
      if (next === "retrieval" && allowRetrieval) return "retrieval";
      if (next === "danger" && allowDanger) return "danger";
      return "documents";
    };

    const onHashChange = () => setActiveSection(resolve());
    setActiveSection(resolve());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowMembers, allowEvaluation, allowRetrieval, allowDanger]);

  useEffect(() => {
    const el = document.getElementById(activeSection);
    el?.scrollIntoView();
  }, [activeSection]);

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
          action={
            <Button asChild variant="outline" className="min-h-[var(--control-h)] px-4 text-sm">
              <Link href="/kbs">返回知识库列表</Link>
            </Button>
          }
          className="w-full max-w-md"
        />
      </div>
    );
  }

  // v2-M9: per-KB effective role drives every write button.
  const myRole: KbRole = kb.my_role ?? (kb.is_system ? "viewer" : "owner");
  const isOwner = myRole === "owner";
  const canWrite = (isOwner || myRole === "editor") && !kb.is_system;

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
        <Button asChild variant="outline">
          <Link href="/kbs">返回知识库</Link>
        </Button>
      }
    >
        {/* v2-M9: role banner for non-owner / non-system access */}
        {!kb.is_system && myRole === "editor" && (
          <div className="mb-4 rounded-lg border border-info/25 bg-info/10 px-4 py-3 text-sm shadow-sm">
            <div className="flex items-start gap-3">
              <span className="admin-icon-tile admin-icon-tile-info rounded-md">
                <Users className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <div className="font-medium text-info">你是协作者（编辑者）</div>
                <p className="mt-1 text-xs leading-5 text-info/90">
                  可以上传 / 删除文档；不能删除 KB 或管理成员。
                </p>
              </div>
            </div>
          </div>
        )}
        {!kb.is_system && myRole === "viewer" && (
          <div className="mb-4 rounded-lg border border-surface-border/75 bg-surface px-4 py-3 text-sm shadow-sm">
            <div className="flex items-start gap-3">
              <span className="admin-icon-tile admin-icon-tile-muted rounded-md shadow-none">
                <Eye className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <div className="font-medium">你是只读访问者</div>
                <p className="mt-1 text-xs leading-5 text-muted">
                  可以在对话中选用这个 KB，但不能上传 / 删除内容。
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Meta + stats */}
        <section className="admin-panel mb-4 overflow-hidden">
          <div className="flex flex-col gap-3 bg-surface-2/35 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex min-w-0 items-start gap-3">
              <span className="admin-icon-tile admin-icon-tile-brand">
                {kb.is_system ? <Lock className="h-4 w-4" /> : <BookOpen className="h-4 w-4" />}
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <h2 className="truncate text-base font-semibold">{kb.name}</h2>
                  {kb.is_system && <span className="chip chip-warning">示例</span>}
                  {kb.is_system && <span className="chip chip-muted">只读</span>}
                  <span className="chip chip-muted">{formatKbRole(myRole)}</span>
                </div>
                {kb.description && (
                  <p className="mt-1 text-sm leading-6 text-muted">{kb.description}</p>
                )}
                <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs tabular-nums text-muted">
                  <span>
                    <span className="font-semibold text-ink">{kb.documents.length}</span> 文档
                  </span>
                  <span aria-hidden className="text-surface-border">·</span>
                  <span>
                    <span className="font-semibold text-ink">{kb.chunks_count}</span> 分块
                  </span>
                  <span aria-hidden className="text-surface-border">·</span>
                  <span className="max-w-[18rem] truncate font-mono text-[11px]">
                    {kb.embedding_model || "—"}
                  </span>
                  <span aria-hidden className="text-surface-border">·</span>
                  <span>{kb.vector_size} 维</span>
                </p>
              </div>
            </div>
          </div>
        </section>

        <AdminSectionNav
          value={`#${activeSection}`}
          onValueChange={(value) => {
            const next = value.replace(/^#/, "");
            setActiveSection(next as KbSectionId);
            window.location.hash = value;
          }}
          items={[
            { label: kb.is_system ? "示例说明" : "文档", href: "#documents", icon: FileText },
            ...(!kb.is_system
              ? [{ label: "成员", href: "#members", icon: Users }]
              : []),
            ...(canWrite
              ? [{ label: "测评", href: "#evaluation", icon: ClipboardList }]
              : []),
            ...(isOwner && !kb.is_system
              ? [
                  { label: "检索设置", href: "#retrieval", icon: SlidersHorizontal },
                  { label: "危险操作", href: "#danger", icon: AlertCircle, muted: true },
                ]
              : []),
          ]}
        />

        {activeSection === "documents" ? (
          <AdminSection
            id="documents"
            icon={FileText}
            title={kb.is_system ? "示例说明" : "文档"}
            description={
              kb.is_system
                ? "内置示例库仅供对话演示，内容只读，不开放文档管理。"
                : "上传、筛选、启停文档，并进入单篇文档的分块管理。"
            }
            className="mt-0"
            actions={
              canWrite && !kb.is_system ? (
                <Button
                  type="button"
                  disabled={uploadingFiles.length > 0 || submittingUrl}
                  onClick={() => setAddDocOpen(true)}
                >
                  <Plus className="h-4 w-4" />
                  添加文档
                </Button>
              ) : undefined
            }
          >
        {kb.is_system ? (
          <StateView
            variant="notice"
            density="compact"
            title="系统内置示例库"
            description={
              kb.documents.length === 0
                ? "这是 Agenora 内置的旅行演示知识库，可在对话中直接选用。文档清单不在此页开放管理；下方无文档列表属预期表现。"
                : "这是 Agenora 内置的旅行演示知识库。所有用户都能在对话中选中它；内容只读，不能上传或删除。"
            }
            className="mb-4"
          />
        ) : null}

        {!(kb.is_system && kb.documents.length === 0) && (
        <AdminPanel
          title={kb.is_system ? "示例文档" : "文档列表"}
          subtitle={kb.is_system ? "只读浏览，不可上传或删除" : "支持筛选与分块管理"}
          toolbar={
            kb.is_system ? (
              <AdminToolbarButton
                icon={RefreshCw}
                loading={listRefreshing}
                onClick={() => void onRefreshList()}
              >
                刷新
              </AdminToolbarButton>
            ) : (
              <>
                <div className="input-shell flex h-[var(--control-h)] items-center gap-2 px-3">
                  <Search className="h-3.5 w-3.5 text-muted" />
                  <input
                    type="search"
                    value={docSearch}
                    onChange={(e) => setDocSearch(e.target.value)}
                    placeholder="搜索文档名称"
                    className="w-36 bg-transparent text-sm outline-none sm:w-44"
                  />
                </div>
                <Select
                  className="w-[120px] admin-select-trigger"
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
            )
          }
          footer={
            <Pagination
              total={filteredDocuments.length}
              page={docPage}
              pageSize={docPageSize}
              onPageChange={setDocPage}
            />
          }
        >
          {kb.documents.length === 0 ? (
            <StateView
              density="compact"
              icon={FileText}
              title="还没有文档"
              description="上传文档后，可在这里筛选、启停和进入分块管理。"
              className="m-4"
            />
          ) : filteredDocuments.length === 0 ? (
            <StateView
              density="compact"
              icon={Search}
              title="没有匹配的文档"
              description="调整搜索关键词或状态筛选后再试。"
              className="m-4"
            />
          ) : (
            <>
            <div className="space-y-3 p-3 md:hidden">
              {pagedDocuments.map((d) => {
                const st = DOC_STATUS_UI[d.status];
                return (
                  <article
                    key={d.id}
                    className="rounded-lg border border-surface-border/70 bg-surface px-3 py-3"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <Link
                          href={`/kbs/${id}/documents/${d.id}`}
                          className="inline-flex max-w-full items-center gap-2 font-medium text-brand"
                        >
                          <FileText className="h-4 w-4 shrink-0 text-muted" />
                          <span className="truncate">{d.filename}</span>
                        </Link>
                        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                          <span>{d.source_type === "url" ? "URL" : "本地文件"}</span>
                          <span>{fileExtension(d.filename)}</span>
                          <span>{formatFileSize(d.size_bytes)}</span>
                        </div>
                      </div>
                      <span className={cn("chip", st.badge)}>{st.label}</span>
                    </div>

                    <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
                      <div>
                        <dt className="text-muted">分块数</dt>
                        <dd className="mt-0.5 tabular-nums">{d.chunks_count}</dd>
                      </div>
                      <div>
                        <dt className="text-muted">更新时间</dt>
                        <dd className="mt-0.5">{formatAdminDate(d.updated_at ?? d.created_at)}</dd>
                      </div>
                    </dl>

                    <div className="mt-3 flex items-center justify-between gap-2 border-t border-surface-border/60 pt-3">
                      <Switch
                        size="sm"
                        checked={d.enabled !== false}
                        loading={docToggleBusy === d.id}
                        disabled={!canWrite || d.status !== "done"}
                        onCheckedChange={(checked) => onToggleDocEnabled(d, checked)}
                        title={
                          docToggleBusy === d.id
                            ? "更新中..."
                            : d.status !== "done"
                              ? "ingest 完成后才可启用检索"
                              : d.enabled !== false
                                ? "禁用后整篇文档不参与检索"
                                : "启用后文档分块可参与检索"
                        }
                      />
                      <div className="flex items-center gap-1">
                        <AdminRowAction
                          icon={Layers}
                          title="分块管理"
                          label="分块"
                          variant="brand"
                          href={`/kbs/${id}/documents/${d.id}`}
                        />
                        {canWrite && (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <AdminRowMoreTrigger
                                aria-label={`${d.filename} 更多操作`}
                              />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-40">
                              {d.status === "done" && (
                                <DropdownMenuItem
                                  className="cursor-pointer"
                                  disabled={reingestingDocId != null}
                                  onSelect={() => void onReingestDoc(d)}
                                >
                                  <Play className="h-4 w-4" />
                                  重新 ingest
                                </DropdownMenuItem>
                              )}
                              {d.status === "done" && <DropdownMenuSeparator />}
                              <DropdownMenuItem
                                className="cursor-pointer"
                                variant="destructive"
                                onSelect={() => setPendingDelete(d)}
                              >
                                <Trash2 className="h-4 w-4" />
                                删除
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        )}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>

            <div className="hidden md:block">
            <table className="admin-table admin-table-documents">
              <thead>
                <tr>
                  <th>文档</th>
                  <th className="w-28">状态</th>
                  <th className="w-16">启用</th>
                  <th className="w-16">分块数</th>
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
                        <div className="min-w-0">
                          <Link
                            href={`/kbs/${id}/documents/${d.id}`}
                            className="inline-flex max-w-sm items-center gap-2 truncate font-medium text-brand hover:underline"
                          >
                            <FileText className="h-4 w-4 shrink-0 text-muted" />
                            <span className="truncate">{d.filename}</span>
                          </Link>
                          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                            <span>{d.source_type === "url" ? "URL" : "本地文件"}</span>
                            <span>{fileExtension(d.filename)}</span>
                            <span>{formatFileSize(d.size_bytes)}</span>
                            <span>创建 {formatAdminDate(d.created_at)}</span>
                          </div>
                        </div>
                      </td>
                      <td>
                        <span className={cn("chip", st.badge)}>{st.label}</span>
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
                              ? "更新中..."
                              : d.status !== "done"
                                ? "ingest 完成后才可启用检索"
                                : d.enabled !== false
                                  ? "禁用后整篇文档不参与检索"
                                  : "启用后文档分块可参与检索"
                          }
                        />
                      </td>
                      <td className="tabular-nums">{d.chunks_count}</td>
                      <td className="text-xs text-muted">
                        {formatAdminDate(d.updated_at ?? d.created_at)}
                      </td>
                      <td>
                        <div className="flex items-center gap-1">
                          <AdminRowAction
                            icon={Layers}
                            title="分块管理"
                            label="分块"
                            variant="brand"
                            href={`/kbs/${id}/documents/${d.id}`}
                          />
                          {canWrite && (
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <AdminRowMoreTrigger
                                  aria-label={`${d.filename} 更多操作`}
                                />
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end" className="w-40">
                                {d.status === "done" && (
                                  <DropdownMenuItem
                                    className="cursor-pointer"
                                    disabled={reingestingDocId != null}
                                    onSelect={() => void onReingestDoc(d)}
                                  >
                                    <Play className="h-4 w-4" />
                                    重新 ingest
                                  </DropdownMenuItem>
                                )}
                                {d.status === "done" && <DropdownMenuSeparator />}
                                <DropdownMenuItem
                                  className="cursor-pointer"
                                  variant="destructive"
                                  onSelect={() => setPendingDelete(d)}
                                >
                                  <Trash2 className="h-4 w-4" />
                                  删除
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </div>
            </>
          )}
        </AdminPanel>
        )}
          </AdminSection>
        ) : null}

        {!kb.is_system && activeSection === "members" ? (
          <AdminSection
            id="members"
            icon={Users}
            title="成员"
            description="管理谁可以查看或维护这个知识库。"
            className="mt-0"
          >
            <MembersSection kbId={kb.id} isOwner={isOwner} />
          </AdminSection>
        ) : null}

        {canWrite && activeSection === "evaluation" ? <KbEvalSection kbId={kb.id} /> : null}

        {/* v3-M3: owner-only advanced settings - grouping toggle + hybrid rebuild. */}
        {isOwner && !kb.is_system && activeSection === "retrieval" ? (
          <AdminSection
            id="retrieval"
            icon={SlidersHorizontal}
            title="检索设置"
            description="统一管理 KB 默认分块参数、grouping search 和索引重建。"
            className="mt-0"
          >
          <section className="admin-panel overflow-hidden">
            <div className="flex items-start gap-3 border-b border-surface-border/70 bg-surface-2/35 px-4 py-4">
              <span className="admin-icon-tile admin-icon-tile-brand">
                <SlidersHorizontal className="h-4 w-4" />
              </span>
              <div>
                <div className="text-sm font-semibold">高级设置</div>
                <p className="mt-1 text-xs text-muted">
                  配置默认分块参数和索引重建策略，改动会影响后续 ingest 和检索召回。
                </p>
              </div>
            </div>

            <div className="m-4 flex items-start gap-3 rounded-lg border border-surface-border/80 bg-surface p-4 text-sm shadow-sm transition hover:border-brand/25 hover:bg-surface-2/60">
              <Switch
                checked={kb.grouping_enabled}
                disabled={groupingBusy}
                onCheckedChange={(checked) => void onToggleGrouping(checked)}
                className="mt-1"
                aria-label="切换 grouping search"
              />
              <span>
                <span className="font-medium">Grouping search</span>
                <span className="ml-1 text-xs text-muted">
                  每篇文档至多返回 1 个最相关 chunk，避免长文档独占 top-k。
                </span>
              </span>
            </div>

            <div className="mx-4 mb-4 flex items-start gap-3 rounded-lg border border-surface-border/80 bg-surface p-4 text-sm shadow-sm transition hover:border-brand/25 hover:bg-surface-2/60">
              <Switch
                checked={Boolean(kb.kg_enabled)}
                disabled={kgBusy}
                onCheckedChange={(checked) => void onToggleKg(checked)}
                className="mt-1"
                aria-label="切换知识图谱召回"
              />
              <span>
                <span className="font-medium">知识图谱召回</span>
                <span className="ml-1 text-xs text-muted">
                  经 LightRAG Server + Neo4j 做实体关系召回，与向量/关键词混合检索并行。开启后会同步已入库文档（额外消耗 LLM）。图谱浏览器：
                  localhost:7474
                </span>
              </span>
            </div>

            <form onSubmit={onSaveChunkSettings} className="border-t border-surface-border/70 px-4 py-4">
              <div className="text-sm font-medium">分块参数（KB 默认）</div>
              <p className="mt-1 text-xs text-muted">
                单位：字符。仅对新上传 / 重新 ingest 的文档生效；单篇文档可在详情页覆盖。
              </p>
              <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-4">
                <label className="text-xs">
                  <span className="text-muted">切分策略</span>
                  <Select
                    value={chunkStrategy}
                    onChange={(e) => setChunkStrategy(e.target.value as ChunkStrategy)}
                    options={CHUNK_STRATEGY_OPTIONS}
                    className="mt-1 h-[var(--control-h)] admin-select-trigger"
                    contentAlign="start"
                    contentPosition="popper"
                  />
                </label>
                <label className="text-xs">
                  <span className="text-muted">目标长度</span>
                  <input
                    type="number"
                    value={chunkTarget}
                    onChange={(e) => setChunkTarget(e.target.value)}
                    className={cn(kbDetailInputClass, "mt-1")}
                  />
                </label>
                <label className="text-xs">
                  <span className="text-muted">最大长度</span>
                  <input
                    type="number"
                    value={chunkMaxSize}
                    onChange={(e) => setChunkMaxSize(e.target.value)}
                    className={cn(kbDetailInputClass, "mt-1")}
                  />
                </label>
                <label className="text-xs">
                  <span className="text-muted">重叠长度</span>
                  <input
                    type="number"
                    value={chunkOverlap}
                    onChange={(e) => setChunkOverlap(e.target.value)}
                    className={cn(kbDetailInputClass, "mt-1")}
                  />
                </label>
              </div>
              <Button
                type="submit"
                disabled={chunkBusy}
                variant="outline"
                className="mt-3 min-h-[var(--control-h)] px-4 text-sm"
              >
                保存分块参数
              </Button>
            </form>

            <div className="border-t border-surface-border/70 bg-surface-2/25 px-4 py-4">
              <div className="text-sm font-medium">混合检索索引</div>
              <p className="mt-1 text-xs text-muted">
                启用后会用 BM25 + 向量两路融合检索，关键词查询命中明显改善。
                重建会丢弃当前分块并重新入库所有文档（约 30-90 秒），期间该知识库临时无召回。
              </p>
              <Button
                onClick={() => setPendingRebuild(true)}
                disabled={rebuildingKb}
                variant="outline"
                className="mt-3 min-h-[var(--control-h)] px-4 text-sm"
                type="button"
              >
                <RefreshCw className={cn("h-4 w-4", rebuildingKb && "animate-spin")} />
                重建索引（启用混合检索）
              </Button>
            </div>
          </section>
          </AdminSection>
        ) : null}

        {/* v3-M1: owner-only danger zone for KB deletion. */}
        {isOwner && !kb.is_system && activeSection === "danger" ? (
          <AdminSection
            id="danger"
            icon={AlertCircle}
            title="危险操作"
            description="高风险操作集中在这里，避免和日常文档维护混在一起。"
            className="mt-0"
          >
          <div className="rounded-lg border border-danger/30 bg-danger/5 p-4 shadow-sm">
            <div className="flex items-start gap-3">
              <span className="admin-icon-tile admin-icon-tile-danger">
                <AlertCircle className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-danger">危险操作</div>
                <p className="mt-1 text-xs leading-5 text-muted">
                  删除知识库会清除所有文档、分块、成员关系和邀请链接。该操作不可逆。
                </p>
              </div>
            </div>
            <Button
              onClick={() => setPendingDeleteKb(true)}
              disabled={deletingKb}
              variant="destructive"
              className="mt-4 min-h-[var(--control-h)] px-4 text-sm"
              type="button"
            >
              <Trash2 className="h-4 w-4" />
              删除整个知识库
            </Button>
          </div>
          </AdminSection>
        ) : null}

      <AddDocumentDialog
        open={addDocOpen}
        onOpenChange={setAddDocOpen}
        uploading={uploadingFiles.length > 0}
        submittingUrl={submittingUrl}
        onUploadFiles={onUploadFiles}
        onSubmitUrl={onSubmitUrl}
      />

      <ConfirmDialog
        open={pendingDelete != null}
        onOpenChange={(o) => !o && setPendingDelete(null)}
        title="删除文档？"
        description={
          <div className="space-y-3">
            <p>该文档及其所有分块都会从向量库中清除。该操作不可逆。</p>
            {pendingDelete ? (
              <div className="rounded-lg border border-surface-border/70 bg-surface-2 px-3 py-2">
                <div className="text-xs font-medium text-muted">文档</div>
                <div className="mt-1 max-h-24 overflow-y-auto break-all text-sm text-ink">
                  {pendingDelete.filename}
                </div>
              </div>
            ) : null}
          </div>
        }
        variant="danger"
        confirmLabel="确认删除"
        onConfirm={confirmDeleteDoc}
        busy={deleting}
      />

      <ConfirmDialog
        open={pendingDeleteKb}
        onOpenChange={(o) => !o && setPendingDeleteKb(false)}
        title={`删除知识库「${kb.name}」？`}
        description="所有文档、分块、成员关系和邀请链接都会一并清除。该操作不可逆。"
        variant="danger"
        confirmLabel="确认删除整个 KB"
        onConfirm={confirmDeleteKb}
        busy={deletingKb}
      />

      <ConfirmDialog
        open={pendingRebuild}
        onOpenChange={(o) => !o && setPendingRebuild(false)}
        title={`重建索引「${kb.name}」？`}
        description="所有文档会被重新 ingest 以启用混合检索（BM25 + 向量）。约 30-90 秒，期间该 KB 聊天会临时无召回；文档原始文件保留。"
        confirmLabel="确认重建"
        onConfirm={confirmRebuildKb}
        busy={rebuildingKb}
      />
    </AdminPageShell>
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

  const memberCount = (data?.members?.length ?? 0) + (data?.owner ? 1 : 0);

  return (
    <AdminPanel
      title={`成员（${memberCount}）`}
      subtitle="按角色管理知识库访问权限，owner 固定拥有完整控制权。"
      bodyClassName="bg-surface/35"
      toolbar={
        isOwner ? (
          <Button
            onClick={() => setInviteOpen(true)}
            className="min-h-[var(--control-h)] px-3 text-sm"
            type="button"
          >
            <UserPlus className="h-4 w-4" />
            邀请
          </Button>
        ) : null
      }
    >
      {loading ? (
        <div className="space-y-2 p-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <div
              key={index}
              className="h-16 animate-pulse rounded-lg border border-surface-border/60 bg-surface-2/45"
            />
          ))}
        </div>
      ) : !data?.owner && (data?.members.length ?? 0) === 0 ? (
        <StateView
          density="compact"
          icon={Users}
          title="暂无成员"
          description="所有者可以通过邮箱或邀请链接添加协作者。"
          className="m-4"
        />
      ) : (
        <ul className="space-y-2 p-4">
          {data?.owner && (
            <li className="flex min-h-16 items-center gap-3 rounded-lg border border-brand/20 bg-brand/5 px-3 py-2.5 shadow-sm">
              <span className="admin-icon-tile admin-icon-tile-brand">
                <BookOpen className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{data.owner.email}</div>
                <div className="mt-0.5 text-xs text-muted">
                  {data.owner.display_name || "-"}
                </div>
              </div>
              <span className="chip chip-brand shadow-sm">
                {formatKbRole("owner")}
              </span>
            </li>
          )}
          {data?.members.map((m) => (
            <li
              key={m.user_id}
              className="flex min-h-16 items-center gap-3 rounded-lg border border-surface-border/70 bg-surface px-3 py-2.5 shadow-sm transition hover:border-brand/25 hover:bg-surface-2/55"
            >
              <span
                className={cn(
                  "admin-icon-tile",
                  m.role === "editor"
                    ? "admin-icon-tile-info"
                    : "admin-icon-tile-muted"
                )}
              >
                {m.role === "editor" ? (
                  <Users className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{m.email}</div>
                <div className="mt-0.5 truncate text-xs text-muted">
                  {m.display_name || "-"}
                  {m.invited_by_email && (
                    <> · 由 {m.invited_by_email} 邀请</>
                  )}
                </div>
              </div>
              {isOwner ? (
                <>
                  <Select
                    value={m.role}
                    onChange={(e) =>
                      onChangeRole(m.user_id, e.target.value as MemberRole)
                    }
                    options={[
                      { value: "editor", label: formatKbRole("editor") },
                      { value: "viewer", label: formatKbRole("viewer") },
                    ]}
                    className="h-[var(--control-h)] w-[112px] admin-select-trigger"
                  />
                  <button
                    onClick={() =>
                      setPendingRemove({ user_id: m.user_id, email: m.email })
                    }
                    className="admin-icon-action admin-icon-action-danger"
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
                      ? "chip-info"
                      : "chip-muted"
                  )}
                >
                  {formatKbRole(m.role)}
                </span>
              )}
            </li>
          ))}
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

      <ConfirmDialog
        open={pendingRemove != null}
        onOpenChange={(o) => !o && setPendingRemove(null)}
        title={`移除 ${pendingRemove?.email ?? ""}？`}
        description="该用户将失去对此 KB 的访问。可重新邀请。"
        variant="danger"
        confirmLabel="确认移除"
        onConfirm={confirmRemove}
        busy={removing}
      />
    </AdminPanel>
  );
}

// ---------------------------------------------------------------------------
// v2-M9: Invite dialog - two tabs (by email, by link)
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

  return (
    <AppModal
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="邀请协作者"
      description="通过邮箱添加成员，或生成可撤销的分享邀请链接。"
      icon={
        <span className="admin-icon-tile admin-icon-tile-brand">
          <UserPlus className="h-4 w-4" />
        </span>
      }
      size="lg"
      bodyClassName="p-0"
    >
      <div className="grid grid-cols-2 gap-1 border-b border-surface-border/70 bg-surface-2/45 p-1">
        <button
          type="button"
          onClick={() => setTab("email")}
          className={cn(
            "inline-flex h-[var(--control-h)] cursor-pointer items-center justify-center gap-2 rounded-md px-3 text-sm font-medium transition-[background-color,color,box-shadow]",
            tab === "email"
              ? "bg-surface text-ink shadow-sm"
              : "text-muted hover:bg-surface/70 hover:text-ink"
          )}
        >
          <UserPlus className="h-3.5 w-3.5" />
          按邮箱邀请
        </button>
        <button
          type="button"
          onClick={() => setTab("link")}
          className={cn(
            "inline-flex h-[var(--control-h)] cursor-pointer items-center justify-center gap-2 rounded-md px-3 text-sm font-medium transition-[background-color,color,box-shadow]",
            tab === "link"
              ? "bg-surface text-ink shadow-sm"
              : "text-muted hover:bg-surface/70 hover:text-ink"
          )}
        >
          <Link2 className="h-3.5 w-3.5" />
          生成分享链接
        </button>
      </div>

      <div className="p-5">
        {tab === "email" ? (
          <form onSubmit={onInviteEmail} className="space-y-4">
            <div className="rounded-lg border border-surface-border/70 bg-surface-2/45 px-3 py-2 text-xs leading-5 text-muted">
              被邀请者必须先在 Agenora 注册一个账号，再用该邮箱邀请。
            </div>
            <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_12rem]">
              <label className="space-y-1.5 text-xs font-medium text-muted">
                <span>邮箱地址</span>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="bob@example.com"
                  className={inviteInputClass}
                />
              </label>
              <label className="space-y-1.5 text-xs font-medium text-muted">
                <span>角色</span>
                <Select
                  value={emailRole}
                  onChange={(e) => setEmailRole(e.target.value as MemberRole)}
                  options={[
                    { value: "editor", label: `${formatKbRole("editor")}（读+写文档）` },
                    { value: "viewer", label: formatKbRole("viewer") },
                  ]}
                  className="h-[var(--control-h)] w-full admin-select-trigger"
                />
              </label>
            </div>
            <Button
              type="submit"
              disabled={emailBusy || !email.trim()}
              className="w-full"
            >
              {emailBusy ? "邀请中..." : "发送邀请"}
            </Button>
          </form>
        ) : (
          <div className="space-y-5">
            <div className="grid gap-3 rounded-lg border border-surface-border/70 bg-surface-2/35 p-4">
              <label className="space-y-1.5 text-xs font-medium text-muted">
                <span>角色</span>
                <Select
                  value={linkRole}
                  onChange={(e) => setLinkRole(e.target.value as MemberRole)}
                  options={[
                    { value: "viewer", label: formatKbRole("viewer") },
                    { value: "editor", label: `${formatKbRole("editor")}（读+写）` },
                  ]}
                  className="h-[var(--control-h)] w-full admin-select-trigger"
                />
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-1.5 text-xs font-medium text-muted">
                  <span>有效期（小时）</span>
                  <input
                    type="number"
                    min="0"
                    value={linkExpiresHours}
                    onChange={(e) => setLinkExpiresHours(e.target.value)}
                    placeholder="留空 = 永不过期"
                    className={inviteInputClass}
                  />
                </label>
                <label className="space-y-1.5 text-xs font-medium text-muted">
                  <span>最大使用次数</span>
                  <input
                    type="number"
                    min="1"
                    value={linkMaxUses}
                    onChange={(e) => setLinkMaxUses(e.target.value)}
                    placeholder="留空 = 不限"
                    className={inviteInputClass}
                  />
                </label>
              </div>
              <Button
                onClick={onCreateLink}
                disabled={linkBusy}
                className="w-full"
                type="button"
              >
                {linkBusy ? "生成中..." : "生成新链接"}
              </Button>
            </div>

            {invitations.length > 0 && (
              <div className="border-t border-surface-border/70 pt-4">
                <div className="mb-2 text-xs font-medium text-muted">现有链接</div>
                <ul className="space-y-2">
                  {invitations.map((inv) => (
                    <li
                      key={inv.id}
                      className={cn(
                        "rounded-lg border border-surface-border/75 bg-surface px-3 py-2.5 text-xs shadow-sm transition",
                        inv.revoked && "opacity-55"
                      )}
                    >
                      <div className="flex items-center gap-2">
                        <span className="chip chip-brand">{formatKbRole(inv.role)}</span>
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
                        {inv.revoked && <span className="text-danger">已撤销</span>}
                        <div className="flex-1" />
                        {!inv.revoked && (
                          <>
                            <button
                              onClick={() => copy(buildUrl(inv.id))}
                              className="inline-flex size-8 cursor-pointer items-center justify-center rounded-lg border border-transparent text-muted transition hover:border-brand/20 hover:bg-brand/10 hover:text-brand"
                              title="复制链接"
                              aria-label="复制邀请链接"
                              type="button"
                            >
                              <Copy className="h-3.5 w-3.5" />
                            </button>
                            <button
                              onClick={() => onRevoke(inv.id)}
                              className="inline-flex size-8 cursor-pointer items-center justify-center rounded-lg border border-transparent text-muted transition hover:border-danger/20 hover:bg-danger/10 hover:text-danger"
                              title="撤销"
                              aria-label="撤销邀请链接"
                              type="button"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </>
                        )}
                      </div>
                      {!inv.revoked && (
                        <div className="mt-2 break-all rounded-md border border-surface-border/60 bg-surface-2/55 px-2 py-1.5 font-mono text-[11px] leading-5 text-muted">
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
    </AppModal>
  );
}

const inviteInputClass =
  "admin-input";
