# 001 — Establish a restrained motion foundation

- **Status**: DONE
- **Commit**: 8ab73cd
- **Severity**: HIGH
- **Category**: Easing & duration; accessibility; cohesion & tokens
- **Estimated scope**: 5 files, ~70 lines

## Problem

The shared UI layer has no named motion vocabulary and repeatedly uses Tailwind's
unbounded `transition-all`. That makes layout, shadows, borders, and colors
animate incidentally, rather than making each component declare the properties
it changes. It also provides no `prefers-reduced-motion` fallback for the
movement used by the shared primitives.

```css
/* frontend/app/globals.css:308-349 — current */
.btn {
  @apply inline-flex items-center justify-center gap-1.5 rounded-lg
         border px-3.5 py-2 text-sm font-medium
         transition-all duration-200
         disabled:opacity-50 disabled:cursor-not-allowed
         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30
         active:scale-[0.98];
}

.card-hover {
  @apply transition-all duration-200
         hover:border-brand/25 hover:bg-surface hover:shadow-lift;
}

.input-shell {
  @apply rounded-lg border border-surface-border/80 bg-surface
         transition-all duration-200
         focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/15;
}
```

```tsx
/* frontend/components/ui/button.tsx:7-8 — current */
const buttonVariants = cva(
  "… whitespace-nowrap transition-all … active:not-aria-[haspopup]:translate-y-px …",
```

```tsx
/* frontend/components/ui/switch.tsx:26-37 — current */
"… shadow-inner transition-all … data-[state=checked]:bg-brand …",
"… shadow-sm ring-0 transition-transform …",
```

## Target

Put a single motion vocabulary beside the existing global color tokens:

```css
/* frontend/app/globals.css — target */
:root {
  --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
  --ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);
  --ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);
  --duration-press: 160ms;
  --duration-popover: 180ms;
  --duration-surface: 200ms;
}

@media (prefers-reduced-motion: reduce) {
  .ak-motion-enter,
  .ak-motion-surface {
    transition-duration: 200ms !important;
    transform: none !important;
  }
}
```

Replace `transition-all` only with the declared properties the component
actually changes. Use `transition-[transform,background-color,color,border-color,box-shadow]`
with `duration-[var(--duration-press)] ease-[var(--ease-out)]` for pressable
controls, `transition-[background-color,border-color,box-shadow]` for surfaces,
and `transition-[background-color,transform]` on the switch root. Retain the
thumb's existing `transition-transform`, set it to
`duration-[var(--duration-press)] ease-[var(--ease-out)]`, and keep its
motion to `transform` only.

## Repo conventions to follow

- Global visual tokens already live in `frontend/app/globals.css:9-26`; add the
  motion tokens there rather than making a parallel stylesheet.
- Components use Tailwind strings composed with `cn` and `cva`, as shown in
  `frontend/components/ui/button.tsx:7-8`.
- The project already uses CSS classes for reusable shared styles under
  `@layer components` in `frontend/app/globals.css:307-485`.

## Steps

1. In `frontend/app/globals.css`, add the three exact easing variables and
   three duration variables shown in **Target** to `:root` immediately after
   the existing color tokens.
2. In that same file, replace the `transition-all` declarations at lines 311,
   337, 348, 366, 377, 453, and 464 with property-specific transitions.
   Preserve the current 150ms/200ms timing intent, but express it with the
   motion tokens and `var(--ease-out)`.
3. Add the reduced-motion rule from **Target** and apply `ak-motion-enter` or
   `ak-motion-surface` only to components that move or scale in plans 002 and
   003. Do not disable opacity or color feedback.
4. In `frontend/components/ui/button.tsx`, replace the root
   `transition-all` with the exact property list in **Target`; add
   `active:not-aria-[haspopup]:scale-[0.97]` while retaining the existing
   `translate-y-px` only if it still looks needed after a slow-motion check.
5. In `frontend/components/ui/switch.tsx`, replace the root `transition-all`
   with `transition-[background-color,transform]` and add the exact duration
   and easing from **Target**. Give the thumb the same duration and easing.

## Boundaries

- Do NOT add a motion/spring dependency; CSS is appropriate for these
  predetermined state changes.
- Do NOT change element structure, keyboard behavior, colors, or component
  APIs.
- Do NOT animate keyboard-driven navigation or the command/search shortcut.
- If a Tailwind arbitrary property syntax does not compile in the installed
  Tailwind 3.4.4 setup, add the equivalent scoped CSS selector in
  `frontend/app/globals.css`; do not reintroduce `transition-all`.

## Verification

- **Mechanical**: from `frontend/`, run `npm run build` and `npx vitest run`.
  Both must finish successfully.
- **Feel check**: press default, outline, ghost, and destructive buttons. The
  response must start on pointer-down, shrink only to `scale(0.97)`, and settle
  within 160ms without a visible layout shift.
- In DevTools Animations at 10% speed, verify no shared component animates
  layout dimensions or an unintended property when hover/focus/disabled state
  changes.
- Toggle `prefers-reduced-motion: reduce` in DevTools Rendering. Movement and
  scale must disappear while opacity, color, and focus feedback remain.
- **Done when**: `rg -n "transition-all" frontend/app/globals.css frontend/components/ui/{button,switch}.tsx`
  returns no matches, and the checks above pass.
