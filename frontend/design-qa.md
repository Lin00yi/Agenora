# Chat workspace visual QA

## 2026-08-05 — Admin authenticated sign-off

- Promoted `1765861423@qq.com` to admin (`is_admin=true` + `ADMIN_EMAILS`).
- Light QA: `/admin` 看板、`/admin/users`、`/admin/kbs` — Brand、tabs、表格、刷新/操作按钮正常；当前账号显示「管理员 · 你」。

## 2026-08-05 — Focus + responsive QA

- Breakpoints `375 / 768 / 1024 / 1440`: Welcome、Login、Chat、KB、Settings — `overflowX === 0`.
- Focus: shared controls keep `focus-visible:ring`; Composer input relies on parent `:focus-within`.
- Fix: KB delete icon + `.admin-icon-action-soft` now keep opacity on `focus-visible` / `group-focus-within` (not hover-only).

## 2026-08-05 — Visual sign-off (public + auth surfaces)

Browser QA on `localhost:3001` (dev). Theme toggle Light/Dark exercised. Authenticated pass after user login.

| Route | Light | Dark | Notes |
|---|---|---|---|
| Welcome | ✅ | ✅ | Hero 五件套完整；Brand + CTA + 产品平面 |
| Login | ✅ | ✅ | BrandPanel + 表单卡 |
| Register | ✅ | ✅ | 与 Login 同壳 |
| Chat | ✅ | ✅ | Sidebar / Composer / KB Select / 模型 / 发送 / 检索条 / 导出动作正常 |
| KB (`/kbs`) | ✅ | — | 列表卡、新建按钮、主题 compact、加载态正常 |
| Settings | ✅ | — | LLM 表单、保存按钮、分区卡片正常 |
| Admin | ✅ | — | 看板 / 用户 / 知识库 Light 签收；`1765861423@qq.com` 显示为管理员 |

Token contrast (computed from CSS vars):

| Pair | Light | Dark | Target |
|---|---|---|---|
| brand / on-brand | **5.17:1** | **7.45:1** | ≥ 5.1 ✅ |
| ink / canvas | 15.35:1 | 17.15:1 | ≥ 4.5 ✅ |
| muted / canvas (dark) | — | 7.99:1 | ≥ 4.5 ✅ |

Also in this pass:

- `SelectTrigger` `layout="icon"` removes ThemeToggle compact `!grid-cols-1`.
- No visual regressions spotted on authenticated Chat / KB / Settings.

## 2026-08-05 — Cleanup complete (post-convergence)

- Chat paint rules unlayered; conflict `!important` eliminated (only `prefers-reduced-motion` remains).
- `SelectTrigger` gains `tone="plain"` for Chat ThemeToggle / model / KB selects.
- Context ring tones use `ak-context-ring-brand|warning|muted` (no utility color fights).
- Renamed `Dialog.tsx` → `ConfirmDialog.tsx`; all imports updated.
- Migrated `admin-toolbar-btn` / `admin-row-action` to `<Button>` via `AdminTableActions`; deleted dead CSS.

## 2026-08-05 — Chat style convergence

- Removed dead `.ak-chat` `--ak-*` color channel aliases (unused; paint uses `--chat-*` / semantic RGB).
- Renamed layout vars: `--chat-composer-offset`, `--chat-thread-scrollbar`.
- Dropped most Chat `!important` (~160 → ~50); kept only where fighting shadcn Select / ThemeToggle / send / sidebar-new.
- ChatPageClient: removed competing paint utilities on sidebar shell, composer box/controls, popover/notice shadows; sidebar rows no longer use `border-transparent`.

## 2026-08-05 — Button API sole source (post-P4)

- Migrated all remaining `admin-btn-*` call sites to `<Button>` / `buttonVariants`.
- Removed `.admin-btn-primary|secondary|danger` CSS aliases from `globals.css`.
- Canonical API: `import { Button, buttonVariants } from "@/components/ui/button"`.

## 2026-08-05 — Legacy alias removal (P4)

- Removed `--bg` / `--fg` / `--brand-dark` aliases from `:root`.
- Migrated all `text-fg` → `text-ink`, `bg-bg` → `bg-canvas`, `brand-dark` → `brand-strong`, `rgb(var(--fg|bg))` → ink/canvas.
- Tailwind no longer exposes `bg` / `fg` / duplicate `brand-dark` keys — only semantic RGB tokens remain (plus shadcn full-color vars).

## 2026-08-05 — Welcome Hero + Admin tokens (P3)

- Welcome first viewport tightened to Brand (lg) + one headline + one sentence + CTA + edge-aligned product plane; removed eyebrow chip / trust-pill strip / hero stats grid.
- Product preview is a single conversation scene (question → cited answer), not a dashboard collage.
- `app-page` / `admin-page` / admin utilities use `--canvas` / `--ink` (not legacy `--bg`/`--fg` in new rules); AdminShell shows Brand; tabs use `rounded-lg` + `text-ink`.

## 2026-08-05 — Component API unification (P2)

- Deleted unused `Sidebar.tsx` and `ChatBox.tsx` (chat owns its own sidebar).
- Confirm dialogs: all callers use named `ConfirmDialog`; deprecated default `Dialog` export removed. Content modals stay on `AppModal` → `ui/dialog`.
- `Button` variants aligned to semantic tokens (`bg-brand text-on-brand`, outline/secondary/destructive).
- `.admin-btn-*` restyled as Button-compatible aliases (same focus ring / motion); unused `.btn*` utility set removed.
- Migrated Welcome / Login / Register / AdminShell / Chat empty-state CTA to `<Button>`.

## 2026-08-05 — Chat bridge cleanup (P1)

- Removed dead `.ak-chat` attribute overrides (`bg-[#…]`, `text-slate-*`, `bg-white/` / `bg-black/`, insight/step/trace orphans, emerald `ak-control-primary`).
- Composer / sidebar / model dropdown now paint from semantic tokens (`--surface`, `--brand`, `--chat-*` aliases); no parallel dark-hex `#101a2b` model menu.
- Restored Brand logo gradient in the sidebar (removed solid-accent `!important` override).
- Composer controls in `ChatPageClient` carry `border-surface-border bg-surface-2 text-ink-2`.
- `!important` count in `globals.css` reduced ~285 → ~170; remaining uses are structural component styles, not hex bridges.
- Public surfaces visually checked 2026-08-05; authenticated Chat still pending login.

## 2026-08-05 — Design tokens v4 (P0)

- Unified semantic RGB tokens in `:root` / `.dark` (`--canvas`, `--ink`, `--brand`, …).
- Legacy aliases (`--bg`, `--fg`, `--brand-dark`) and chat aliases (`--chat-*`, `--ak-*`) now resolve through the semantic layer.
- shadcn / Radix theme vars no longer use a parallel oklch palette; they bind to `rgb(var(--…))`.
- Tailwind exposes `canvas`, `ink`, `brand-strong`, `brand-cyan`, `on-brand`, `composer`.
- Public Light/Dark visual pass completed 2026-08-05 (Welcome / Login / Register).

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

Signed off 2026-08-05: Welcome / Login / Register / Chat / KB / Settings (Light; Dark on public + Chat). Admin empty-permission state checked with non-admin account. Focus + responsive overflow matrix passed.
