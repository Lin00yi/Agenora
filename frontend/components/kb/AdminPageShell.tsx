"use client";

import Link from "next/link";
import { ChevronRight, Home } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import ThemeToggle from "@/components/ThemeToggle";

export type BreadcrumbItem = {
  label: string;
  href?: string;
};

export type AdminSectionNavItem = {
  label: string;
  href: string;
  icon?: LucideIcon;
  muted?: boolean;
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
    <div className={cn("app-page admin-page min-h-dvh text-fg", className)}>
      <header className="app-page-header border-b">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4 sm:px-6">
          <Link
            href="/"
            className="admin-icon-action admin-icon-action-surface"
            aria-label="返回首页"
          >
            <Home className="h-4 w-4" />
          </Link>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold">{title}</div>
            <div className="hidden text-xs text-muted sm:block">知识库管理</div>
          </div>
          <ThemeToggle />
        </div>
      </header>

      <main className="app-page-content mx-auto px-4 py-7 sm:px-6 sm:py-10">
        <nav className="mb-5 flex flex-wrap items-center gap-1 text-xs text-muted">
          {breadcrumbs.map((item, i) => (
            <span key={item.label} className="inline-flex items-center gap-1">
              {i > 0 && <ChevronRight className="h-3 w-3 opacity-50" />}
              {item.href ? (
                <Link
                  href={item.href}
                  className="inline-flex min-h-7 items-center rounded-md border border-transparent px-2 text-muted transition-colors hover:border-surface-border/70 hover:bg-surface hover:text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30"
                >
                  {item.label}
                </Link>
              ) : (
                <span className="inline-flex min-h-7 items-center rounded-md border border-surface-border/70 bg-surface px-2 font-medium text-fg shadow-sm">
                  {item.label}
                </span>
              )}
            </span>
          ))}
        </nav>

        <div className="mb-6 flex flex-col gap-4 border-b border-surface-border/70 pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-tight text-fg">{title}</h1>
            {subtitle && (
              <p className="mt-2 text-sm leading-6 text-muted">{subtitle}</p>
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
  selectionBar,
  children,
  className,
  headerClassName,
  toolbarClassName,
  bodyClassName,
}: {
  title: string;
  subtitle?: string;
  toolbar?: ReactNode;
  footer?: ReactNode;
  selectionBar?: ReactNode;
  children: ReactNode;
  className?: string;
  headerClassName?: string;
  toolbarClassName?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cn("admin-panel overflow-hidden", className)}>
      <div
        className={cn(
          "flex flex-col gap-3 border-b border-surface-border/70 bg-surface-2/35 px-5 py-4 sm:flex-row sm:items-center sm:justify-between",
          headerClassName
        )}
      >
        <div className="min-w-0">
          <h2 className="text-base font-semibold">{title}</h2>
          {subtitle && (
            <p className="mt-1 text-xs leading-relaxed text-muted">{subtitle}</p>
          )}
        </div>
        {toolbar && (
          <div className={cn("flex flex-wrap items-center gap-2", toolbarClassName)}>
            {toolbar}
          </div>
        )}
      </div>
      {selectionBar && (
        <div className="border-b border-surface-border/60 bg-brand/5 px-5 py-3">
          {selectionBar}
        </div>
      )}
      <div className={cn("overflow-x-auto", bodyClassName)}>{children}</div>
      {footer && (
        <div className="border-t border-surface-border/60 px-5 py-3">
          {footer}
        </div>
      )}
    </section>
  );
}

export function AdminSectionNav({ items }: { items: AdminSectionNavItem[] }) {
  return (
    <nav className="admin-section-nav" aria-label="页面分区">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <a
            key={item.href}
            href={item.href}
            className={cn("admin-section-nav-item", item.muted && "opacity-70")}
          >
            {Icon ? <Icon className="h-3.5 w-3.5" aria-hidden /> : null}
            <span>{item.label}</span>
          </a>
        );
      })}
    </nav>
  );
}

export function AdminSection({
  id,
  icon: Icon,
  title,
  description,
  children,
  className,
}: {
  id?: string;
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={cn("admin-section scroll-mt-24", className)}>
      <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-fg">
            {Icon ? <Icon className="h-4 w-4 text-brand" aria-hidden /> : null}
            <h2>{title}</h2>
          </div>
          {description ? (
            <p className="mt-1 text-xs leading-relaxed text-muted">{description}</p>
          ) : null}
        </div>
      </div>
      {children}
    </section>
  );
}
