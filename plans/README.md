# UI Motion Improvement Plans

Generated from the current `8ab73cd` checkout after a source-level audit of
the React/Tailwind/Radix UI. The project already has the correct library
choices: Radix supplies accessible primitives, Sonner supplies toasts, and CSS
is sufficient for the recommended deterministic motion. No new dependency is
recommended.

| # | Plan | Severity | Status | Dependency |
| --- | --- | --- | --- | --- |
| 001 | Establish a restrained motion foundation | HIGH | DONE | — |
| 002 | Give dialogs, popovers, and sheets intentional motion | HIGH | DONE | 001 |
| 003 | Make the chat workbench respond with restraint | MEDIUM | DONE | 001 |
| 004 | Composite the context meter instead of animating width | MEDIUM | DONE | 001 |

Recommended execution order: **001 → 002 → 003 → 004**. Re-review the diff
after each plan using the `review-animations` bar; all plans require a
slow-motion and reduced-motion feel check, not only a successful build.

Implementation status: plans 001–004 were completed on 2026-07-24. `npx
vitest run` passes. `next build` compiles and type-checks successfully, but
the existing root route cannot complete static export because its
`useSearchParams()` call lacks a Suspense boundary; this is outside the motion
plan scope.
