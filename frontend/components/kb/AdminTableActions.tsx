"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Loader2, type LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

type AdminRowActionProps = {
  icon: LucideIcon;
  title: string;
  label?: string;
  variant?: "default" | "brand" | "danger";
  loading?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  href?: string;
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
}: AdminRowActionProps) {
  const className = cn(
    variant === "brand" && "text-brand hover:text-brand hover:bg-brand/10",
    variant === "danger" &&
      "text-danger hover:border-danger/30 hover:bg-danger/10 hover:text-danger",
    loading && "pointer-events-none opacity-70"
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
      <Button variant="ghost" size="sm" className={className} asChild title={title}>
        <Link href={href}>{content}</Link>
      </Button>
    );
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className={className}
      title={title}
      disabled={disabled || loading}
      onClick={onClick}
    >
      {content}
    </Button>
  );
}

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
