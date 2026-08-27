"use client";

import { useState, type ReactNode } from "react";
import { Eye, EyeOff } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type PasswordInputProps = Omit<React.ComponentProps<typeof Input>, "type"> & {
  prefixIcon?: ReactNode;
};

/** Password input with an accessible, local-only visibility toggle. */
export default function PasswordInput({ className, disabled, id, prefixIcon, ...props }: PasswordInputProps) {
  const [visible, setVisible] = useState(false);
  const label = visible ? "隐藏密码" : "显示密码";

  return (
    <div className="relative">
      <Input
        {...props}
        id={id}
        disabled={disabled}
        type={visible ? "text" : "password"}
        className={cn("pr-11", prefixIcon && "pl-10", className)}
      />
      {prefixIcon && (
        <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" aria-hidden>
          {prefixIcon}
        </span>
      )}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        disabled={disabled}
        aria-controls={id}
        aria-label={label}
        aria-pressed={visible}
        title={label}
        className="absolute right-1 top-1/2 size-9 -translate-y-1/2 text-muted hover:text-ink"
        onClick={() => setVisible((current) => !current)}
      >
        {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </Button>
    </div>
  );
}
