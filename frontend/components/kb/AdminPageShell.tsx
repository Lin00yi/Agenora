"use client";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/cn";
import type { LucideIcon } from "lucide-react";
import { ChevronRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

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
    <div className={cn("app-page admin-page min-h-dvh text-ink", className)}>
      <header className="app-page-header border-b">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:px-6">
          <nav
            aria-label="面包屑"
            className="flex min-w-0 flex-1 flex-wrap items-center gap-1 text-xs text-muted"
          >
            {breadcrumbs.map((item, i) => (
              <span key={`${item.label}-${i}`} className="inline-flex min-w-0 items-center gap-1">
                {i > 0 && <ChevronRight className="h-3 w-3 shrink-0 opacity-50" />}
                {item.href ? (
                  <Link
                    href={item.href}
                    className="inline-flex min-h-7 max-w-full items-center truncate rounded-md px-1.5 text-muted transition-colors hover:text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30"
                  >
                    {item.label}
                  </Link>
                ) : (
                  <span className="inline-flex min-h-7 max-w-full items-center truncate px-1.5 font-medium text-ink">
                    {item.label}
                  </span>
                )}
              </span>
            ))}
          </nav>
        </div>
      </header>

      <main className="app-page-content mx-auto px-4 py-7 sm:px-6 sm:py-10">
        <div className="mb-5 flex flex-col gap-3 border-b border-surface-border/70 pb-5 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
            {subtitle && (
              <p className="mt-1.5 text-sm leading-6 text-muted">{subtitle}</p>
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

export function AdminSectionNav({
  items,
  value,
  onValueChange,
}: {
  items: AdminSectionNavItem[];
  value?: string;
  onValueChange?: (value: string) => void;
}) {
  return (
    <Tabs value={value} onValueChange={onValueChange} className="gap-0" size="large">
      <div className="mb-6 max-w-full overflow-x-auto pb-1">
        <TabsList aria-label="页面分区">
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <TabsTrigger
                key={item.href}
                value={item.href}
                className={cn(item.muted && "opacity-70")}
              >
                {Icon ? <Icon className="h-3.5 w-3.5" aria-hidden /> : null}
                {item.label}
              </TabsTrigger>
            );
          })}
        </TabsList>
      </div>
    </Tabs>
  );
}

export function AdminSection({
  id,
  icon: Icon,
  title,
  description,
  actions,
  children,
  className,
}: {
  id?: string;
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={cn("admin-section scroll-mt-24", className)}>
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-ink">
            {Icon ? <Icon className="h-4 w-4 text-brand" aria-hidden /> : null}
            <h2>{title}</h2>
          </div>
          {description ? (
            <p className="mt-1 text-xs leading-relaxed text-muted">{description}</p>
          ) : null}
        </div>
        {actions ? (
          <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
        ) : null}
      </div>
      {children}
    </section>
  );
}
