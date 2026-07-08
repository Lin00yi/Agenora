"use client";

import {
  forwardRef,
  type ChangeEvent,
} from "react";
import {
  Select as ShadcnSelect,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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

type SelectProps = {
  options: SelectOption[];
  size?: "sm" | "md";
  placeholderOption?: SelectOption;
  value?: string;
  defaultValue?: string;
  disabled?: boolean;
  name?: string;
  className?: string;
  id?: string;
  title?: string;
  "aria-label"?: string;
  onChange?: (event: ChangeEvent<HTMLSelectElement>) => void;
};

/** Radix Select wrapper — keeps the legacy options/value/onChange API. */
const Select = forwardRef<HTMLButtonElement, SelectProps>(function Select(
  {
    options,
    size = "md",
    placeholderOption,
    className,
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
  const allOptions = placeholderOption ? [placeholderOption, ...options] : options;
  const currentValue = toRadixValue(
    value !== undefined && value !== null
      ? String(value)
      : defaultValue !== undefined && defaultValue !== null
        ? String(defaultValue)
        : placeholderOption?.value ?? allOptions[0]?.value ?? ""
  );

  return (
    <ShadcnSelect
      value={currentValue}
      disabled={disabled}
      name={name}
      onValueChange={(next) => {
        onChange?.({
          target: { value: fromRadixValue(next), name: name ?? "" },
        } as ChangeEvent<HTMLSelectElement>);
      }}
    >
      <SelectTrigger
        ref={ref}
        id={id}
        title={title}
        aria-label={ariaLabel}
        size={size === "sm" ? "sm" : "default"}
        className={cn("w-full min-w-[8rem]", className)}
      >
        <SelectValue placeholder={placeholderOption?.label ?? "请选择"} />
      </SelectTrigger>
      <SelectContent>
        {allOptions.map((opt) => (
          <SelectItem key={toRadixValue(opt.value)} value={toRadixValue(opt.value)}>
            {opt.prefix ? `${opt.prefix} ${opt.label}` : opt.label}
          </SelectItem>
        ))}
      </SelectContent>
    </ShadcnSelect>
  );
});

export default Select;
