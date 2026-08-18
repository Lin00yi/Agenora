"use client";

import Link from "next/link";
import type { RefObject } from "react";
import {
  ArrowUp,
  Database,
  LockKeyhole,
  Paperclip,
  Square,
} from "lucide-react";
import ModelSelect from "@/components/Select";
import { ProviderLogo } from "@/components/ProviderLogo";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { ConversationContextStatus } from "@/lib/conversations-api";
import type { KB } from "@/lib/kb-api";
import type { LLMConnection, LLMModelProfile } from "@/lib/settings-api";
import type { MemoryTrace } from "@/lib/sseClient";
import { cn } from "@/lib/cn";
import type { LlmSource } from "./types";
import { formatContextUsagePercent, resolveContextUsagePercent } from "./utils";

const MANAGE_MODELS_VALUE = "__manage_models__";
const modelIdCollator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });

export function Composer({
  value,
  textareaRef,
  busy,
  currentKbId,
  kbs,
  currentModel,
  currentProfileId,
  modelOptions,
  modelProfiles = [],
  modelConnections = [],
  modelLabels = {},
  llmSource,
  contextStatus,
  contextStatusLoading,
  promptTrace,
  kbLocked,
  onChange,
  onSubmit,
  onStop,
  onSelectKb,
  onModelChange,
  onManageModels,
  centered = false,
}: {
  value: string;
  textareaRef: React.RefObject<HTMLTextAreaElement>;
  busy: boolean;
  currentKbId: string | null;
  kbs: KB[];
  currentModel: string | null;
  currentProfileId?: string | null;
  modelOptions: string[];
  modelProfiles?: LLMModelProfile[];
  modelConnections?: LLMConnection[];
  modelLabels?: Record<string, string>;
  llmSource: LlmSource;
  contextStatus: ConversationContextStatus | null;
  contextStatusLoading: boolean;
  /** Safe token counts for the latest completed provider request. */
  promptTrace?: MemoryTrace["prompt"] | null;
  kbLocked: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  onSelectKb: (id: string | null) => void;
  onModelChange: (model: string | null) => void;
  onManageModels: () => void;
  centered?: boolean;
}) {
  const profileOptions = [...modelProfiles]
    .sort((left, right) => modelIdCollator.compare(left.model_id, right.model_id) || left.id.localeCompare(right.id))
    .map((profile) => ({
      value: profile.id,
      label: modelLabels[profile.id] ?? profile.model_id,
      icon: <ProviderLogo connection={modelConnections.find((connection) => connection.id === profile.connection_id)} catalog={profile.catalog} />,
    }));
  const visibleModelOptions =
    profileOptions.length > 0
      ? profileOptions
      : (currentModel && !modelOptions.includes(currentModel) ? [currentModel, ...modelOptions] : modelOptions)
          .slice()
          .sort(modelIdCollator.compare)
          .map((model) => ({ value: model, label: modelLabels[model] ? `${modelLabels[model]} · ${model}` : model, icon: <ProviderLogo /> }));
  const selectableModelOptions = [
    ...visibleModelOptions,
    { value: MANAGE_MODELS_VALUE, label: "管理模型配置" },
  ];

  return (
    <div
      className={cn("kf-composer", centered ? "kf-composer-centered mt-6 px-0 pb-8" : "kf-composer-docked px-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-1 sm:px-5 sm:pb-3")}
      data-kf-region="composer"
    >
      <div className="kf-composer-box mx-auto w-full max-w-[860px] rounded-[var(--radius-composer)] border-0">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (busy) return;
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              onSubmit();
            }
          }}
          rows={1}
          aria-label="输入消息"
          data-testid="composer-input"
          placeholder="向当前会话提问，知识库将为会话增强"
          disabled={busy}
          className={cn("kf-composer-input block max-h-[160px] w-full resize-none bg-transparent px-5 py-4 text-[15px] leading-6 outline-none disabled:cursor-not-allowed disabled:opacity-70", centered ? "min-h-[112px] text-base" : "min-h-[44px] px-4 py-3")}
        />
        <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-1.5 px-3 pb-2.5 pt-1 sm:flex sm:flex-wrap">
          <div
            className="kf-control inline-flex h-[var(--control-h-sm)] min-w-0 w-full items-center gap-1.5 rounded-lg border px-2 text-xs sm:w-auto sm:max-w-[216px]"
            title={kbLocked ? "当前会话由首条消息的知识库锁定" : "选择通用对话或知识库"}
          >
            <Database className="h-3.5 w-3.5 shrink-0 text-brand" />
            <ModelSelect
              aria-label="选择知识库"
              tone="plain"
              className="kf-kb-trigger h-[var(--control-h-sm)] min-w-[96px] flex-1 border-0 bg-transparent px-0 py-0 text-xs text-current shadow-none hover:bg-transparent focus-visible:ring-0 disabled:cursor-not-allowed disabled:text-muted"
              contentAlign="start"
              contentClassName="kf-model-content"
              contentPosition="popper"
              disabled={kbLocked || busy}
              onChange={(e) => onSelectKb(e.target.value || null)}
              options={[
                { value: "", label: "通用对话" },
                ...kbs.map((kb) => ({ value: kb.id, label: kb.name })),
              ]}
              title={kbLocked ? "当前会话由首条消息的知识库锁定" : "选择通用对话或知识库"}
              value={currentKbId ?? ""}
            />
            {kbLocked && <LockKeyhole className="h-3.5 w-3.5 shrink-0 text-muted" />}
          </div>
          <Link
            className="kf-control kf-press inline-flex size-[var(--control-h-sm)] items-center justify-center rounded-lg border"
            href={currentKbId ? `/kbs/${currentKbId}` : "/kbs"}
            aria-label={currentKbId ? "\u6253\u5f00\u77e5\u8bc6\u5e93\u4e0a\u4f20\u8d44\u6599" : "\u9009\u62e9\u77e5\u8bc6\u5e93\u540e\u4e0a\u4f20\u8d44\u6599"}
            title={currentKbId ? "\u6253\u5f00\u77e5\u8bc6\u5e93\u4e0a\u4f20\u8d44\u6599" : "\u9009\u62e9\u77e5\u8bc6\u5e93\u540e\u4e0a\u4f20\u8d44\u6599"}
          >
            <Paperclip className="h-3.5 w-3.5" />
          </Link>
          <div className="col-span-2 flex min-w-0 items-center gap-2 sm:col-auto sm:ml-auto">
            <ContextUsageIndicator
              contextStatus={contextStatus}
              loading={contextStatusLoading}
              promptTrace={promptTrace}
            />
            <ModelSelect
              aria-label="模型选择"
              className="kf-model-trigger h-8 min-w-0 flex-1 text-sm sm:min-w-[132px] sm:max-w-[200px]"
              tone="plain"
              contentAlign="end"
              contentClassName="kf-model-content"
              contentPosition="popper"
              disabled={busy}
              onChange={(event) => {
                if (event.target.value === MANAGE_MODELS_VALUE) {
                  onManageModels();
                  return;
                }
                onModelChange(event.target.value || null);
              }}
              options={selectableModelOptions}
              placeholder="选择模型"
              title="选择模型或管理模型配置"
              value={modelProfiles.length > 0 ? currentProfileId ?? "" : currentModel ?? ""}
            />
            {busy ? (
              <button
                className="kf-stop-button kf-press inline-flex h-[var(--control-h-sm)] min-w-[var(--control-h-sm)] cursor-pointer items-center justify-center gap-1 rounded-lg border px-2.5 text-xs font-medium"
                aria-label="停止生成"
                data-testid="composer-stop"
                onClick={onStop}
                type="button"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
                <span className="hidden sm:inline">{"\u505c\u6b62"}</span>
              </button>
            ) : (
              <button
                className="kf-send-button kf-press inline-flex size-[var(--control-h-sm)] shrink-0 items-center justify-center rounded-full transition disabled:cursor-not-allowed"
                aria-label="发送消息"
                data-testid="composer-send"
                disabled={!value.trim()}
                onClick={onSubmit}
                title="发送消息"
                type="button"
              >
                <ArrowUp className="h-3.5 w-3.5" strokeWidth={2.5} />
              </button>
            )}
          </div>
        </div>
      </div>
      <p className="kf-composer-disclaimer mt-2 text-center text-xs">{"\u5185\u5bb9\u7531 AI \u751f\u6210\uff0c\u8bf7\u4ed4\u7ec6\u7504\u522b"}</p>
    </div>
  );
}

