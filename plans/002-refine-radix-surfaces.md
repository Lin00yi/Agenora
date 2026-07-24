# 002 — Give dialogs, popovers, and sheets intentional motion

- **Status**: DONE
- **Commit**: 8ab73cd
- **Severity**: HIGH
- **Category**: Easing & duration; physicality & origin; accessibility
- **Estimated scope**: 4 files, ~35 lines

## Problem

The shared Radix primitives already have correct trigger-aware origins for
menus/selects, but use stock 100ms animation classes. The Sheet has an
unbounded `transition` plus generic `ease-in-out`, which is weaker than the
product's intended responsive/drawer behavior. None of these motion surfaces
has a local reduced-motion path.

```tsx
/* frontend/components/ui/sheet.tsx:65 — current */
"… shadow-lg transition duration-200 ease-in-out … data-open:animate-in …
 data-[side=bottom]:data-open:slide-in-from-bottom-10 …
 data-closed:animate-out …"
```

```tsx
/* frontend/components/ui/dropdown-menu.tsx:46 — current */
"… origin-(--radix-dropdown-menu-content-transform-origin) … duration-100
 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 …"
```

```tsx
/* frontend/components/ui/select.tsx:72 — current */
"… origin-(--radix-select-content-transform-origin) … duration-100
 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 …"
```

```tsx
/* frontend/components/ui/dialog.tsx:42,64 — current */
"… duration-100 … data-open:fade-in-0 …",
"… duration-100 … data-open:fade-in-0 data-open:zoom-in-95 …",
```

## Target

Keep the current Radix `origin-(--radix-*-content-transform-origin)` on
anchored surfaces. Use the global tokens from plan 001:

```tsx
/* dropdown/select target class fragments */
"duration-[var(--duration-popover)] ease-[var(--ease-out)]
 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95
 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95
 ak-motion-enter"

/* dialog target class fragments — centered modal stays center-origin */
"duration-[var(--duration-popover)] ease-[var(--ease-out)]
 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95
 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95
 ak-motion-enter"

/* sheet target class fragments */
"transition-[transform,opacity] duration-[var(--duration-surface)]
 ease-[var(--ease-drawer)] ak-motion-enter
 data-open:animate-in data-open:fade-in-0 … data-closed:animate-out …"
```

For `prefers-reduced-motion`, the classes supplied by plan 001 must prevent
the scale/slide transform while retaining the same 180ms/200ms opacity bridge.
The sheet is a drawer, so its 200ms drawer curve is appropriate; do not give
it spring/bounce behavior because it is not draggable today.

## Repo conventions to follow

- UI primitives are Radix wrappers using `data-open`/`data-closed` animation
  classes, exemplified by `frontend/components/ui/dialog.tsx:34-68`.
- Popover and select origin variables are already correct at
  `frontend/components/ui/dropdown-menu.tsx:46` and
  `frontend/components/ui/select.tsx:72`; preserve them.
- Global motion tokens and the `ak-motion-enter` accessibility hook are
  introduced by plan 001 in `frontend/app/globals.css`.

## Steps

1. Complete plan 001 first.
2. In `frontend/components/ui/dropdown-menu.tsx`, change both content class
   strings at lines 46 and 247 from `duration-100` to
   `duration-[var(--duration-popover)] ease-[var(--ease-out)] ak-motion-enter`.
   Keep the Radix transform-origin and the existing `zoom-in-95`/`zoom-out-95`.
3. In `frontend/components/ui/select.tsx:72`, make the same timing and
   accessibility-class change; retain `data-[align-trigger=true]:animate-none`.
4. In `frontend/components/ui/dialog.tsx`, apply
   `duration-[var(--duration-popover)] ease-[var(--ease-out)] ak-motion-enter`
   to the overlay and content. Do not add a custom transform-origin: centered
   dialogs are the explicit exception to trigger-origin animation.
5. In `frontend/components/ui/sheet.tsx`, replace bare `transition duration-200
   ease-in-out` with `transition-[transform,opacity] duration-[var(--duration-surface)]
   ease-[var(--ease-drawer)] ak-motion-enter`. Apply the same 200ms
   `ease-[var(--ease-out)]` opacity timing to its overlay.

## Boundaries

- Do NOT replace Radix with Base UI; Radix is already installed and correctly
  supplies focus management and dismissal.
- Do NOT add drag-to-dismiss. A future iOS-style sheet drag needs Motion or a
  dedicated sheet primitive, pointer capture, velocity hand-off, momentum
  projection, and rubber-banding; it is not a CSS-only enhancement.
- Do NOT change dialog/sheet layout, side selection, z-index, or focus logic.

## Verification

- **Mechanical**: from `frontend/`, run `npm run build` and `npx vitest run`.
- **Feel check**: trigger a dropdown and select from each side available in
  the app. At 10% DevTools speed, both must scale from the trigger rather than
  the viewport center; opening then immediately closing must reverse cleanly.
- Open a dialog and confirm its centered scale is still centered. Open every
  sheet side and confirm it enters/exits on the same side within 200ms.
- Toggle reduced motion: menus/dialogs/sheets retain an opacity transition but
  do not translate or scale.
- **Done when**: no shared surface uses bare `ease-in-out` or a 100ms stock
  enter/exit duration, and all interaction/focus behavior remains unchanged.
