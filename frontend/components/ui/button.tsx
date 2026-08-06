import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "group/button inline-flex cursor-pointer shrink-0 items-center justify-center rounded-lg border border-transparent bg-clip-padding text-sm font-medium whitespace-nowrap shadow-sm transition-[transform,background-color,border-color,color,box-shadow] duration-press ease-ui-out outline-none select-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:not-aria-[haspopup]:scale-[0.97] disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-brand text-on-brand shadow-none hover:bg-brand-strong dark:bg-brand dark:text-on-brand dark:hover:bg-brand-strong",
        outline:
          "border-surface-border/80 bg-surface text-ink hover:border-brand/35 hover:bg-surface-2 hover:text-ink aria-expanded:border-brand/35 aria-expanded:bg-surface-2 aria-expanded:text-ink dark:border-surface-border/80 dark:bg-surface dark:hover:bg-surface-2",
        secondary:
          "border-surface-border/80 bg-surface-2 text-ink hover:border-brand/30 hover:bg-surface aria-expanded:border-brand/35 aria-expanded:bg-surface-2 aria-expanded:text-ink",
        ghost:
          "text-muted hover:bg-surface-2 hover:text-ink aria-expanded:bg-surface-2 aria-expanded:text-ink dark:hover:bg-surface-2/70",
        destructive:
          "border-danger/30 bg-danger/10 text-danger hover:border-danger/45 hover:bg-danger/15 focus-visible:border-danger/40 focus-visible:ring-danger/25",
        link: "text-brand underline-offset-4 hover:underline",
      },
      size: {
        default:
          "h-[var(--control-h)] gap-1.5 px-3 has-data-[icon=inline-end]:pr-2.5 has-data-[icon=inline-start]:pl-2.5",
        xs: "h-6 gap-1 rounded-[min(var(--radius-md),10px)] px-2 text-xs in-data-[slot=button-group]:rounded-lg has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-[var(--control-h-sm)] gap-1 rounded-[min(var(--radius-md),12px)] px-2.5 text-[0.8rem] in-data-[slot=button-group]:rounded-lg has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-11 gap-1.5 px-4 has-data-[icon=inline-end]:pr-3 has-data-[icon=inline-start]:pl-3",
        icon: "size-[var(--control-h)]",
        "icon-xs":
          "size-6 rounded-[min(var(--radius-md),10px)] in-data-[slot=button-group]:rounded-lg [&_svg:not([class*='size-'])]:size-3",
        "icon-sm":
          "size-[var(--control-h-sm)] rounded-[min(var(--radius-md),12px)] in-data-[slot=button-group]:rounded-lg",
        "icon-lg": "size-[var(--control-h)]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

const Button = React.forwardRef<
  HTMLButtonElement,
  React.ComponentProps<"button"> &
    VariantProps<typeof buttonVariants> & {
      asChild?: boolean
    }
>(function Button(
  {
    className,
    variant = "default",
    size = "default",
    asChild = false,
    ...props
  },
  ref
) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      ref={ref}
      {...props}
    />
  )
})
Button.displayName = "Button"

export { Button, buttonVariants }
