"use client";

import type { ReactNode } from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";

export type ConfirmDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "default" | "danger";
  onConfirm: () => void | Promise<void>;
  busy?: boolean;
  size?: "sm" | "md";
  className?: string;
};

/** App-level confirm dialog. Prefer this for destructive / irreversible actions. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "确定",
  cancelLabel = "取消",
  variant = "default",
  onConfirm,
  busy = false,
  size = "sm",
  className,
}: ConfirmDialogProps) {
  const danger = variant === "danger";

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!busy) onOpenChange(next);
      }}
    >
      <AlertDialogContent
        size={size === "sm" ? "sm" : "default"}
        className={cn("app-modal-panel", className)}
      >
        <AlertDialogHeader className="gap-2 text-left sm:text-left">
          <AlertDialogTitle className="text-[15px] leading-snug tracking-tight">
            {title}
          </AlertDialogTitle>
          {description ? (
            <AlertDialogDescription asChild>
              <div className="text-sm leading-6 text-muted">{description}</div>
            </AlertDialogDescription>
          ) : null}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>{cancelLabel}</AlertDialogCancel>
          <AlertDialogAction
            variant={danger ? "destructive" : "default"}
            disabled={busy}
            className={
              danger
                ? "border-transparent bg-[rgb(var(--danger))] text-white hover:bg-[rgb(var(--danger))]/90 focus-visible:ring-[rgb(var(--danger))]/25 dark:bg-[rgb(var(--danger))] dark:hover:bg-[rgb(var(--danger))]/90"
                : undefined
            }
            onClick={(e) => {
              e.preventDefault();
              void onConfirm();
            }}
          >
            {busy ? "处理中…" : confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/** @deprecated Prefer ConfirmDialog. Kept as default export for existing imports. */
export default function Dialog(props: ConfirmDialogProps) {
  return <ConfirmDialog {...props} />;
}
