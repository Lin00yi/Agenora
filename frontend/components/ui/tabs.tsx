"use client"

import { Tabs as TabsPrimitive } from "radix-ui"
import * as React from "react"

import { cn } from "@/lib/utils"

type TabsSize = "small" | "medium" | "large"

const TabsSizeContext = React.createContext<TabsSize>("medium")

function Tabs({
  size = "medium",
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Root> & { size?: TabsSize }) {
  return (
    <TabsSizeContext.Provider value={size}>
      <TabsPrimitive.Root
        data-slot="tabs"
        className={cn("flex flex-col gap-2", className)}
        {...props}
      />
    </TabsSizeContext.Provider>
  )
}

function TabsList({
  size,
  children,
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List> & { size?: TabsSize }) {
  const inheritedSize = React.useContext(TabsSizeContext)
  const resolvedSize = size ?? inheritedSize
  const listRef = React.useRef<React.ElementRef<typeof TabsPrimitive.List> | null>(null)
  const [indicatorStyle, setIndicatorStyle] = React.useState<React.CSSProperties | null>(null)

  React.useEffect(() => {
    const listEl = listRef.current
    if (!listEl) return

    const updateIndicator = () => {
      const activeTrigger = listEl.querySelector<HTMLElement>('[data-slot="tabs-trigger"][data-state="active"]')
      if (!activeTrigger) {
        setIndicatorStyle(null)
        return
      }
      setIndicatorStyle({
        width: activeTrigger.offsetWidth,
        height: activeTrigger.offsetHeight,
        transform: `translate(${activeTrigger.offsetLeft}px, ${activeTrigger.offsetTop}px)`,
      })
    }

    updateIndicator()

    const resizeObserver = new ResizeObserver(updateIndicator)
    resizeObserver.observe(listEl)
    Array.from(listEl.querySelectorAll<HTMLElement>('[data-slot="tabs-trigger"]')).forEach((trigger) => {
      resizeObserver.observe(trigger)
    })

    const mutationObserver = new MutationObserver(updateIndicator)
    mutationObserver.observe(listEl, {
      subtree: true,
      attributes: true,
      attributeFilter: ["data-state"],
      childList: true,
    })

    window.addEventListener("resize", updateIndicator)
    return () => {
      resizeObserver.disconnect()
      mutationObserver.disconnect()
      window.removeEventListener("resize", updateIndicator)
    }
  }, [resolvedSize])

  return (
    <TabsPrimitive.List
      ref={listRef}
      data-slot="tabs-list"
      className={cn(
        "relative inline-flex w-fit items-center justify-center rounded-lg bg-surface-2 text-muted",
        resolvedSize === "small" && "h-8 p-0.5",
        resolvedSize === "medium" && "h-10 p-1",
        resolvedSize === "large" && "h-12 p-1.5",
        className
      )}
      {...props}
    >
      {indicatorStyle ? (
        <span
          aria-hidden
          className="pointer-events-none absolute left-0 top-0 rounded-md bg-surface shadow-sm transition-transform duration-200 ease-ui-out"
          style={indicatorStyle}
        />
      ) : null}
      {children}
    </TabsPrimitive.List>
  )
}

function TabsTrigger({
  size,
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Trigger> & { size?: TabsSize }) {
  const inheritedSize = React.useContext(TabsSizeContext)
  const resolvedSize = size ?? inheritedSize
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        "relative z-10 inline-flex flex-1 cursor-pointer items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap text-muted outline-none transition-[color,transform] duration-200 ease-ui-out hover:text-ink focus-visible:ring-2 focus-visible:ring-brand/20 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 data-[state=active]:text-ink data-[state=active]:scale-[1.01] [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        resolvedSize === "small" && "h-7 px-2 py-0.5 text-xs",
        resolvedSize === "medium" && "h-8 px-3 py-1 text-sm",
        resolvedSize === "large" && "h-9 px-4 py-1.5 text-base",
        className
      )}
      {...props}
    />
  )
}

function TabsContent({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn(
        "flex-1 text-sm outline-none",
        className
      )}
      {...props}
    />
  )
}

export { Tabs, TabsContent, TabsList, TabsTrigger }