export function ContextUsageIndicator({
  contextStatus,
  loading,
  promptTrace,
}: {
  contextStatus: ConversationContextStatus | null;
  loading: boolean;
  promptTrace?: MemoryTrace["prompt"] | null;
}) {
  const status = contextStatus ?? {
    state: "normal" as const,
    label: loading ? "正在读取" : "暂无数据",
    description: loading
      ? "正在读取当前会话的上下文使用情况。"
      : "暂时无法读取上下文状态，请刷新后重试。",
    current_tokens: 0,
    available_tokens: 0,
    context_window: 0,
    percent: 0,
    ratio: 0,
    retained_recent_turns: 20,
    summary: null,
  };
  const precisePercent = resolveContextUsagePercent(status);
  const percentLabel = formatContextUsagePercent(precisePercent);
  const remainingPercentLabel = formatContextUsagePercent(Math.max(0, 100 - precisePercent));
  // Keep a faint ring when usage is non-zero but still under 0.5%, so the
  // meter does not look empty next to a "1.9k / 979.9k" readout.
  const ringPercent =
    status.current_tokens > 0 && precisePercent > 0 && precisePercent < 0.5
      ? 0.5
      : precisePercent;
  const circumference = 2 * Math.PI * 8;
  const dashOffset = loading ? 0 : circumference * (1 - ringPercent / 100);
  const isAttention = status.state === "approaching" || status.state === "ready" || status.state === "critical";
  const ringTone =
    status.state === "compressed"
      ? "kf-context-ring-brand"
      : isAttention
        ? "kf-context-ring-warning"
        : "kf-context-ring-muted";
  const detail =
    status.state === "compressed"
      ? `已自动压缩长期上下文，优先保留最近 ${status.retained_recent_turns} 轮；空间不足时优先保留更近的对话。`
      : status.description;
  const displayTokenCount = (value: number) => {
    if (!Number.isFinite(value) || value <= 0) return "-";
    return value >= 1_000 ? `${(value / 1_000).toFixed(1)}k` : String(Math.round(value));
  };
  const formatPromptTokenCount = (value: number) => {
    if (!Number.isFinite(value) || value <= 0) return "0";
    return value >= 1_000 ? `${(value / 1_000).toFixed(1)}k` : String(Math.round(value));
  };
  const promptTokens = promptTrace?.tokens;
  const promptWindow = promptTrace?.context_window ?? status.context_window;
  const currentHistoryTokens = promptTokens
    ? status.current_tokens > 0
      ? status.current_tokens
      : promptTokens.history
    : 0;
  const promptTotal = promptTokens
    ? Math.max(0, promptTokens.total_input - promptTokens.history + currentHistoryTokens)
    : 0;
  const promptPercent = promptWindow > 0 ? Math.min(100, (promptTotal / promptWindow) * 100) : 0;
  const segments = promptTokens
    ? [
        { label: "系统规则", value: promptTokens.system, tone: "bg-muted" },
        { label: "工具定义", value: promptTokens.tools, tone: "bg-brand/75" },
        { label: "用户偏好", value: promptTokens.profile ?? 0, tone: "bg-info" },
        { label: "长期记忆", value: promptTokens.memory ?? 0, tone: "bg-success" },
        { label: "会话摘要", value: promptTokens.summary ?? 0, tone: "bg-warning" },
        { label: "对话历史", value: currentHistoryTokens, tone: "bg-brand" },
        { label: "知识库资料", value: promptTokens.rag, tone: "bg-danger" },
      ]
    : [];

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            aria-label={loading ? "正在读取背景信息窗口" : `查看上下文使用情况，历史已用 ${percentLabel}%`}
            className="kf-context-usage inline-flex size-7 cursor-help items-center justify-center rounded-md outline-none focus-visible:ring-2 focus-visible:ring-brand/70"
            type="button"
          >
            <svg
              aria-hidden="true"
              className={cn("size-4 -rotate-90", loading && "animate-spin motion-reduce:animate-none")}
              viewBox="0 0 20 20"
            >
              <circle className="kf-context-track stroke-current" cx="10" cy="10" fill="none" r="8" strokeWidth="2.25" />
              <circle
                className={cn("kf-context-ring stroke-current", ringTone)}
                cx="10"
                cy="10"
                fill="none"
                r="8"
                strokeDasharray={loading ? `16 ${circumference}` : circumference}
                strokeDashoffset={dashOffset}
                strokeLinecap="round"
                strokeWidth="2.25"
              />
            </svg>
          </button>
        </TooltipTrigger>
        <TooltipContent
          align="center"
          className="kf-context-tooltip w-80 px-3 py-3 text-left"
          side="top"
        >
          <div className="space-y-1 text-center">
            <p className="kf-context-tooltip-muted text-sm font-medium leading-5">会话历史预算</p>
            <p className="kf-context-tooltip-title text-base font-semibold leading-6 tabular-nums">
              {loading ? "正在读取" : `${percentLabel}% 已用（剩余 ${remainingPercentLabel}%）`}
            </p>
            <p className="kf-context-tooltip-title text-sm font-medium leading-6 tabular-nums">
              历史 {displayTokenCount(status.current_tokens)} / 可用历史预算 {displayTokenCount(status.available_tokens)}
            </p>
          </div>
          {promptTokens ? (
            <div className="mt-3 border-t border-surface-border/70 pt-3">
              <div className="flex items-baseline justify-between gap-3">
                <p className="kf-context-tooltip-muted text-sm font-medium">最近一次请求（已同步）</p>
                <p className="kf-context-tooltip-title shrink-0 text-sm font-semibold tabular-nums">
                  {formatContextUsagePercent(promptPercent)}% 已用
                </p>
              </div>
              <p className="mt-1 text-sm tabular-nums text-ink">
                {formatPromptTokenCount(promptTotal)} / {formatPromptTokenCount(promptWindow)} tokens
              </p>
              <div
                aria-label={`最近一次请求同步后的上下文使用 ${formatContextUsagePercent(promptPercent)}%`}
                aria-valuemax={promptWindow}
                aria-valuemin={0}
                aria-valuenow={promptTotal}
                className="mt-2 flex h-2 overflow-hidden rounded-full bg-surface-2"
                role="progressbar"
              >
                {segments.map((segment) => (
                  <span
                    className={segment.tone}
                    key={segment.label}
                    style={{ width: `${Math.min(100, (segment.value / promptWindow) * 100)}%` }}
                    title={`${segment.label} ${formatPromptTokenCount(segment.value)}`}
                  />
                ))}
              </div>
              <ul className="mt-3 space-y-1.5">
                {segments.map((segment) => (
                  <li className="flex items-center justify-between gap-3 text-sm" key={segment.label}>
                    <span className="flex min-w-0 items-center gap-2 text-muted">
                      <span className={cn("size-2 shrink-0 rounded-sm", segment.tone)} aria-hidden />
                      <span className="truncate">{segment.label}</span>
                    </span>
                    <span className="shrink-0 tabular-nums text-ink">{formatPromptTokenCount(segment.value)}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs leading-5 text-muted tabular-nums">
                输出预留 {formatPromptTokenCount(promptTokens.output)} · 安全余量 {formatPromptTokenCount(promptTokens.safety)}
              </p>
              <p className="mt-1 text-xs leading-5 text-muted">单位：tokens（1k = 1,000 tokens）</p>
            </div>
          ) : (
            <p className="mt-2 border-t border-surface-border/70 pt-2 text-xs leading-5 text-muted">
              最近一次请求的分段用量会在回答完成后显示。
            </p>
          )}
          {status.state === "compressed" && (
            <p className="kf-context-tooltip-summary kf-context-tooltip-muted mt-2 border-t pt-2 text-xs leading-5">
              {detail}
            </p>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
