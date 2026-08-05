"use client";

import type { ReactNode } from "react";
import { ExternalLink, FileText, Globe } from "lucide-react";
import type { Citation } from "@/lib/sseClient";
import { cn } from "@/lib/cn";
import {
  citationCardTitle,
  formatCitationScore,
  groupCitationsByChannel,
  resolveCitationHref,
} from "./utils";

export function SourceCards({ citations }: { citations: Citation[] }) {
  const { kb, web } = groupCitationsByChannel(citations);
  if (kb.length === 0 && web.length === 0) return null;

  return (
    <div className="mt-4 space-y-3 px-1 sm:px-2">
      {kb.length > 0 ? (
        <SourceGroup
          channel="kb"
          title="来自知识库"
          icon={<FileText className="h-3.5 w-3.5 shrink-0" />}
          items={kb}
        />
      ) : null}
      {web.length > 0 ? (
        <SourceGroup
          channel="web"
          title="来自网络"
          icon={<Globe className="h-3.5 w-3.5 shrink-0" />}
          items={web}
        />
      ) : null}
    </div>
  );
}

function SourceGroup({
  channel,
  title,
  icon,
  items,
}: {
  channel: "kb" | "web";
  title: string;
  icon: ReactNode;
  items: Citation[];
}) {
  return (
    <section aria-label={title} className="space-y-2">
      <div className="flex items-center gap-1.5 text-xs font-medium text-muted">
        {icon}
        <span>{title}</span>
        <span className="tabular-nums text-faint">· {items.length}</span>
      </div>
      <ul className="grid gap-2 sm:grid-cols-2">
        {items.map((item, index) => (
          <li key={`${channel}-${item.url || item.source || item.title}-${index}`}>
            <SourceCard item={item} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function SourceCard({ item }: { item: Citation }) {
  const isWeb = item.channel === "web";
  const scoreLabel = !isWeb ? formatCitationScore(item.score) : null;
  const href = resolveCitationHref(item);
  const title = citationCardTitle(item);
  const meta = href
    ? item.source && !item.source.includes("/")
      ? item.source
      : null
    : isWeb
      ? item.source || null
      : null;

  const body = (
    <>
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 flex-1 truncate text-sm font-medium text-ink/90">{title}</p>
        {href ? (
          <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted opacity-70" />
        ) : null}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted">
        {meta ? <span className="truncate">{meta}</span> : null}
        {scoreLabel ? (
          <span className="tabular-nums text-faint">相关度 {scoreLabel}</span>
        ) : null}
      </div>
      {item.snippet ? (
        <p className="mt-1.5 line-clamp-2 text-xs leading-5 text-muted/90">{item.snippet}</p>
      ) : null}
    </>
  );

  const className = cn(
    "block w-full rounded-lg border border-surface-border/70 bg-surface/80 px-3 py-2.5 text-left transition-colors",
    href &&
      "cursor-pointer hover:border-border-strong hover:bg-surface-2/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40"
  );

  if (href) {
    return (
      <a className={className} href={href} rel="noopener noreferrer" target="_blank">
        {body}
      </a>
    );
  }

  return <div className={className}>{body}</div>;
}
