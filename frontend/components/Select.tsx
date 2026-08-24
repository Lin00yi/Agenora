"use client";

import React, {
  forwardRef,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react";
import { CheckIcon, ChevronDownIcon } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

const EMPTY_VALUE = "__empty__";

function toRadixValue(value: string) {
  return value === "" ? EMPTY_VALUE : value;
}

function fromRadixValue(value: string) {
  return value === EMPTY_VALUE ? "" : value;
}

export type SelectOption = {
  value: string;
  label: string;
  prefix?: string;
  icon?: ReactNode;
};

export type SelectSubmenu = {
  label: string;
  options: SelectOption[];
};

type SelectProps = {
  options: SelectOption[];
  submenus?: SelectSubmenu[];
  size?: "sm" | "md";
  tone?: "default" | "plain";
  placeholder?: string;
  placeholderOption?: SelectOption;
  value?: string;
  defaultValue?: string;
  disabled?: boolean;
  name?: string;
  className?: string;
  contentClassName?: string;
  contentAlign?: "start" | "center" | "end";
  contentAlignOffset?: number;
  /** Keep a menu edge fixed to its trigger when its placement is predictable. */
  contentAvoidCollisions?: boolean;
  contentPosition?: "item-aligned" | "popper";
  id?: string;
  title?: string;
  "aria-label"?: string;
  onChange?: (event: ChangeEvent<HTMLSelectElement>) => void;
};

/** Radix Select wrapper — keeps the legacy options/value/onChange API. */
const Select = forwardRef<HTMLButtonElement, SelectProps>(function Select(
  {
    options,
    submenus = [],
    size = "md",
    tone = "default",
    placeholder,
    placeholderOption,
    className,
  contentClassName,
  contentAlign,
  contentAlignOffset,
  contentAvoidCollisions = true,
  value,
    defaultValue,
    disabled,
    name,
    onChange,
    id,
    title,
    "aria-label": ariaLabel,
  },
  ref
) {
  const [open, setOpen] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const selectedItemRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);
  const allOptions = [
    ...(placeholderOption ? [placeholderOption] : []),
    ...options,
    ...submenus.flatMap((submenu) => submenu.options),
  ];
  const currentValue = toRadixValue(
    value !== undefined && value !== null
      ? String(value)
      : defaultValue !== undefined && defaultValue !== null
        ? String(defaultValue)
        : placeholderOption?.value ?? allOptions[0]?.value ?? ""
  );

  const emitChange = (next: string) => {
    onChange?.({
      target: { value: fromRadixValue(next), name: name ?? "" },
    } as ChangeEvent<HTMLSelectElement>);
  };

  const selected = fromRadixValue(currentValue);
  const selectedOption = allOptions.find((option) => option.value === selected);

  useEffect(() => {
    if (!open) return;

    // The menu is portalled and positioned after opening. Defer one frame so
    // its final height is available before deciding whether the selected item
    // needs to be brought into view.
    const frameId = requestAnimationFrame(() => {
      const content = contentRef.current;
      const selectedItem = selectedItemRef.current;
      if (
        !content ||
        !selectedItem ||
        !content.contains(selectedItem) ||
        content.scrollHeight <= content.clientHeight
      ) {
        return;
      }

      const contentBounds = content.getBoundingClientRect();
      const itemBounds = selectedItem.getBoundingClientRect();
      if (itemBounds.top < contentBounds.top) {
        content.scrollTop += itemBounds.top - contentBounds.top;
      } else if (itemBounds.bottom > contentBounds.bottom) {
        content.scrollTop += itemBounds.bottom - contentBounds.bottom;
      }
    });

    return () => cancelAnimationFrame(frameId);
  }, [open, selected]);

  const currentLabel = selectedOption?.label ?? placeholder ?? placeholderOption?.label ?? "请选择";
  const itemTrailing = (option: SelectOption) =>
    selected === option.value ? (
      <span
        className="ml-auto flex size-4 shrink-0 items-center justify-center"
        data-slot="select-item-indicator"
        aria-hidden
      >
        <CheckIcon className="size-3.5 text-brand" />
      </span>
    ) : null;
  const optionContent = (option: SelectOption) => (
    <>
      <span
        className="flex min-w-0 flex-1 items-center gap-2 text-left"
        data-slot="select-item-label"
      >
        {option.icon && <span className="inline-flex shrink-0" aria-hidden>{option.icon}</span>}
        <span className="min-w-0 truncate">{option.prefix ? `${option.prefix} ${option.label}` : option.label}</span>
      </span>
      {itemTrailing(option)}
    </>
  );
  return (
    <DropdownMenu
      // Selects can be opened inside AppModal. Keep this menu modal so its
      // own scroll lock becomes the active one instead of the dialog's lock
      // swallowing wheel events from the portalled option list.
      modal
      open={disabled ? false : open}
      onOpenChange={(nextOpen) => {
        setOpen(disabled ? false : nextOpen);
      }}
    >
      <DropdownMenuTrigger asChild>
        <button
          ref={ref}
          id={id}
          type="button"
          disabled={disabled}
          name={name}
          title={title}
          aria-label={ariaLabel}
          data-placeholder={selectedOption ? "false" : "true"}
          className={cn(
            "grid w-full min-w-[8rem] cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-2 overflow-hidden rounded-lg border border-surface-border/80 bg-surface/95 py-0 pr-2.5 pl-3 text-sm text-ink shadow-sm outline-none transition-[background-color,border-color,box-shadow,color] select-none hover:border-brand/35 hover:bg-surface-2 focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/20 data-[placeholder=true]:text-muted/75 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-surface dark:hover:bg-surface-2",
            tone === "plain" && "border-transparent bg-transparent text-current shadow-none hover:border-transparent hover:bg-transparent focus-visible:ring-2 focus-visible:ring-brand/20",
            size === "sm" ? "h-[var(--control-h-sm)] rounded-md text-xs" : "h-[var(--control-h)]",
            className
          )}
        >
          <span className="flex min-w-0 items-center gap-1.5 truncate">
            {selectedOption?.icon && <span className="inline-flex shrink-0" aria-hidden>{selectedOption.icon}</span>}
            <span className="truncate">{currentLabel}</span>
          </span>
          <ChevronDownIcon className="pointer-events-none size-4 shrink-0 text-muted" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        ref={contentRef}
        align={contentAlign ?? "start"}
        alignOffset={contentAlignOffset}
        avoidCollisions={contentAvoidCollisions}
        className={cn("min-w-[var(--radix-dropdown-menu-trigger-width)]", contentClassName)}
      >
        {placeholderOption && (
          <DropdownMenuItem
            ref={placeholderOption.value === selected ? selectedItemRef : undefined}
            onSelect={() => emitChange(placeholderOption.value)}
          >
            {optionContent(placeholderOption)}
          </DropdownMenuItem>
        )}
        {options.map((option) => (
          <DropdownMenuItem
            key={option.value}
            ref={option.value === selected ? selectedItemRef : undefined}
            onSelect={() => emitChange(option.value)}
          >
            {optionContent(option)}
          </DropdownMenuItem>
        ))}
        {options.length > 0 && submenus.length > 0 && <DropdownMenuSeparator />}
        {submenus.map((submenu) => (
          <DropdownMenuSub key={submenu.label}>
            <DropdownMenuSubTrigger
              ref={submenu.options.some((option) => option.value === selected) ? selectedItemRef : undefined}
            >
              <span className="min-w-0 flex-1 truncate text-left">{submenu.label}</span>
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              {submenu.options.map((option) => (
                <DropdownMenuItem key={option.value} onSelect={() => emitChange(option.value)}>
                  {optionContent(option)}
                </DropdownMenuItem>
              ))}
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
});

export default Select;
