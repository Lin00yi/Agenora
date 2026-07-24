# Chat workspace visual QA

## Scope

- Refresh the sidebar launch area (brand, new conversation, search, and all conversations) while preserving the existing recent-conversation list and account area below it.
- Use the supplied RAG-answer screenshot as the visual reference: a light cloud canvas, blue-to-violet emphasis, a centered answer-oriented empty state, and a soft, prominent composer.
- Apply that direction only to the chat workspace, in light and dark mode.
- Keep knowledge-base selection, model selection, attachments, send/stop, and the context-usage ring inside the composer.

## Source checks completed

- The chat header now contains only the conversation title and existing utility actions.
- Retrieval/tool events, sources, and answer export actions render inline with each assistant answer.
- The context-usage control remains a circular progress ring; its detailed token and loading information is still available on hover and keyboard focus.
- Each answer export action targets its own answer node.

## Automated verification

- `npm run build` passed.
- `npm test -- --run` passed (1 test).

## Visual verification

Final result: **blocked** — the in-app browser cannot reach the local development server and the external Chrome bridge is not available in this environment. Light/dark screenshots and interaction states (composer hover, context tooltip, loading, and narrow layout) must be checked in the user’s browser before final visual sign-off.
