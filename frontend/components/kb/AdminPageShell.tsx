"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import ThemeToggle from "@/components/ThemeToggle";

export type BreadcrumbItem = {
  label: string;
  href?: string;
};

export function AdminPageShell({
  breadcrumbs,
  title,
  subtitle,
  actions,
  children,
  className,
}: {
  breadcrumbs: BreadcrumbItem[];
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("admin-page min-h-dvh text-fg", className)}>
      <header className="border-b border-surface-border/60 bg-surface/90 backdrop-blur dark:bg-surface/95">
        <div className="mx-auto flex h-12 max-w-7xl items-center justify-end gap-2 px-4 sm:px-6">
          <ThemeToggle />
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-8">
        <nav className="mb-4 flex flex-wrap items-center gap-1 text-xs text-muted">
          {breadcrumbs.map((item, i) => (
            <span key={item.label} className="inline-flex items-center gap-1">
              {i > 0 && <ChevronRight className="h-3 w-3 opacity-50" />}
              {item.href ? (
                <Link href={item.href} className="transition hover:text-brand">
                  {item.label}
                </Link>
              ) : (
                <span className="text-fg/80">{item.label}</span>
              )}
            </span>
          ))}
        </nav>

        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            {subtitle && (
              <p className="mt-1 text-sm text-muted">{subtitle}</p>
            )}
          </div>
          {actions && (
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              {actions}
            </div>
          )}
        </div>

        {children}
      </main>
    </div>
  );
}

export function AdminPanel({
  title,
  subtitle,
  toolbar,
  footer,
  children,
  className,
}: {
  title: string;
  subtitle?: string;
  toolbar?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("admin-panel overflow-hidden", className)}>
      <div className="flex flex-col gap-3 border-b border-surface-border/60 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-base font-semibold">{title}</h2>
          {subtitle && (
            <p className="mt-0.5 text-xs text-muted">{subtitle}</p>
          )}
        </div>
        {toolbar && (
          <div className="flex flex-wrap items-center gap-2">{toolbar}</div>
        )}
      </div>
      <div className="overflow-x-auto">{children}</div>
      {footer && (
        <div className="border-t border-surface-border/60 px-5 py-3">
          {footer}
        </div>
      )}
    </section>
  );
}
