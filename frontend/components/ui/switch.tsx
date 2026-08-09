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
        "peer group/switch relative inline-flex cursor-pointer shrink-0 items-center rounded-full border border-surface-border/70 shadow-inner transition-[background-color,border-color,box-shadow,transform] duration-press ease-ui-out outline-none after:absolute after:-inset-x-3 after:-inset-y-3 hover:border-brand/35 focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30 aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20 data-[size=default]:h-6 data-[size=default]:w-11 data-[size=sm]:h-5 data-[size=sm]:w-9 data-[state=checked]:border-brand/70 data-[state=checked]:bg-brand data-[state=unchecked]:bg-surface-border/90 dark:data-[state=unchecked]:border-white/15 dark:data-[state=unchecked]:bg-white/20 disabled:cursor-not-allowed disabled:opacity-50",
        loading && "cursor-wait",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className={cn(
          // Checked thumb uses --on-brand (white on black / black on white) so dark brand track stays readable.
          "pointer-events-none block rounded-full bg-white shadow-sm ring-0 transition-[transform,background-color] duration-press ease-ui-out group-data-[size=default]/switch:size-5 group-data-[size=sm]/switch:size-4 group-data-[size=default]/switch:data-[state=checked]:translate-x-5 group-data-[size=sm]/switch:data-[state=checked]:translate-x-4 group-data-[size=default]/switch:data-[state=unchecked]:translate-x-0.5 group-data-[size=sm]/switch:data-[state=unchecked]:translate-x-0.5 dark:bg-white group-data-[state=checked]/switch:bg-on-brand dark:group-data-[state=checked]/switch:bg-on-brand",
          loading && "opacity-0"
        )}
      />
      {loading ? (
        <span className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <Loader2
            className={cn(
              "animate-spin text-on-brand",
              size === "sm" ? "h-2.5 w-2.5" : "h-3.5 w-3.5"
            )}
            aria-hidden
          />
        </span>
      ) : null}
    </SwitchPrimitive.Root>
  )
}

export { Switch }
