"use client";

import type { ReactNode } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

const SIZE_CLASS = {
  sm: "sm:max-w-sm",
  md: "sm:max-w-lg",
  lg: "sm:max-w-2xl",
  xl: "sm:max-w-3xl",
} as const;

export type AppModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  /** Leading icon / media in the header. */
  icon?: ReactNode;
  /** Fully replace the default title header. */
  header?: ReactNode;
  /**
   * Only provide the panel shell (+ optional close).
   * Caller owns header / body layout (e.g. settings with side nav).
   */
  bare?: boolean;
  size?: keyof typeof SIZE_CLASS;
  showCloseButton?: boolean;
  /** Prevent dismiss while saving. */
  busy?: boolean;
  className?: string;
  bodyClassName?: string;
  footerClassName?: string;
};

/**
 * App-level content / form modal built on shadcn Dialog.
 * Use ConfirmDialog for simple yes/no confirms.
 */
export default function AppModal({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  icon,
  header,
  bare = false,
  size = "md",
  showCloseButton = true,
  busy = false,
  className,
  bodyClassName,
  footerClassName,
}: AppModalProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!busy) onOpenChange(next);
      }}
    >
      <DialogContent
        showCloseButton={showCloseButton}
        className={cn(
          "app-modal-panel gap-0 overflow-hidden p-0",
          SIZE_CLASS[size],
          bare && "flex max-h-[min(92vh,44rem)] min-h-0 flex-col",
          className
        )}
      >
        {bare ? (
          children
        ) : (
          <>
            {header ?? (
              <DialogHeader className="gap-1 border-b border-surface-border/70 px-5 py-4 text-left">
                <div className="flex items-start gap-3 pr-8">
                  {icon ? <div className="mt-0.5 shrink-0">{icon}</div> : null}
                  <div className="min-w-0 space-y-1">
                    {title ? (
                      <DialogTitle className="text-[15px] leading-snug tracking-tight">
                        {title}
                      </DialogTitle>
                    ) : null}
                    {description ? (
                      <DialogDescription className="text-sm leading-6 text-muted">
                        {description}
                      </DialogDescription>
                    ) : null}
                  </div>
                </div>
              </DialogHeader>
            )}

            <div
              className={cn(
                "max-h-[min(70vh,36rem)] overflow-y-auto px-5 py-4",
                bodyClassName
              )}
            >
              {children}
            </div>

            {footer ? (
              <DialogFooter
                className={cn(
                  "m-0 rounded-none border-t border-surface-border/70 bg-surface-2/70 px-5 py-3",
                  footerClassName
                )}
              >
                {footer}
              </DialogFooter>
            ) : null}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
