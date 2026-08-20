"use client";

import { Check, CircleAlert, LoaderCircle, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/cn";

export type HumanInputRequest = {
  phase?: "awaiting" | "processing";
  slot?: string;
  requiredSlots?: string[];
  prompt: string;
  approvalId?: string;
  confirmationPhrase?: string;
  orderId?: string;
  amountMinor?: number;
  currency?: string;
};

const FIELD_COPY: Record<string, { label: string; placeholder: string }> = {
  order_id: { label: "订单号", placeholder: "例如：ORD-xxxxxxxx-xxxx" },
  refund_reason: { label: "退款原因", placeholder: "请简要说明退款原因" },
  refund_confirmation: { label: "退款确认", placeholder: "请输入上方的精确确认语" },
};

function formatAmount(amountMinor?: number, currency?: string): string | null {
  if (typeof amountMinor !== "number") return null;
  const unit = currency === "CNY" ? "¥" : currency ? `${currency} ` : "";
  return `${unit}${(amountMinor / 100).toFixed(2)}`;
}

export function HumanInputPanel({
  request,
  value,
  busy,
  onChange,
  onSubmit,
}: {
  request: HumanInputRequest;
  value: string;
  busy: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
}) {
  const slot = request.slot ?? "";
  const field = FIELD_COPY[slot] ?? {
    label: "需要补充的信息",
    placeholder: "请输入继续处理所需的信息",
  };
  const isConfirmation = slot === "refund_confirmation";
  const isProcessing = request.phase === "processing";
  const amount = formatAmount(request.amountMinor, request.currency);
  const canSubmit = value.trim().length > 0 && !busy && !isProcessing;

  return (
    <section
      aria-label="需要人工介入"
      className={cn(
        "kf-human-input-panel mx-auto w-full max-w-[860px] rounded-[var(--radius-composer)] border p-3 sm:p-4",
        isConfirmation && "kf-human-input-panel-confirmation"
      )}
      data-kf-region="human-input"
    >
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "mt-0.5 inline-grid size-8 shrink-0 place-items-center rounded-full",
            isConfirmation ? "bg-amber-500/12 text-amber-700 dark:text-amber-300" : "bg-brand/10 text-brand"
          )}
          aria-hidden="true"
        >
          {isConfirmation ? <ShieldCheck className="size-4" /> : <CircleAlert className="size-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-ink">
            {isProcessing ? "退款正在执行" : isConfirmation ? "请确认退款操作" : `请补充${field.label}`}
          </p>
          <p className="mt-1 text-sm leading-6 text-muted">
            {isProcessing ? "退款确认已提交，正在处理。请勿重复发送或再次确认。" : request.prompt}
          </p>
        </div>
      </div>

      {isConfirmation ? (
        <div className="mt-3 rounded-xl border border-amber-500/20 bg-amber-500/[0.07] px-3 py-2.5 text-sm text-ink">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
            {request.orderId ? <span>订单：{request.orderId}</span> : null}
            {amount ? <span>退款金额：{amount}</span> : null}
            {request.approvalId ? <span>确认单：{request.approvalId}</span> : null}
          </div>
          {request.confirmationPhrase && !isProcessing ? (
            <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
              <code className="min-w-0 flex-1 overflow-x-auto rounded-lg bg-surface px-2.5 py-2 text-xs text-ink">
                {request.confirmationPhrase}
              </code>
              <button
                className="kf-control kf-press inline-flex h-8 shrink-0 items-center justify-center rounded-lg border px-3 text-xs font-medium"
                onClick={() => onChange(request.confirmationPhrase ?? "")}
                type="button"
              >
                填入确认语
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {isProcessing ? (
        <div className="mt-4 flex items-center gap-2 rounded-xl border border-surface-border bg-surface px-3 py-3 text-sm text-muted">
          <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />
          正在等待服务端完成并同步结果…
        </div>
      ) : (
        <label className="mt-4 block" htmlFor="human-input-value">
          <span className="sr-only">{field.label}</span>
          {slot === "refund_reason" ? (
          <textarea
            id="human-input-value"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (busy || event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
              event.preventDefault();
              onSubmit();
            }}
            placeholder={field.placeholder}
            disabled={busy}
            rows={2}
            className="block w-full resize-none rounded-xl border border-surface-border bg-surface px-3 py-2.5 text-sm leading-6 text-ink outline-none placeholder:text-muted focus:border-brand focus:ring-2 focus:ring-brand/15 disabled:cursor-not-allowed disabled:opacity-70"
          />
          ) : (
          <input
            id="human-input-value"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (busy || event.key !== "Enter" || event.nativeEvent.isComposing) return;
              event.preventDefault();
              onSubmit();
            }}
            placeholder={field.placeholder}
            disabled={busy}
            autoComplete="off"
            className="block h-11 w-full rounded-xl border border-surface-border bg-surface px-3 text-sm text-ink outline-none placeholder:text-muted focus:border-brand focus:ring-2 focus:ring-brand/15 disabled:cursor-not-allowed disabled:opacity-70"
          />
          )}
        </label>
      )}

      <div className="mt-3 flex items-center justify-between gap-3">
        <p className="text-xs text-muted">
          {isProcessing ? "即使刷新页面，服务端也会继续处理并保存结果。" : "会话已暂停，提交后会从当前工作流继续。"}
        </p>
        {!isProcessing ? <button
          className={cn(
            "kf-human-input-submit kf-press inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm font-medium text-white",
            isConfirmation && "kf-human-input-submit-confirmation"
          )}
          disabled={!canSubmit}
          onClick={onSubmit}
          type="button"
        >
          {busy ? <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" /> : <Check className="size-4" />}
          {busy ? "正在继续" : isConfirmation ? "确认并继续" : "提交"}
        </button> : null}
      </div>
    </section>
  );
}
