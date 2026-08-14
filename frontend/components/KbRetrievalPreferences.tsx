"use client";

import { useEffect, useState } from "react";
import { Globe2, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { saveKbOptions, type MyKbOptions } from "@/lib/settings-api";
import { toast } from "@/lib/toast";

export function KbRetrievalPreferences({
  initial,
  onChanged,
}: {
  initial?: MyKbOptions;
  onChanged?: (next: MyKbOptions) => void | Promise<void>;
}) {
  const [webEnabled, setWebEnabled] = useState(initial?.kb_web_search_enabled ?? false);
  const [saving, setSaving] = useState(false);
  const dirty = webEnabled !== (initial?.kb_web_search_enabled ?? false);

  useEffect(() => setWebEnabled(initial?.kb_web_search_enabled ?? false), [initial?.kb_web_search_enabled]);

  const onSave = async () => {
    setSaving(true);
    try {
      const next = await saveKbOptions({ kb_web_search_enabled: webEnabled });
      await onChanged?.(next.kb_options);
      toast.success("检索策略已保存");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存检索策略失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section aria-labelledby="kb-retrieval-preferences-heading" className="admin-panel">
      <div className="flex flex-col gap-5 px-5 py-5 sm:flex-row sm:items-start sm:justify-between sm:px-6">
        <div className="flex min-w-0 items-start gap-3">
          <span className="admin-icon-tile admin-icon-tile-muted" aria-hidden>
            <Globe2 className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-brand">检索策略</p>
            <h2 id="kb-retrieval-preferences-heading" className="mt-1 text-balance text-base font-semibold">知识库回答不足时允许网络检索</h2>
            <p className="mt-1 max-w-2xl text-pretty text-sm leading-6 text-muted">
              此为你的知识库会话默认策略。开启后，Agent 会优先检索文档；仅在没有相关分块时最多补充一次网络搜索，并在回答中区分来源。
            </p>
          </div>
        </div>
        <Switch
          checked={webEnabled}
          onCheckedChange={setWebEnabled}
          disabled={saving}
          aria-label="允许知识库对话调用网络搜索作为兜底"
          className="shrink-0"
        />
      </div>
      <footer className="flex flex-col gap-3 border-t border-surface-border/70 bg-surface-2/35 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <span className="text-sm text-muted">{dirty ? "策略已变更，保存后影响后续知识库对话。" : "当前策略已保存。"}</span>
        <Button type="button" variant="outline" onClick={onSave} disabled={saving || !dirty}>
          {saving && <Loader2 className="h-4 w-4 animate-spin" />}
          {saving ? "正在保存" : "保存检索策略"}
        </Button>
      </footer>
    </section>
  );
}
