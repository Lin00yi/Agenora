# 004 — Composite the context meter instead of animating width

- **Status**: DONE
- **Commit**: 8ab73cd
- **Severity**: MEDIUM
- **Category**: Performance; accessibility
- **Estimated scope**: 1 file, ~20 lines

## Problem

The context progress meter uses `transition-all` while React updates its
inline `width`. Width changes force layout and paint, and `transition-all`
also permits unrelated properties to animate. This panel can update during a
long, streaming conversation, which is exactly when the main thread should be
kept clear.

```tsx
/* frontend/app/page.tsx:2164-2168 — current */
<div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10">
  <div
    className={cn("h-full rounded-full transition-all", bar)}
    style={{ width: `${Math.min(100, Math.max(0, status.percent))}%` }}
  />
</div>
```

## Target

Keep the outer track at full width and change only the fill's compositor
transform. The current percentage remains visible as text, and the meter gains
native progress semantics.

```tsx
/* frontend/app/page.tsx — target */
const progress = Math.min(100, Math.max(0, status.percent));

<div
  aria-label="上下文使用率"
  aria-valuemax={100}
  aria-valuemin={0}
  aria-valuenow={progress}
  className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10"
  role="progressbar"
>
  <div
    className={cn(
      "h-full origin-left rounded-full transition-transform duration-[var(--duration-surface)] ease-[var(--ease-out)]",
      bar
    )}
    style={{ transform: `scaleX(${progress / 100})` }}
  />
</div>
```

In reduced motion, use the 200ms opacity/color feedback supplied by plan 001
and make the scale transform snap rather than animate. The numerical label
continues to communicate the change.

## Repo conventions to follow

- `status.percent` is already clamped in the JSX at
  `frontend/app/page.tsx:2167`; preserve the same 0–100 behavior.
- `cn` combines the semantic color class with shared classes throughout this
  page, for example `frontend/app/page.tsx:1137-1140`.
- Motion tokens are introduced by plan 001 in `frontend/app/globals.css`.

## Steps

1. Complete plan 001 first.
2. Immediately before the return that renders this context status block,
   calculate `const progress = Math.min(100, Math.max(0, status.percent));`.
3. Replace the outer meter `<div>` with the `role="progressbar"` container
   shown in **Target**, preserving the existing track classes.
4. Replace the fill's `transition-all` and width style with the exact
   `transition-transform`, origin, duration, easing, and `scaleX` style from
   **Target**. Do not use a CSS variable on the parent to drive this transform.
5. Apply the reduced-motion hook from plan 001 to the fill so transform motion
   is removed under `prefers-reduced-motion: reduce`.

## Boundaries

- Do NOT change context calculations, thresholds, status colors, labels, or
  request behavior.
- Do NOT add a number-ticker library: this is operational status users read,
  not a celebratory metric.
- Do NOT introduce `requestAnimationFrame`, a keyframe animation, or a parent
  CSS variable for the fill transform.

## Verification

- **Mechanical**: from `frontend/`, run `npm run build` and `npx vitest run`.
- **Feel check**: exercise normal, warning, and compressed status values. The
  fill should travel smoothly from its left origin without reflowing the right
  panel; repeat rapid status changes and look for no restart/jump.
- In DevTools Performance, confirm the meter's change is represented by a
  `transform` rather than width layout work. At 10% Animation playback, verify
  the bar does not scale from its center.
- Toggle reduced motion: the numeric status and color state remain available,
  while movement is removed.
- **Done when**: no `transition-all` or animated `width` remains on this fill,
  and a screen reader receives current/minimum/maximum progress values.
