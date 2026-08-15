# Context window tooltip QA

## Comparison target

- Source visual truth: `/var/folders/7s/ll6zgpyd3q7bzdg1795zbdnw0000gp/T/codex-clipboard-92bff893-a1b9-4a83-a7da-102217840ade.png`
- Supporting source: `/var/folders/7s/ll6zgpyd3q7bzdg1795zbdnw0000gp/T/codex-clipboard-35dca7c1-5b28-4a6a-96b0-7d8a98e2b4f7.png`
- Intended implementation: the `ContextUsageIndicator` in the authenticated `/c` composer.
- Target state: dark theme, context meter hover/focus state.

## Implementation changes inspected

- The circular context meter remains the compact entry point beside the model selector.
- Its accessible Radix tooltip now follows the source hierarchy: `背景信息窗口：` → `{percent}% 已用` → `已用 {current} 标记，共 {available}`.
- The tooltip uses the existing `surface`, `surface-border`, chat text, and shadow tokens for light/dark theme alignment.
- The reported total is the server-calculated available history budget, not the raw provider context window, so it remains honest about prompt/tool/RAG reserves.

## Rendered comparison evidence

- Browser viewport: unavailable for authenticated chat state.
- The available in-app browser redirected `/c` to the public landing page because it has no authenticated Agenora session.
- The connected Chrome surface was unavailable to the browser controller, so the existing logged-in local page could not be captured.

## Findings

- [P2] Visual hover-state comparison is blocked.
  - Evidence: no rendered authenticated composer screenshot is available in the controllable browser.
  - Impact: source and implementation cannot be compared at the same viewport/state.
  - Fix: open an authenticated local `/c` chat session in the controllable browser, hover/focus the context meter, then capture and compare the tooltip against the supplied dark reference.

## Implementation checklist

- [x] Keep the compact circular meter in the composer action row.
- [x] Present the three-line context-window hierarchy from the reference.
- [x] Use a keyboard-accessible tooltip primitive and current theme tokens.
- [x] Validate frontend lint and unit tests.
- [ ] Capture authenticated light and dark composer states for visual QA.

## Final result

final result: blocked
