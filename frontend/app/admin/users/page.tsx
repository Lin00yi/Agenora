"use client";

import { useEffect, useState } from "react";
import {
  ShieldCheck,
  ShieldOff,
  Ban,
  CheckCircle2,
  KeyRound,
  RefreshCw,
  Trash2,
  Users,
} from "lucide-react";
import { toast } from "@/lib/toast";

import { getUser as getCachedUser } from "@/lib/auth";
import {
  listUsers,
  updateUser,
  resetUserPassword,
  deleteUser,
  type AdminUser,
} from "@/lib/admin-api";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/button";
import { Pagination } from "@/components/ui/pagination";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import AppModal from "@/components/AppModal";
import { PageSkeleton, StateView } from "@/components/ui/state-view";

const PAGE_SIZE = 50;

/**
 * /admin/users — user management table with inline actions (06-01).
 *
 * Actions (ban/unban, grant/revoke admin, reset password, delete) call the
 * admin API; the backend enforces self-protection + last-admin invariants
 * (400 / 409) which we surface verbatim via toast.
 */
export default function AdminUsersPage() {
  return <UsersTable />;
}

function UsersTable() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [initialLoading, setInitialLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  // Dialog state
  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
  const [resetPwd, setResetPwd] = useState("");
  const [resetBusy, setResetBusy] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const me = getCachedUser();

  const load = (nextOffset = offset) => {
    setRefreshing(true);
    listUsers(PAGE_SIZE, nextOffset)
      .then((r) => {
        setUsers(r.users);
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

  const patch = async (u: AdminUser, body: { is_active?: boolean; is_admin?: boolean }) => {
    setBusyId(u.id);
    try {
      const updated = await updateUser(u.id, body);
      setUsers((prev) => prev.map((x) => (x.id === u.id ? updated : x)));
      toast.success("已更新");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  const confirmReset = async () => {
    if (!resetTarget) return;
    if (resetPwd.length < 8) {
      toast.error("新密码至少 8 位");
      return;
    }
    setResetBusy(true);
    try {
      await resetUserPassword(resetTarget.id, resetPwd);
      toast.success(`已为 ${resetTarget.email} 重置密码`);
      setResetTarget(null);
      setResetPwd("");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setResetBusy(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleteBusy(true);
    try {
      await deleteUser(deleteTarget.id);
      toast.success(`已删除：${deleteTarget.email}`);
      setDeleteTarget(null);
      // Reload current page (total shifts).
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

  if (users.length === 0) {
    return <StateView title="还没有用户" description="新用户注册后会显示在这里，并可进行权限管理。" />;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 border-b border-surface-border/70 pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold tracking-[0.16em] text-brand">
            用户目录
          </p>
          <h2 className="mt-2 flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <Users className="h-5 w-5 text-brand" />
            用户管理
          </h2>
          <p className="mt-2 text-sm text-muted">共 {total} 个用户，可管理状态、角色和密码。</p>
        </div>
        <Button type="button" variant="outline" disabled={refreshing} onClick={() => load(offset)}>
          <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
          刷新
        </Button>
      </div>

      <div className="admin-panel overflow-x-auto">
        <table className="admin-table admin-table-users">
          <thead>
            <tr>
              <th className="w-[28%]">用户</th>
              <th className="w-[14%]">注册时间</th>
              <th className="w-[10%]">状态</th>
              <th className="w-[8%] text-right">KB</th>
              <th className="w-[8%] text-right">会话</th>
              <th className="w-[12%]">LLM</th>
              <th className="w-[20%] text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const isSelf = me?.id === u.id;
              const busy = busyId === u.id;
              return (
                <tr key={u.id}>
                  <td className="max-w-0">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="admin-icon-tile admin-icon-tile-brand shrink-0 rounded-md text-xs font-semibold">
                        {(u.display_name?.trim()?.[0] || u.email[0] || "?").toUpperCase()}
                      </span>
                      <span className="truncate font-medium">
                        {u.display_name?.trim() || u.email}
                      </span>
                      {u.is_admin && (
                        <span className="chip chip-brand shrink-0">
                          管理员
                        </span>
                      )}
                      {isSelf && (
                        <span className="chip chip-muted shrink-0">
                          你
                        </span>
                      )}
                    </div>
                    <div className="truncate text-xs text-muted" title={u.email}>{u.email}</div>
                  </td>
                  <td className="text-xs text-muted">
                    {u.created_at
                      ? new Date(u.created_at).toLocaleDateString("zh-CN")
                      : "—"}
                  </td>
                  <td>
                    {u.is_active ? (
                      <span className="chip chip-success">
                        活跃
                      </span>
                    ) : (
                      <span className="chip chip-danger">
                        已封禁
                      </span>
                    )}
                  </td>
                  <td className="text-right tabular-nums">{u.kb_count}</td>
                  <td className="text-right tabular-nums">
                    {u.conversation_count}
                  </td>
                  <td>
                    {u.byok_configured ? (
                      <span className="chip chip-success">已配置</span>
                    ) : (
                      <span className="text-xs text-muted">—</span>
                    )}
                  </td>
                  <td>
                    <div className="flex items-center justify-end gap-1">
                      <IconBtn
                        title={u.is_active ? "封禁" : "解封"}
                        disabled={busy || isSelf}
                        onClick={() => patch(u, { is_active: !u.is_active })}
                        danger={u.is_active}
                      >
                        {u.is_active ? (
                          <Ban className="h-4 w-4" />
                        ) : (
                          <CheckCircle2 className="h-4 w-4" />
                        )}
                      </IconBtn>
                      <IconBtn
                        title={u.is_admin ? "取消管理员" : "设为管理员"}
                        disabled={busy || isSelf}
                        onClick={() => patch(u, { is_admin: !u.is_admin })}
                      >
                        {u.is_admin ? (
                          <ShieldOff className="h-4 w-4" />
                        ) : (
                          <ShieldCheck className="h-4 w-4" />
                        )}
                      </IconBtn>
                      <IconBtn
                        title="重置密码"
                        disabled={busy}
                        onClick={() => {
                          setResetPwd("");
                          setResetTarget(u);
                        }}
                      >
                        <KeyRound className="h-4 w-4" />
                      </IconBtn>
                      <IconBtn
                        title="删除"
                        disabled={busy || isSelf}
                        danger
                        onClick={() => setDeleteTarget(u)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </IconBtn>
                    </div>
                  </td>
                </tr>
              );
            })}
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

      <AppModal
        open={resetTarget != null}
        onOpenChange={(o) => {
          if (!o && !resetBusy) {
            setResetTarget(null);
            setResetPwd("");
          }
        }}
        title={`为「${resetTarget?.email ?? ""}」重置密码`}
        description="设置一个新密码（至少 8 位）。该用户可立即用新密码登录。"
        size="sm"
        busy={resetBusy}
        footer={
          <>
            <Button
              type="button"
              variant="outline"
              disabled={resetBusy}
              onClick={() => {
                setResetTarget(null);
                setResetPwd("");
              }}
            >
              取消
            </Button>
            <Button
              type="button"
              disabled={resetBusy || resetPwd.length < 8}
              onClick={() => void confirmReset()}
            >
              {resetBusy ? "重置中…" : "重置"}
            </Button>
          </>
        }
      >
        <label className="block space-y-1.5 text-xs font-medium text-muted">
          <span>新密码</span>
          <input
            type="password"
            value={resetPwd}
            onChange={(e) => setResetPwd(e.target.value)}
            placeholder="至少 8 位"
            className="admin-input"
            autoComplete="new-password"
            disabled={resetBusy}
          />
        </label>
      </AppModal>

      {/* Delete confirm dialog */}
      <ConfirmDialog
        open={deleteTarget != null}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title={`删除用户「${deleteTarget?.email ?? ""}」？`}
        description="该用户的所有知识库与会话都会一并清除。该操作不可逆。"
        variant="danger"
        confirmLabel="确认删除"
        onConfirm={confirmDelete}
        busy={deleteBusy}
      />
    </div>
  );
}

function IconBtn({
  title,
  onClick,
  disabled,
  danger,
  children,
}: {
  title: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "admin-icon-action admin-icon-action-lg disabled:opacity-30",
        danger
          ? "admin-icon-action-danger border-danger/20 bg-danger/5 text-danger"
          : "admin-icon-action-surface text-muted"
      )}
    >
      {children}
    </button>
  );
}
