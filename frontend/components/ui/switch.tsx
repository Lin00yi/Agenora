"use client"

import * as React from "react"
import { Loader2 } from "lucide-react"
import { Switch as SwitchPrimitive } from "radix-ui"

import { cn } from "@/lib/utils"

function Switch({
  className,
  size = "default",
  loading = false,
  disabled,
  ...props
}: React.ComponentProps<typeof SwitchPrimitive.Root> & {
  size?: "sm" | "default"
  loading?: boolean
}) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      data-size={size}
      data-loading={loading ? "" : undefined}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "peer group/switch relative inline-flex shrink-0 items-center rounded-full border border-transparent shadow-inner transition-all outline-none after:absolute after:-inset-x-3 after:-inset-y-2 focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30 aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20 data-[size=default]:h-[18.4px] data-[size=default]:w-[32px] data-[size=sm]:h-[14px] data-[size=sm]:w-[24px] data-[state=checked]:bg-brand data-[state=unchecked]:bg-surface-border/90 dark:data-[state=unchecked]:bg-surface-border disabled:cursor-not-allowed disabled:opacity-50",
        loading && "cursor-wait",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className={cn(
          "pointer-events-none block rounded-full bg-white shadow-sm ring-0 transition-transform group-data-[size=default]/switch:size-4 group-data-[size=sm]/switch:size-3 group-data-[size=default]/switch:data-[state=checked]:translate-x-[calc(100%-2px)] group-data-[size=sm]/switch:data-[state=checked]:translate-x-[calc(100%-2px)] group-data-[size=default]/switch:data-[state=unchecked]:translate-x-0.5 group-data-[size=sm]/switch:data-[state=unchecked]:translate-x-0.5 dark:bg-white",
          loading && "opacity-0"
        )}
      />
      {loading ? (
        <span className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <Loader2
            className={cn(
              "animate-spin text-white",
              size === "sm" ? "h-2.5 w-2.5" : "h-3 w-3"
            )}
            aria-hidden
          />
        </span>
      ) : null}
    </SwitchPrimitive.Root>
  )
}

export { Switch }
