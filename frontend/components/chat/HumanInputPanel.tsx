"use client";

import { Check, CircleAlert, LoaderCircle, PackageCheck, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { cn } from "@/lib/cn";

export type RefundOrderOption = {
  orderId: string;
  productName: string;
  productUrl?: string;
  imageUrl?: string;
  status?: string;
  statusLabel?: string;
  refundableMinor?: number;
  currency?: string;
  refundTo?: string;
};

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
  refundTo?: string;
  productName?: string;
  productUrl?: string;
  orderStatusLabel?: string;
  orderOptions?: RefundOrderOption[];
};

const FIELD_COPY: Record<string, { label: string; placeholder: string }> = {
  order_id: { label: "订单", placeholder: "请选择要退款的订单" },
  refund_reason: { label: "退款原因", placeholder: "补充说明（可选）" },
  refund_confirmation: { label: "最终确认", placeholder: "" },
};

const REFUND_REASONS = ["不再需要", "重复购买", "商品与描述不符", "商品质量问题", "其他原因"];

function formatAmount(amountMinor?: number, currency?: string): string | null {
  if (typeof amountMinor !== "number") return null;
  const unit = currency === "CNY" ? "¥" : currency ? `${currency} ` : "";
  return `${unit}${(amountMinor / 100).toFixed(2)}`;
}

function stepFor(slot: string): number {
  if (slot === "order_id") return 1;
  if (slot === "refund_reason") return 2;
  return 3;
}

function composeReason(preset: string, details: string): string {
  const trimmed = details.trim();
  if (!preset) return trimmed;
  if (!trimmed || trimmed === preset) return preset;
  return `${preset}：${trimmed}`;
}

