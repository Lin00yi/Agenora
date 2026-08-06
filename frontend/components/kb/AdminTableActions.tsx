"use client";

import Link from "next/link";
import {
  forwardRef,
  type ComponentPropsWithoutRef,
  type ReactNode,
} from "react";
import { Loader2, MoreHorizontal, type LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

/** Shared compact control look for admin table row actions. */
export const adminRowActionClassName =
  "h-7 gap-1 rounded-md px-2 text-xs font-medium shadow-none";

type AdminRowActionProps = {
  icon: LucideIcon;
  title: string;
  label?: string;
  variant?: "default" | "brand" | "danger";
  loading?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  href?: string;
  className?: string;
};

/** Compact row action for admin tables — icon with optional label + loading. */
export function AdminRowAction({
  icon: Icon,
  title,
  label,
  variant = "default",
  loading = false,
  disabled = false,
  onClick,
  href,
  className,
}: AdminRowActionProps) {
  const classes = cn(
    adminRowActionClassName,
    variant === "default" && "text-muted hover:bg-surface-2 hover:text-ink",
    variant === "brand" && "text-brand hover:bg-brand/10 hover:text-brand",
    variant === "danger" &&
      "text-danger hover:bg-danger/10 hover:text-danger",
    loading && "pointer-events-none opacity-70",
    className
  );

  const content = (
    <>
      {loading ? (
        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
      ) : (
        <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
      )}
      {label ? <span>{label}</span> : null}
    </>
  );

  if (href && !disabled && !loading) {
    return (
      <Button variant="ghost" size="sm" className={classes} asChild title={title}>
        <Link href={href}>{content}</Link>
      </Button>
    );
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className={classes}
      title={title}
      disabled={disabled || loading}
      onClick={onClick}
    >
      {content}
    </Button>
  );
}

type AdminRowMoreTriggerProps = ComponentPropsWithoutRef<"button"> & {
  title?: string;
};

/**
 * Dropdown trigger for row “更多”.
 * Renders a native <button> (not Button) so Radix DropdownMenuTrigger asChild
 * can attach pointer handlers/ref reliably — same pattern as ChatTopBar.
 */
export const AdminRowMoreTrigger = forwardRef<
  HTMLButtonElement,
  AdminRowMoreTriggerProps
>(function AdminRowMoreTrigger(
  {
    title = "更多操作",
    "aria-label": ariaLabel,
    disabled = false,
    className,
    type = "button",
    ...props
  },
  ref
) {
  return (
    <button
      ref={ref}
      type={type}
      title={title}
      aria-label={ariaLabel ?? title}
      disabled={disabled}
      className={cn(
        adminRowActionClassName,
        "inline-flex w-7 cursor-pointer items-center justify-center px-0 text-muted",
        "transition-colors hover:bg-surface-2 hover:text-ink",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30",
        "aria-expanded:bg-surface-2 aria-expanded:text-ink",
        "disabled:pointer-events-none disabled:opacity-50",
        className
      )}
      {...props}
    >
      <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
    </button>
  );
});
AdminRowMoreTrigger.displayName = "AdminRowMoreTrigger";

type AdminToolbarButtonProps = {
  icon?: LucideIcon;
  children: ReactNode;
  loading?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  type?: "button" | "submit";
  className?: string;
};

/** Toolbar button with optional spinner for refresh / batch actions. */
export function AdminToolbarButton({
  icon: Icon,
  children,
  loading = false,
  disabled = false,
  onClick,
  type = "button",
  className,
}: AdminToolbarButtonProps) {
  return (
    <Button
      type={type}
      variant="outline"
      className={cn(className)}
      disabled={disabled || loading}
      onClick={onClick}
    >
      {Icon ? (
        <Icon
          className={cn("h-3.5 w-3.5 shrink-0", loading && "animate-spin")}
          aria-hidden
        />
      ) : null}
      {children}
    </Button>
  );
}
