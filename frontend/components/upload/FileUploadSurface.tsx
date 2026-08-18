"use client";

import { Eye, FileUp } from "lucide-react";
import {
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type ReactNode,
} from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

type FileUploadSurfaceProps = {
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  busy?: boolean;
  onPick: (files: File[]) => Promise<void> | void;
  onPreview?: () => void;
  label?: string;
  title?: string;
  busyTitle?: string;
  description?: ReactNode;
  selectedNames?: string[];
  icon?: ReactNode;
  className?: string;
};

export function FileUploadSurface({
  accept,
  multiple = false,
  disabled = false,
  busy = false,
  onPick,
  onPreview,
  label,
  title = "点击选择文件",
  busyTitle = "正在上传…",
  description,
  selectedNames,
  icon,
  className,
}: FileUploadSurfaceProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const dragCount = useRef(0);
  const [localNames, setLocalNames] = useState<string[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const names = selectedNames ?? localNames;
  const showPreview = Boolean(onPreview) && names.length > 0;
  const inactive = disabled || busy;

  const pickFiles = async (files: File[]) => {
    if (!files.length) return;
    setLocalNames(files.map((file) => file.name));
    try {
      await onPick(files);
    } finally {
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    void pickFiles(Array.from(event.target.files ?? []));
  };

  const handleDragEnter = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    if (inactive) return;
    dragCount.current += 1;
    setDragOver(true);
  };

  const handleDragLeave = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    dragCount.current = Math.max(0, dragCount.current - 1);
    if (dragCount.current === 0) setDragOver(false);
  };

  const handleDrop = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    dragCount.current = 0;
    setDragOver(false);
    if (inactive) return;
    const files = Array.from(event.dataTransfer.files);
    void pickFiles(multiple ? files : files.slice(0, 1));
  };

  return (
    <div className={className}>
      <input
        id={inputId}
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        onChange={handleChange}
        className="hidden"
      />
      {label ? (
        <label htmlFor={inputId} className="mb-1.5 block text-xs font-medium text-ink">
          {label}
        </label>
      ) : null}
      <div className="relative">
        {showPreview ? (
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            title="预览"
            aria-label="预览"
            className="absolute right-2 top-2 z-10 text-muted shadow-none hover:bg-surface hover:text-ink"
            onClick={onPreview}
          >
            <Eye className="h-3.5 w-3.5" />
          </Button>
        ) : null}
        <button
          type="button"
          disabled={inactive}
          onClick={() => inputRef.current?.click()}
          onDragEnter={handleDragEnter}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={cn(
            "flex min-h-[8.5rem] w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-4 py-6 text-center transition-[border-color,background-color]",
            dragOver
              ? "border-brand/50 bg-brand/5"
              : "border-surface-border bg-surface-2/50",
            showPreview && "pr-12",
            inactive
              ? "cursor-not-allowed opacity-60"
              : "hover:border-brand/35 hover:bg-surface-2/80",
          )}
        >
          <span className="admin-icon-tile admin-icon-tile-muted shadow-none text-ink">
            {icon ?? <FileUp className="h-4 w-4" />}
          </span>
          <div className="text-sm font-medium text-ink">{busy ? busyTitle : title}</div>
          {description ? (
            <p className="max-w-sm text-xs leading-5 text-muted">{description}</p>
          ) : null}
          {names.length > 0 ? (
            <p className="max-w-full truncate px-2 text-xs text-ink">{names.join("、")}</p>
          ) : null}
        </button>
      </div>
    </div>
  );
}