function Stepper({ step }: { step: number }) {
  return (
    <ol className="grid grid-cols-3 gap-2 text-xs" aria-label={`退款流程，第 ${step} 步，共 3 步`}>
      {["选择订单", "填写原因", "确认执行"].map((label, index) => {
        const number = index + 1;
        const active = number === step;
        const complete = number < step;
        return (
          <li key={label} className={cn("flex items-center gap-2", !active && !complete && "text-muted")}>
            <span
              className={cn(
                "inline-grid size-5 shrink-0 place-items-center rounded-full text-[11px] font-semibold",
                active && "bg-brand text-white",
                complete && "bg-brand/12 text-brand",
                !active && !complete && "bg-surface text-muted"
              )}
            >
              {complete ? <Check className="size-3" aria-hidden="true" /> : number}
            </span>
            <span className={cn("truncate", active && "font-semibold text-ink")}>{label}</span>
          </li>
        );
      })}
    </ol>
  );
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
  onSubmit: (value?: string) => void;
}) {
  const slot = request.slot ?? "";
  const field = FIELD_COPY[slot] ?? { label: "需要补充的信息", placeholder: "请输入继续处理所需的信息" };
  const step = stepFor(slot);
  const isConfirmation = slot === "refund_confirmation";
  const isReason = slot === "refund_reason";
  const isOrderSelection = slot === "order_id";
  const isProcessing = request.phase === "processing";
  const amount = formatAmount(request.amountMinor, request.currency);
  const selectedOrder = useMemo(
    () => request.orderOptions?.find((option) => option.orderId === value),
    [request.orderOptions, value]
  );
  const [reasonPreset, setReasonPreset] = useState("");
  const [reasonDetails, setReasonDetails] = useState("");
  const reasonValue = composeReason(reasonPreset, reasonDetails);
  const canSubmit = isProcessing
    ? false
    : isConfirmation
      ? Boolean(request.confirmationPhrase)
      : isOrderSelection
        ? Boolean(selectedOrder)
        : isReason
          ? Boolean(reasonPreset) && (reasonPreset !== "其他原因" || Boolean(reasonDetails.trim()))
          : value.trim().length > 0;

  const selectReason = (preset: string) => {
    setReasonPreset(preset);
    onChange(composeReason(preset, reasonDetails));
  };

  const updateReasonDetails = (details: string) => {
    setReasonDetails(details);
    onChange(composeReason(reasonPreset, details));
  };

  const submit = () => {
    if (!canSubmit || busy) return;
    onSubmit(isConfirmation ? request.confirmationPhrase : isReason ? reasonValue : value);
  };

  return (
    <section
      aria-label="退款人工介入流程"
      className={cn(
        "kf-human-input-panel mx-auto w-full max-w-[860px] rounded-[var(--radius-composer)] border p-4 sm:p-5",
        isConfirmation && "kf-human-input-panel-confirmation"
      )}
      data-kf-region="human-input"
    >
      <Stepper step={step} />

      <div className="mt-5 flex items-start gap-3">
        <span
          className={cn(
            "mt-0.5 inline-grid size-9 shrink-0 place-items-center rounded-full",
            isConfirmation ? "bg-amber-500/12 text-amber-700 dark:text-amber-300" : "bg-brand/10 text-brand"
          )}
          aria-hidden="true"
        >
          {isConfirmation ? <ShieldCheck className="size-[18px]" /> : isOrderSelection ? <PackageCheck className="size-[18px]" /> : <CircleAlert className="size-[18px]" />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-base font-semibold text-ink">
            {isProcessing ? "退款正在执行" : isConfirmation ? "确认并执行退款" : isOrderSelection ? "选择要退款的订单" : "说明退款原因"}
          </p>
          <p className="mt-1 text-sm leading-6 text-muted">
            {isProcessing ? "退款确认已提交，正在处理。请勿刷新后重复确认。" : request.prompt}
          </p>
        </div>
      </div>

      {isOrderSelection ? (
        request.orderOptions?.length ? (
          <fieldset className="mt-5">
            <legend className="sr-only">选择要退款的订单</legend>
            <div className="max-h-72 space-y-2 overflow-y-auto pr-1" role="radiogroup" aria-label="可退款订单">
              {request.orderOptions.map((option) => {
                const selected = option.orderId === value;
                return (
                  <button
                    key={option.orderId}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    disabled={busy}
                    onClick={() => onChange(option.orderId)}
                    className={cn(
                      "w-full rounded-xl border px-3 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30 disabled:cursor-not-allowed disabled:opacity-60",
                      selected ? "border-brand bg-brand/[0.06]" : "border-surface-border bg-surface hover:border-brand/40"
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-ink">{option.productName}</p>
                        <p className="mt-1 text-xs text-muted">{option.orderId}</p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-sm font-semibold text-ink">{formatAmount(option.refundableMinor, option.currency) ?? "—"}</p>
                        <p className="mt-1 text-xs text-muted">{option.statusLabel ?? option.status ?? "订单状态"}</p>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </fieldset>
        ) : (
          <div className="mt-5 rounded-xl border border-surface-border bg-surface px-3 py-3 text-sm text-muted">
            当前没有可退款订单，请稍后重试。
          </div>
        )
      ) : null}

      {isReason ? (
        <div className="mt-5">
          <p className="text-sm font-medium text-ink">常用原因 <span className="text-danger">*</span></p>
          <div className="mt-2 flex flex-wrap gap-2" aria-label="常用退款原因">
            {REFUND_REASONS.map((reason) => (
              <button
                key={reason}
                type="button"
                disabled={busy}
                onClick={() => selectReason(reason)}
                aria-pressed={reasonPreset === reason}
                className={cn(
                  "rounded-full border px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30 disabled:cursor-not-allowed disabled:opacity-60",
                  reasonPreset === reason ? "border-brand bg-brand/[0.08] text-brand" : "border-surface-border bg-surface text-muted hover:text-ink"
                )}
              >
                {reason}
              </button>
            ))}
          </div>
          <label className="mt-4 block" htmlFor="refund-reason-details">
            <span className="text-sm font-medium text-ink">
              补充说明{reasonPreset === "其他原因" ? <span className="text-danger"> *</span> : "（可选）"}
            </span>
            <textarea
              id="refund-reason-details"
              value={reasonDetails}
              onChange={(event) => updateReasonDetails(event.target.value)}
              placeholder={field.placeholder}
              disabled={busy}
              rows={3}
              className="mt-2 block w-full resize-none rounded-xl border border-surface-border bg-surface px-3 py-2.5 text-sm leading-6 text-ink outline-none placeholder:text-muted focus:border-brand focus:ring-2 focus:ring-brand/15 disabled:cursor-not-allowed disabled:opacity-70"
            />
          </label>
        </div>
      ) : null}

      {!isOrderSelection && !isReason && !isConfirmation && !isProcessing ? (
        <label className="mt-5 block" htmlFor="human-input-value">
          <span className="text-sm font-medium text-ink">{field.label}</span>
          <input
            id="human-input-value"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder={field.placeholder}
            disabled={busy}
            autoComplete="off"
            className="mt-2 block h-11 w-full rounded-xl border border-surface-border bg-surface px-3 text-sm text-ink outline-none placeholder:text-muted focus:border-brand focus:ring-2 focus:ring-brand/15 disabled:cursor-not-allowed disabled:opacity-70"
          />
        </label>
      ) : null}

      {isConfirmation ? (
        <div className="mt-5 rounded-xl border border-amber-500/25 bg-amber-500/[0.07] p-4">
          <p className="text-sm font-semibold text-ink">请核对本次退款</p>
          <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            <div><dt className="text-muted">订单</dt><dd className="mt-0.5 break-all font-medium text-ink">{request.orderId ?? "—"}</dd></div>
            <div><dt className="text-muted">商品</dt><dd className="mt-0.5 font-medium text-ink">{request.productName ?? "—"}</dd></div>
            <div><dt className="text-muted">退款金额</dt><dd className="mt-0.5 font-medium text-ink">{amount ?? "—"}</dd></div>
            <div><dt className="text-muted">退款去向</dt><dd className="mt-0.5 font-medium text-ink">{request.refundTo ?? "原支付渠道"}</dd></div>
            <div><dt className="text-muted">订单状态</dt><dd className="mt-0.5 font-medium text-ink">{request.orderStatusLabel ?? "—"}</dd></div>
            <div><dt className="text-muted">确认单</dt><dd className="mt-0.5 break-all font-medium text-ink">{request.approvalId ?? "—"}</dd></div>
          </dl>
          <p className="mt-4 text-xs leading-5 text-amber-900/80 dark:text-amber-200">
            点击“确认并执行退款”后将向订单服务发起不可逆的退款请求。提交后会锁定本次操作，直至服务端返回结果。
          </p>
        </div>
      ) : null}

      {isProcessing ? (
        <div className="mt-5 flex items-center gap-2 rounded-xl border border-surface-border bg-surface px-3 py-3 text-sm text-muted">
          <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />
          正在等待服务端完成并同步结果…
        </div>
      ) : null}

      <div className="mt-5 flex items-center justify-between gap-3 border-t border-surface-border pt-4">
        <p className="text-xs text-muted">
          {isProcessing ? "即使刷新页面，服务端也会继续处理并保存结果。" : step === 3 ? "提交后不可重复执行。" : `第 ${step} 步，共 3 步`}
        </p>
        {!isProcessing ? (
          <button
            className={cn(
              "kf-human-input-submit kf-press inline-flex h-10 shrink-0 items-center gap-1.5 rounded-lg px-4 text-sm font-medium text-white",
              isConfirmation && "kf-human-input-submit-confirmation"
            )}
            disabled={!canSubmit || busy}
            onClick={submit}
            type="button"
          >
            {busy ? <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" /> : <Check className="size-4" />}
            {busy ? "正在继续" : isConfirmation ? "确认并执行退款" : step === 1 ? "继续填写原因" : "生成退款确认单"}
          </button>
        ) : null}
      </div>
    </section>
  );
}
