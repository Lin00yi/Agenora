"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { KnowledgeBaseContextHeader } from "@/components/kb/AdminPageShell";
import { StateView } from "@/components/ui/state-view";
import { getToken } from "@/lib/auth";
import { getKb, type KBDetail } from "@/lib/kb-api";
import { toast } from "@/lib/toast";

export function KbWorkspaceShell({ kbId, children }: { kbId: string; children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [kb, setKb] = useState<KBDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    let active = true;
    setLoading(true);
    getKb(kbId)
      .then((nextKb) => {
        if (active) setKb(nextKb);
      })
      .catch((error: Error) => {
        if (active) toast.error(error.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [kbId, router]);

  if (loading) {
    return <StateView variant="loading" title="正在加载知识库工作区" description="正在准备文档与图谱管理界面。" className="m-8" />;
  }
  if (!kb) {
    return <StateView variant="error" title="无法加载知识库" description="请返回知识库列表后重试。" className="m-8" />;
  }

  return (
    <div className="app-page admin-page min-h-dvh text-ink">
      <KnowledgeBaseContextHeader
        breadcrumbs={[{ label: "知识库管理", href: "/kbs" }]}
        title={pathname.includes("/documents/") ? "文档" : undefined}
        context={{ label: kb.name, href: `/kbs/${kbId}` }}
      />
      <main className="app-page-content mx-auto px-4 py-7 sm:px-6 sm:py-10">{children}</main>
    </div>
  );
}
