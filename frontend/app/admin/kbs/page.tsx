"use client";

import { useEffect, useState } from "react";
import { BookOpen, Database, Lock, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "@/lib/toast";

import { listKbs, deleteKb, type AdminKb } from "@/lib/admin-api";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/button";
import { Pagination } from "@/components/ui/pagination";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageSkeleton, StateView } from "@/components/ui/state-view";

const PAGE_SIZE = 50;

/**
 * /admin/kbs — cross-user knowledge base management (06-01).
 *
 * System KBs can't be deleted (backend returns 400); we disable the delete
 * button for them and still surface the error if it somehow fires.
 */
export default function AdminKbsPage() {
  return <KbsTable />;
}

function KbsTable() {
  const [kbs, setKbs] = useState<AdminKb[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [initialLoading, setInitialLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState<AdminKb | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const load = (nextOffset = offset) => {
    setRefreshing(true);
    listKbs(PAGE_SIZE, nextOffset)
      .then((r) => {
        setKbs(r.kbs);
        setTotal(r.total);
        setOffset(r.offset);
      })
      .catch((e) => toast.error((e as Error).message))
      .finally(() => {
        setInitialLoading(false);
        setRefreshing(false);
      });
  };

  useEffect(() => {
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleteBusy(true);
    try {
      await deleteKb(deleteTarget.id);
      toast.success(`已删除：${deleteTarget.name}`);
      setDeleteTarget(null);
      load();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setDeleteBusy(false);
    }
  };

  if (initialLoading) {
    return <PageSkeleton />;
  }

  if (kbs.length === 0) {
    return <StateView title="还没有知识库" description="创建知识库后，这里会展示所有用户的资料库。" />;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 border-b border-surface-border/70 pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold tracking-[0.16em] text-brand">
            知识库清单
          </p>
          <h2 className="mt-2 flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <Database className="h-5 w-5 text-brand" />
            全局知识库
          </h2>
          <p className="mt-2 text-sm text-muted">共 {total} 个知识库，包含用户资料库和系统示例库。</p>
        </div>
        <Button type="button" variant="outline" disabled={refreshing} onClick={() => load(offset)}>
          <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
          刷新
        </Button>
      </div>

      <div className="admin-panel overflow-x-auto">
        <table className="admin-table admin-table-kbs">
          <thead>
            <tr>
              <th className="w-[32%]">名称</th>
              <th className="w-[22%]">所有者</th>
              <th className="w-[8%] text-right">文档</th>
              <th className="w-[8%] text-right">分块</th>
              <th className="w-[8%] text-right">成员</th>
              <th className="w-[14%]">创建时间</th>
              <th className="w-[8%] text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {kbs.map((kb) => (
              <tr key={kb.id}>
                <td className="max-w-0">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="admin-icon-tile admin-icon-tile-muted shrink-0 rounded-md">
                      {kb.is_system ? (
                        <Lock className="h-4 w-4 text-warning" />
                      ) : (
                        <BookOpen className="h-4 w-4 text-brand" />
                      )}
                    </span>
                    <span className="truncate font-medium">{kb.name}</span>
                    {kb.is_system && (
                      <span className="chip chip-warning shrink-0">
                        系统
                      </span>
                    )}
                  </div>
                  {kb.description && (
                    <div className="mt-1 truncate text-xs text-muted" title={kb.description}>
                      {kb.description}
                    </div>
                  )}
                </td>
                <td className="max-w-0 truncate text-xs text-muted" title={kb.owner_email || undefined}>
                  {kb.owner_email || (
                    <span className="italic opacity-60">系统 / 无主</span>
                  )}
                </td>
                <td className="text-right tabular-nums">
                  {kb.documents_count}
                </td>
                <td className="text-right tabular-nums">
                  {kb.chunks_count}
                </td>
                <td className="text-right tabular-nums">
                  {kb.member_count}
                </td>
                <td className="whitespace-nowrap text-xs text-muted">
                  {kb.created_at
                    ? new Date(kb.created_at).toLocaleDateString("zh-CN")
                    : "—"}
                </td>
                <td>
                  <div className="flex items-center justify-end">
                    <button
                      type="button"
                      title={kb.is_system ? "系统 KB 不可删除" : "删除"}
                      aria-label="删除知识库"
                      disabled={kb.is_system}
                      onClick={() => setDeleteTarget(kb)}
                      className={cn(
                        "admin-icon-action admin-icon-action-lg admin-icon-action-danger text-muted/80 disabled:opacity-30",
                        "hover:bg-danger/15"
                      )}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Pagination
        total={total}
        offset={offset}
        pageSize={PAGE_SIZE}
        onOffsetChange={(next) => load(next)}
        disabled={refreshing}
      />

      <ConfirmDialog
        open={deleteTarget != null}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title={`删除知识库「${deleteTarget?.name ?? ""}」？`}
        description="这个 KB 下所有文档和向量都会一并清除。该操作不可逆。"
        variant="danger"
        confirmLabel="确认删除"
        onConfirm={confirmDelete}
        busy={deleteBusy}
      />
    </div>
  );
}
