# Design QA

final result: passed

Reference: `C:\Users\17658\AppData\Local\Temp\codex-clipboard-ec1d887e-ad23-4a0d-b3eb-d14bf079b6d0.png`

Verified target: `http://localhost:3000/`

Checks:
- Dark enterprise three-column shell is implemented: left navigation, central chat workspace, right retrieval/source panel.
- Top bar is now informational: it shows the locked conversation knowledge base and account/model readiness state, while mutable model/retrieval controls live in the composer.
- Primary actions are present: new conversation, knowledge-base management/upload links, model selection, hybrid retrieval settings, send/stop composer.
- Conversation rendering, knowledge-base binding, SSE streaming, and persisted server conversations remain wired to existing APIs.
- Empty conversations now show a real waiting state instead of a fake completed answer.
- Sidebar conversation count/search and right-panel source/process states are derived from current app state instead of fixed mock values.
- Composer controls are explicitly accessible/testable (`composer-input`, `composer-send`, `composer-stop`) and remain visible at 1280x720.
- Real send flow verified in the browser: typed a question, clicked send, received an assistant answer, and confirmed no console errors.
- Self-audit pass removed or downgraded static-looking controls: mock KB entries are gone, real KB/settings/help/upload links are wired, unsupported filters/feedback/source-detail actions are removed or disabled with explanatory titles.
- Second self-audit pass removed remaining static residue: message timestamps use real message time, missing conversation time renders as `-`, user avatars use the logged-in user initial, model/status no longer hardcode `GPT-4o` or `就绪`, and the right source panel no longer fabricates a source when the backend returns none.
- Test suite fixed and verified: `components/ThinkingChain` imports React for JSX constants, its test imports React for JSX rendering, and the test assertion now matches the component's running-state copy.
- Request follow-up pass: removed unimplemented `@ 我` / `收藏` / `回收站` sidebar entries, right-aligned user messages, locked KB switching once a conversation has messages, moved model and retrieval controls into the composer, and converted source-looking cards/right rail into read-only tool-call status.
- Completion pass: the new-conversation split button now opens a real menu (`新建通用对话` / `基于当前知识库新建`), and locked conversations gray out inactive knowledge bases with lock affordance instead of allowing misleading clicks.
- Full-system self-test pass: locked conversations now make every KB row read-only, the current-KB new-chat action is disabled when no KB is bound, and LLM readiness distinguishes user BYOK, system fallback, and missing configuration.
- Conversation URL pass: individual conversations are addressable at `/c/{conversationId}`; root auto-open, sidebar switching, explicit new conversation, deletion fallback, and direct reload all keep the active conversation id in the URL.
- Conversation switching smoothness pass: sidebar switching/new conversation/deletion now update `/c/{conversationId}` with the History API instead of Next route navigation, so the chat shell is not remounted on every conversation change; browser back/forward loads the matching conversation through `popstate`.
- Right panel info pass: the session information block now exposes a copyable conversation ID, created/updated times, turn/message statistics, linked knowledge base, and model source instead of raw sparse database fields.
- Browser verification passed with no console errors.

Notes:
- The first-run screen keeps the visual direction of the reference while clearly showing that no retrieval has happened yet.
- `npm run lint` is not currently usable as a non-interactive check because Next prompts to create an ESLint config; `npm run build` and `npx vitest run` are the reliable checks used here.
- Remaining product notes from self-test: the bundled system KB is an optional travel demo ("旅行演示库（可选）"), not the default unbound Agenora persona; the in-app browser in this environment does not expose screenshot capture, so mobile layout was checked with DOM/overflow assertions rather than visual screenshots.
