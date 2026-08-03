import type { DocStatus } from "@/lib/kb-api";

export function formatAdminDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const y = d.getFullYear();
  const m = d.getMonth() + 1;
  const day = d.getDate();
  const h = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  const s = String(d.getSeconds()).padStart(2, "0");
  return `${y}/${m}/${day} ${h}:${min}:${s}`;
}

/** Rough token estimate (chars / 1.4 for mixed CJK). */
export function estimateTokens(charCount: number): number {
  return Math.max(1, Math.round(charCount / 1.4));
}

export function fileExtension(filename: string): string {
  const i = filename.lastIndexOf(".");
  if (i <= 0) return "—";
  return filename.slice(i + 1).toLowerCase();
}

export function formatFileSize(bytes: number): string {
  if (bytes <= 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export const DOC_STATUS_UI: Record<
  DocStatus,
  { label: string; dot: string; badge: string }
> = {
  pending: {
    label: "排队",
    dot: "bg-warning",
    badge: "chip-warning",
  },
  ingesting: {
    label: "处理中",
    dot: "bg-info",
    badge: "chip-info",
  },
  done: {
    label: "完成",
    dot: "bg-success",
    badge: "chip-success",
  },
  failed: {
    label: "失败",
    dot: "bg-danger",
    badge: "chip-danger",
  },
};
