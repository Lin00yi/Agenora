# Chat workspace visual QA

## Scope

- Refresh the sidebar launch area (brand, new conversation, search, and all conversations) while preserving the existing recent-conversation list and account area below it.
- Use the supplied RAG-answer screenshot as the starting visual reference, then constrain it into an enterprise SaaS system language: light cloud canvas, blue/cyan emphasis, restrained shadows, square-ish controls, and a soft but structured composer.
- Apply that direction to the chat workspace in light and dark mode.
- Extend the same color system and page-shell layout to the knowledge-base, document management, settings, authentication, invitation, welcome, and admin routes without changing their business flows.
- Keep knowledge-base selection, model selection, attachments, send/stop, and the context-usage ring inside the composer.

## Source checks completed

- The chat header now contains only the conversation title and existing utility actions.
- Retrieval/tool events, sources, and answer export actions render inline with each assistant answer.
- The context-usage control remains a circular progress ring; its detailed token and loading information is still available on hover and keyboard focus.
- Each answer export action targets its own answer node.
- Shared global tokens, brand treatment, page chrome, cards, tabs, forms, and primary actions now use a restrained blue/cyan enterprise system across non-chat pages.
- The light-mode brand and muted text tokens were darkened to meet normal-text contrast targets; primary actions now have at least a 5.1:1 contrast ratio against white.
- Chat search now supports Ctrl/Cmd+K, the new-conversation menu closes on Escape and outside click, and the context-usage indicator is focusable informational content rather than an inert button.
- Theme switching is present on the admin shell and mobile chat header.
- The composer send action now uses the same square primary-control language as the rest of the workspace; shared Radix selects and remaining native selects use a consistent elevated trigger, focus ring, and option treatment.
- The new-conversation split dropdown was removed; its primary action keeps the current knowledge-base selection in the draft workspace.
- New conversation now opens `/c` as a draft workspace without creating a server conversation. The first send creates the conversation and replaces the URL with `/c/{id}`; the centered draft layout keeps the large composer between the answer-oriented heading and starter cards.
- Enterprise constraints applied after the shadcn-style pass: badges use `rounded-md` plus visible borders, theme toggle items are 36px square controls, sheet panels have structured header/footer bands, select scroll controls use pointer cursors, and switches keep the familiar pill affordance while gaining larger hit areas and clearer checked/unchecked borders.

## Automated verification

- `npm run build` passed.
- `npx vitest run` passed (1 test).

## Visual verification

Final result: **blocked** — the in-app browser cannot reach the local development server and the external Chrome bridge is not available in this environment. Light/dark screenshots and interaction states (composer hover, context tooltip, loading, and narrow layout) must be checked in the user’s browser before final visual sign-off.
