"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Globe2, Loader2 } from "lucide-react";

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
      <div className="px-5 py-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3">
            <span className="admin-icon-tile admin-icon-tile-muted size-9 shrink-0" aria-hidden>
              <Globe2 className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <p className="text-xs font-semibold text-brand">检索策略</p>
              <h2 id="kb-retrieval-preferences-heading" className="mt-1 text-balance text-base font-semibold">网络检索兜底</h2>
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
        <p className="mt-4 text-pretty text-sm leading-6 text-muted">
          当知识库没有命中相关内容时，最多补充一次网络检索，并在回答中区分来源。
        </p>
      </div>
      <footer className="flex min-h-[var(--control-h)] items-center justify-between gap-3 border-t border-surface-border/70 bg-surface-2/25 px-5 py-3">
        {dirty ? (
          <span className="text-sm text-muted">策略已变更，保存后影响后续知识库对话。</span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-sm text-muted">
            <CheckCircle2 className="h-4 w-4 text-success" aria-hidden />
            当前策略已保存
          </span>
        )}
        {(dirty || saving) && (
          <Button type="button" size="sm" onClick={onSave} disabled={saving}>
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {saving ? "正在保存" : "保存"}
          </Button>
        )}
      </footer>
    </section>
  );
}
