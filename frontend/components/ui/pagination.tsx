"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

type PaginationProps = {
  total: number;
  pageSize?: number;
  page?: number;
  offset?: number;
  onPageChange?: (page: number) => void;
  onOffsetChange?: (offset: number) => void;
  disabled?: boolean;
  className?: string;
};

export function Pagination({
  total,
  pageSize = 20,
  page,
  offset,
  onPageChange,
  onOffsetChange,
  disabled = false,
  className,
}: PaginationProps) {
  const resolvedOffset = offset ?? Math.max(0, ((page ?? 1) - 1) * pageSize);
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = Math.min(pageCount, Math.floor(resolvedOffset / pageSize) + 1);
  const from = total === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const to = Math.min(currentPage * pageSize, total);
  const showNav = total > pageSize;

  const goTo = (nextPage: number) => {
    const clamped = Math.min(pageCount, Math.max(1, nextPage));
    onPageChange?.(clamped);
    onOffsetChange?.((clamped - 1) * pageSize);
  };

  return (
    <nav
      aria-label="分页"
      className={cn("flex items-center justify-between gap-3 text-xs text-muted", className)}
    >
      <p className="min-w-0 tabular-nums">
        {total === 0 ? "共 0 条" : `共 ${total} 条 · ${from}–${to}`}
      </p>
      {showNav ? (
        <div className="flex shrink-0 items-center gap-1.5">
          <Button
            type="button"
            variant="outline"
            size="icon-xs"
            aria-label="上一页"
            disabled={disabled || currentPage <= 1}
            onClick={() => goTo(currentPage - 1)}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </Button>
          <span className="min-w-12 px-1 text-center tabular-nums text-ink">
            {currentPage} / {pageCount}
          </span>
          <Button
            type="button"
            variant="outline"
            size="icon-xs"
            aria-label="下一页"
            disabled={disabled || currentPage >= pageCount}
            onClick={() => goTo(currentPage + 1)}
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      ) : null}
    </nav>
  );
}
