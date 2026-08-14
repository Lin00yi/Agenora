"use client";

import {
  forwardRef,
  type ChangeEvent,
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
  placeholderOption?: SelectOption;
  value?: string;
  defaultValue?: string;
  disabled?: boolean;
  name?: string;
  className?: string;
  contentClassName?: string;
  contentAlign?: "start" | "center" | "end";
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
    placeholderOption,
    className,
  contentClassName,
  contentAlign,
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
  const currentLabel = selectedOption?.label ?? placeholderOption?.label ?? "请选择";
  const itemLeading = (option: SelectOption) => (
    <span className="flex size-4 shrink-0 items-center justify-center" aria-hidden>
      {selected === option.value && <CheckIcon className="size-3.5 text-brand" />}
    </span>
  );
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          ref={ref}
          id={id}
          type="button"
          disabled={disabled}
          name={name}
          title={title}
          aria-label={ariaLabel}
          className={cn(
            "grid w-full min-w-[8rem] cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-2 overflow-hidden rounded-lg border border-surface-border/80 bg-surface/95 py-0 pr-2.5 pl-3 text-sm text-ink shadow-sm outline-none transition-[background-color,border-color,box-shadow,color] select-none hover:border-brand/35 hover:bg-surface-2 focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/20 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-surface dark:hover:bg-surface-2",
            tone === "plain" && "border-transparent bg-transparent text-current shadow-none hover:border-transparent hover:bg-transparent focus-visible:ring-2 focus-visible:ring-brand/20",
            size === "sm" ? "h-[var(--control-h-sm)] rounded-md text-xs" : "h-[var(--control-h)]",
            className
          )}
        >
          <span className="truncate">{currentLabel}</span>
          <ChevronDownIcon className="pointer-events-none size-4 shrink-0 text-muted" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align={contentAlign ?? "start"}
        className={cn("min-w-[var(--radix-dropdown-menu-trigger-width)]", contentClassName)}
      >
        {placeholderOption && (
          <DropdownMenuItem onSelect={() => emitChange(placeholderOption.value)}>
            {itemLeading(placeholderOption)}
            {placeholderOption.prefix ? `${placeholderOption.prefix} ${placeholderOption.label}` : placeholderOption.label}
          </DropdownMenuItem>
        )}
        {options.map((option) => (
          <DropdownMenuItem key={option.value} onSelect={() => emitChange(option.value)}>
            {itemLeading(option)}
            {option.prefix ? `${option.prefix} ${option.label}` : option.label}
          </DropdownMenuItem>
        ))}
        {options.length > 0 && submenus.length > 0 && <DropdownMenuSeparator />}
        {submenus.map((submenu) => (
          <DropdownMenuSub key={submenu.label}>
            <DropdownMenuSubTrigger>
              <span className="flex size-4 shrink-0 items-center justify-center" aria-hidden>
                {submenu.options.some((option) => option.value === selected) && <CheckIcon className="size-3.5 text-brand" />}
              </span>
              {submenu.label}
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              {submenu.options.map((option) => (
                <DropdownMenuItem key={option.value} onSelect={() => emitChange(option.value)}>
                  {itemLeading(option)}
                  {option.prefix ? `${option.prefix} ${option.label}` : option.label}
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
