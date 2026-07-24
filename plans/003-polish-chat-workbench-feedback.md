# 003 — Make the chat workbench respond with restraint

- **Status**: DONE
- **Commit**: 8ab73cd
- **Severity**: MEDIUM
- **Category**: Missed opportunities; physicality & origin; accessibility
- **Estimated scope**: 2 files, ~55 lines

## Problem

The main chat workbench is the highest-traffic surface, yet many of its
buttons only change color on hover and the split-button menu appears without a
spatial bridge. It also uses an unbounded mobile-sidebar transform transition.

```tsx
/* frontend/app/page.tsx:1136-1175 — current */
"… shadow-2xl transition-transform …",
"… bg-gradient-to-r from-emerald-400 to-emerald-500",
"… border-l border-white/20 transition hover:bg-emerald-500",
{newMenuOpen && (
  <div className="ak-popover absolute left-0 right-0 top-12 … shadow-2xl">
```

```tsx
/* frontend/app/page.tsx:1905-1948 — current */
"… text-slate-300 transition hover:bg-white/[0.08]",
"… px-3 text-sm text-slate-200 outline-none transition …",
"… shadow-[…] transition hover:bg-emerald-500 …",
```

## Target

Apply only purposeful, frequency-appropriate feedback:

```tsx
/* pressable control class fragment */
"transition-[transform,background-color,border-color,color,box-shadow]
 duration-[var(--duration-press)] ease-[var(--ease-out)]
 active:scale-[0.97]"

/* split menu target class fragment */
"ak-popover ak-motion-enter origin-top … opacity-100 scale-100
 duration-[var(--duration-popover)] ease-[var(--ease-out)]"
```

Use `transition-transform duration-[var(--duration-surface)]
ease-[var(--ease-drawer)] ak-motion-enter` for the mobile sidebar. The menu
entrance is a **scale in** and **origin-aware animation**, not a bounce: its
purpose is spatial consistency with the split trigger. In reduced motion it
must use the opacity-only behavior supplied by plan 001.

## Repo conventions to follow

- The chat page uses the scoped `ak-*` theme bridge in
  `frontend/app/globals.css:33-274`; keep all new reusable chat motion hooks
  in that scope or use the global hooks from plan 001.
- Use the `cn` pattern shown at `frontend/app/page.tsx:1137-1140`; no new
  component library is required.
- The existing primary action has a visual hover state at
  `frontend/app/page.tsx:1938-1948`; add press feedback instead of new
  decoration.

## Steps

1. Complete plan 001 first.
2. At `frontend/app/page.tsx:1138`, make the sidebar transition explicit:
   `transition-transform duration-[var(--duration-surface)]
   ease-[var(--ease-drawer)] ak-motion-enter`. Preserve its mobile-only
   transform and keep the desktop layout instant.
3. Add `active:scale-[0.97]` plus the exact property-specific 160ms transition
   from **Target** to the new-conversation button, its chevron button, menu
   items, mobile close button, upload link, stop button, and send button.
   Do not add a press scale to text inputs or native selects.
4. When `newMenuOpen` is true, give the menu container at line 1175 the
   `origin-top`, `ak-motion-enter`, 180ms strong ease-out, `opacity-100`, and
   `scale-100` classes. Define its entry state in the scoped CSS as
   `opacity: 0; transform: scale(0.97) translateY(-4px);`; use `@starting-style`
   when supported so no mount-state JavaScript is required.
5. In `frontend/app/globals.css`, add the corresponding `.ak-popover.ak-motion-enter`
   rules. The reduced-motion media query from plan 001 must override its
   transform to `none` and leave a 200ms opacity crossfade.

## Boundaries

- Do NOT animate message send, Enter-to-send, keyboard navigation, search,
  streaming tokens, or conversation selection. They are frequent paths where
  motion would add latency.
- Do NOT add a global page transition, parallax, ambient pulse, or list-entry
  stagger to the chat surface.
- Do NOT add Motion/Framer Motion; these are predetermined CSS interactions.
- Do NOT alter API calls, routing, dialog state, or control semantics.

## Verification

- **Mechanical**: from `frontend/`, run `npm run build` and `npx vitest run`.
- **Feel check**: click and release every scoped button. It must respond on
  pointer-down with a subtle `scale(0.97)`, then settle within 160ms; no text
  or layout may jump.
- Toggle the split menu repeatedly. At 10% animation speed, it must emerge
  from its trigger with `scale(0.97)` + opacity, never from `scale(0)`, and
  the chevron rotation must remain responsive.
- On a narrow viewport, rapidly open/close the sidebar. It must retarget from
  the current transform without a jump, and reduced-motion must change this to
  an opacity-only transition.
- **Done when**: the workbench has clear press feedback where a pointer action
  is deliberate, but no new animation on keyboard or high-frequency content.
