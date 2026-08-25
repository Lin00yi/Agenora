"use client";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StateView } from "@/components/ui/state-view";
import { cn } from "@/lib/cn";
import type { LucideIcon } from "lucide-react";
import { BookOpen, ChevronRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

export type BreadcrumbItem = {
  label: string;
  href?: string;
};

export type AdminSectionNavItem = {
  label: string;
  value: string;
  icon?: LucideIcon;
  muted?: boolean;
};

export type AdminContextNavItem = {
  label: string;
  href: string;
  icon?: LucideIcon;
  current?: boolean;
};

export function KnowledgeBaseContextHeader({
  breadcrumbs,
  title,
  context,
  contextNavigation,
}: {
  breadcrumbs: BreadcrumbItem[];
  title: string;
  context?: { label: string; href: string };
  contextNavigation?: AdminContextNavItem[];
}) {
  return (
    <header className="app-page-header border-b">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:px-6">
        <Link href="/kbs" className="app-nav-link app-nav-link-compact" aria-label="返回知识库管理">
          <BookOpen className="h-4 w-4" />
          <span className="hidden sm:inline">知识库</span>
        </Link>
        <ChevronRight className="hidden h-3.5 w-3.5 shrink-0 text-muted/55 sm:block" aria-hidden />
        {context ? (
          <Link href={context.href} className="min-w-0 flex-1 truncate text-sm font-medium text-ink transition-colors hover:text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30 sm:max-w-[20rem] sm:flex-none">
            {context.label}
          </Link>
        ) : (
          <nav aria-label="面包屑" className="flex min-w-0 flex-1 items-center gap-1 text-xs text-muted">
            {breadcrumbs.map((item, i) => (
              <span key={`${item.label}-${i}`} className="inline-flex min-w-0 items-center gap-1">
                {i > 0 && <ChevronRight className="h-3 w-3 shrink-0 opacity-50" />}
                {item.href ? <Link href={item.href} className="truncate rounded-md px-1.5 hover:text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30">{item.label}</Link> : <span className="truncate px-1.5 font-medium text-ink">{item.label}</span>}
              </span>
            ))}
          </nav>
        )}
        <span className="hidden shrink-0 text-sm text-muted sm:inline" aria-hidden>/</span>
        <span className="hidden truncate text-sm text-muted sm:inline">{title}</span>
        <div className="flex-1" />
      </div>
      {contextNavigation?.length ? (
        <nav className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 pb-3 sm:px-6" aria-label="知识库分区">
          {contextNavigation.map((item) => {
            const Icon = item.icon;
            return (
              <Link key={item.href} href={item.href} aria-current={item.current ? "page" : undefined} className={cn("app-mini-link gap-1.5", item.current ? "border border-brand/25 bg-brand/10 text-brand" : "text-muted hover:border-surface-border hover:bg-surface-2 hover:text-ink")}>
                {Icon ? <Icon className="h-3.5 w-3.5" aria-hidden /> : null}
                {item.label}
              </Link>
            );
          })}
        </nav>
      ) : null}
    </header>
  );
}

export function AdminPageHeading({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-col gap-3 border-b border-surface-border/70 pb-5 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-balance text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1.5 text-pretty text-sm leading-6 text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function AdminPageShell({
  breadcrumbs,
  title,
  subtitle,
  actions,
  context,
  contextNavigation,
  children,
  className,
}: {
  breadcrumbs: BreadcrumbItem[];
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  context?: { label: string; href: string };
  contextNavigation?: AdminContextNavItem[];
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("app-page admin-page min-h-dvh text-ink", className)}>
      <KnowledgeBaseContextHeader breadcrumbs={breadcrumbs} title={title} context={context} contextNavigation={contextNavigation} />

      <main className="app-page-content mx-auto px-4 py-7 sm:px-6 sm:py-10">
        <AdminPageHeading title={title} subtitle={subtitle} actions={actions} />

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
  busy = false,
  busyTitle,
  busyDescription,
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
  busy?: boolean;
  busyTitle?: string;
  busyDescription?: string;
}) {
  return (
    <section className={cn("admin-panel overflow-hidden", className)} aria-busy={busy || undefined}>
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
      <div className={cn("relative overflow-x-auto", bodyClassName)}>
        {children}
        {busy ? (
          <StateView
            variant="loading"
            overlay
            density="compact"
            title={busyTitle}
            description={busyDescription}
          />
        ) : null}
      </div>
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
                key={item.value}
                value={item.value}
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
