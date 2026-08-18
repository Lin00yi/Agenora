"use client";

import { use, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Users, Eye, CheckCircle, BookOpen, ShieldCheck } from "lucide-react";
import { toast } from "@/lib/toast";

import Brand, { APP_NAME } from "@/components/Brand";
import { getToken } from "@/lib/auth";
import {
  acceptInvitation,
  formatKbRole,
  peekInvitation,
  type InvitationPreview,
} from "@/lib/kb-api";
import { StateView } from "@/components/ui/state-view";
import { Button } from "@/components/ui/button";

/**
 * v2-M9: invitation landing page.
 *
 * Flow:
 *   1. If not logged in → redirect to /login?next=/invite/{token}
 *   2. If logged in → peekInvitation(token) to show KB name + role
 *   3. User clicks "接受邀请" → acceptInvitation(token) → redirect to /kbs/{kb_id}
 *
 * Error states (404 invalid / 410 expired / 410 exhausted) render a friendly
 * "链接已失效" panel with a back-to-KBs link.
 */
export default function InvitePage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const router = useRouter();

  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [accepting, setAccepting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!getToken()) {
      router.replace(`/login?next=/invite/${token}`);
      return;
    }
    try {
      const p = await peekInvitation(token);
      setPreview(p);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token, router]);

  useEffect(() => {
    void load();
  }, [load]);

  const onAccept = async () => {
    setAccepting(true);
    try {
      const { kb_id } = await acceptInvitation(token);
      toast.success("已加入知识库");
      router.replace(`/kbs/${kb_id}`);
    } catch (e) {
      toast.error((e as Error).message);
      setError((e as Error).message);
      setAccepting(false);
    }
  };

  return (
    <div className="app-page flex min-h-dvh items-center justify-center bg-surface-2/25 px-4 py-10 text-ink">
      <div className="w-full max-w-xl">
        <div className="mb-6 flex flex-col items-center gap-3">
          <Brand size="md" showWordmark={false} />
          <div className="text-center">
            <p className="text-xs font-semibold tracking-[0.16em] text-brand">协作邀请</p>
            <h1 className="mt-2 text-xl font-semibold tracking-tight">{APP_NAME} 知识库邀请</h1>
            <p className="mt-2 text-sm leading-6 text-muted">确认权限后即可加入协作知识库。</p>
          </div>
        </div>

        <div className="overflow-hidden rounded-lg border border-surface-border/80 bg-surface shadow-[0_18px_50px_rgb(15_23_42/0.14)]">
          <div className="border-b border-surface-border/70 bg-surface px-5 py-4 sm:px-6">
            <div className="flex items-center gap-3">
              <span className="admin-icon-tile admin-icon-tile-brand">
                <ShieldCheck className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <div className="text-sm font-semibold">邀请验证</div>
                <div className="mt-0.5 text-xs text-muted">验证知识库、角色和邀请有效期</div>
              </div>
            </div>
          </div>
          <div className="bg-surface px-5 py-6 sm:px-6">
            {loading ? (
              <StateView
                variant="loading"
                title="正在验证邀请"
                description="正在确认知识库和权限信息。"
                className="min-h-56 border-0 bg-surface"
              />
            ) : error ? (
              <StateView
                variant="error"
                title="链接无法使用"
                description={error}
                action={
                  <Button asChild className="min-h-[var(--control-h)] px-4 text-sm">
                    <Link href="/kbs">返回知识库列表</Link>
                  </Button>
                }
                className="min-h-56 border-0 bg-surface shadow-none"
              />
            ) : preview ? (
              <div className="flex flex-col items-center gap-4 py-1 text-center">
                <span className="admin-icon-tile admin-icon-tile-lg admin-icon-tile-brand">
                  <BookOpen className="h-6 w-6" />
                </span>
                <div className="min-w-0">
                  <div className="text-lg font-semibold tracking-tight">
                    邀请你加入「{preview.kb_name}」
                  </div>
                  <p className="mt-2 text-sm leading-6 text-muted">
                    加入后即可在当前账号下访问这个协作知识库。
                  </p>
                </div>

                <div className="flex w-full flex-col gap-3 rounded-lg border border-surface-border/80 bg-surface-2/35 p-4 text-left shadow-sm">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <span className="text-xs font-semibold tracking-wide text-muted">授予角色</span>
                    {preview.role === "editor" ? (
                      <span className="chip chip-info min-h-8">
                        <Users className="h-3.5 w-3.5" />
                        {formatKbRole("editor")}（读 + 写文档）
                      </span>
                    ) : (
                      <span className="chip chip-muted min-h-8">
                        <Eye className="h-3.5 w-3.5" />
                        {formatKbRole("viewer")}
                      </span>
                    )}
                  </div>

                  {(preview.max_uses != null || preview.expires_at) && (
                    <div className="grid gap-2 border-t border-surface-border/70 pt-3 text-xs text-muted sm:grid-cols-2">
                      {preview.max_uses != null && (
                        <div className="rounded-lg border border-surface-border/70 bg-surface px-3 py-2">
                          <div className="font-medium text-ink">使用次数</div>
                          <div className="mt-1 tabular-nums">
                            {preview.uses_count}/{preview.max_uses} 次
                          </div>
                        </div>
                      )}
                      {preview.expires_at && (
                        <div className="rounded-lg border border-surface-border/70 bg-surface px-3 py-2">
                          <div className="font-medium text-ink">有效期</div>
                          <div className="mt-1">{new Date(preview.expires_at).toLocaleString()}</div>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                <div className="mt-2 flex w-full flex-col-reverse gap-2 sm:flex-row">
                  <Button asChild variant="outline" className="min-h-[44px] flex-1 justify-center px-4 text-sm">
                    <Link href="/kbs">取消</Link>
                  </Button>
                  <Button
                    onClick={onAccept}
                    disabled={accepting}
                    className="min-h-[44px] flex-1 justify-center px-4 text-sm"
                    type="button"
                  >
                    <CheckCircle className="h-4 w-4" />
                    {accepting ? "处理中…" : "接受邀请"}
                  </Button>
                </div>
              </div>
            ) : null}
          </div>
          <div className="border-t border-surface-border/70 bg-surface-2/35 px-5 py-3 text-center text-xs text-muted sm:px-6">
            只会授予邀请中声明的知识库权限。
          </div>
        </div>
      </div>
    </div>
  );
}
