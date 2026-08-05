# KnowFlow UI 设计系统 v5

> v5：**Flow Teal** 主题色 + 新字体栈 + `--kf-*` Token 为唯一真相源；Chat DOM 拆分为 `components/chat/*`，类名前缀 `kf-*`。

| 字段 | 值 |
|---|---|
| **产品** | KnowFlow（anykb）— 私有 RAG 知识库 + 透明 Agent |
| **视觉方向** | ChatGPT-inspired monochrome：白/浅灰底，炭黑深色，黑白主按钮，大圆角 Composer |
| **主题** | Light-first + Dark |
| **无障碍** | WCAG AA（正文 ≥ 4.5:1，大字 / 图标 ≥ 3:1） |
| **设计系统日期** | 2026-08-05 |
| **实施状态** | v5.6：对齐 ChatGPT 气质（非像素级抄袭） |
| **UI 设计师** | Cursor UI Designer |

---

## 0. 诊断摘要（历史 → 已解决）

v3 曾并行三套 Token；v4 收敛语义 RGB。  
**v5**：引入 `--kf-*` 为规范 Token，旧名（`--canvas` / `--brand` 等）为兼容别名；Chat 类名 `ak-*` → `kf-*`，DOM 拆到 `components/chat/`。

---

## 1. 设计基础

### 1.1 色彩系统

#### 品牌主色（Monochrome / ChatGPT-like）

| Token | Light | Dark | 用途 |
|---|---|---|---|
| `kf-brand` | `#0D0D0D` | `#FFFFFF` | 主按钮、发送 |
| `kf-brand-strong` | `#000000` | `#ECECEC` | Hover |
| `kf-brand-accent` | `#404040` | `#B4B4B4` | 次级点缀 |
| `kf-on-brand` | `#FFFFFF` | `#0D0D0D` | 主色上的字/图标 |

#### 中性（ChatGPT-like）

| Token | Light | Dark |
|---|---|---|
| `kf-canvas` | `#FFFFFF` | `#212121` |
| `kf-surface` | `#FFFFFF` | `#171717` |
| `kf-surface-2` / composer | `#F4F4F4` | `#2F2F2F` |
| `kf-border` | `#E2E2E2` | `#404040` |
| `kf-ink` | `#0D0D0D` | `#ECECEC` |
| `kf-muted` | `#6E6E6E` | `#A3A3A3` |

Composer `border-radius: 1.5rem`；用户气泡浅灰底、无描边；发送钮圆形黑/白实心。

> 语义 `success` / `warning` / `danger` 仍保留彩色。

#### 语义色

| Token | Light | Dark | 对比度要求 |
|---|---|---|---|
| `success` | `#15803D` | `#34A064` | 与相邻背景 ≥ 4.5:1（含文字） |
| `warning` | `#B45309` | `#BC9438` | 不可仅靠颜色传达状态 |
| `danger` | `#DC2626` | `#C86262` | Destructive 按钮需图标或文案 |
| `info` | `#0D0D0D` | `#FFFFFF` | 与 brand 对齐 |

Tailwind：`bg-kf-brand` / `text-kf-ink` 为规范写法；`bg-brand` / `text-ink` 仍可用（别名）。

#### 禁止色 / 反模式

- 禁止默认落到紫色 / indigo 渐变主题
- 禁止暖奶油底 + 衬线大标题 + 陶土强调色组合
- 禁止 glow、多层霓虹阴影、全圆 pill 作为主控件语言
- Chat 内禁止残留硬编码暗色 hex；一律走 Token

#### WCAG AA 已验证组合（目标）

| 组合 | 比例目标 |
|---|---|
| `ink` on `canvas` / `surface` | ≥ 12:1 |
| `muted` on `canvas` | ≥ 4.5:1 |
| `on-brand` on `kf-brand` | ≥ 4.5:1（Light `#0F766E` + 白） |
| Focus ring `brand` @ 2px + 2px offset | 可见，不依赖颜色 alone |

---

### 1.2 排版系统

**策略**：西文用 Plus Jakarta Sans，中文用 Noto Sans SC（`next/font`），等宽用 JetBrains Mono。系统字体作回退。

| 角色 | 字体栈 |
|---|---|
| **UI / 正文** | `Plus Jakarta Sans`, `Noto Sans SC`, `"PingFang SC"`, `"Microsoft YaHei"`, system-ui |
| **等宽** | `JetBrains Mono`, ui-monospace, Menlo, Monaco, Consolas |

CSS 变量：`--font-sans-latin` / `--font-sans-cjk` / `--font-mono`（由 `lib/fonts.ts` 注入）。

#### 比例（4px 基线对齐）

| Token | Size | Line-height | 用途 |
|---|---|---|---|
| `text-xs` | 12px | 16px | 徽章、辅助元数据 |
| `text-sm` | 14px | 20px | 侧栏项、表单说明 |
| `text-base` | 15–16px | 24px | 正文默认（根 `15px`） |
| `text-lg` | 18px | 28px | 区块标题 |
| `text-xl` | 20px | 28px | 对话标题 |
| `text-2xl` | 24px | 32px | 空态标题 |
| `text-3xl` | 30px | 36px | Welcome / Auth 标题 |
| `text-4xl` | 36px | 40px | 营销 Hero（仅桌面） |

**字重**：400（正文）· 500（控件标签）· 600（标题 / 强调）· 700（极少，仅数字指标）

**行宽**：消息气泡 / 报告正文理想 `60–72ch`；侧栏标题截断用 `truncate` + `title`。

---

### 1.3 间距系统

**基础单位**：4px

| Token | 值 | 典型用途 |
|---|---|---|
| `space-1` | 4px | 图标与文字间隙 |
| `space-2` | 8px | 紧凑控件内边距 |
| `space-3` | 12px | 列表项垂直节奏 |
| `space-4` | 16px | 默认内边距 |
| `space-5` | 20px | 卡片内容区 |
| `space-6` | 24px | 区块间距 |
| `space-8` | 32px | 页面分区 |
| `space-12` | 48px | 空态 / Hero 呼吸 |
| `space-16` | 64px | 营销大段间距 |

---

### 1.4 圆角 · 阴影 · 运动

| Token | 值 | 说明 |
|---|---|---|
| `--radius` | `8px`（0.5rem） | 主控件、卡片、输入 |
| `--radius-md` | `6px` | Badge、Chip |
| `--radius-sm` | `4px` | 行内标签 |
| `--radius-full` | 仅 Switch / 进度环 | 禁止用于主按钮 |

| Shadow | 值 | 用途 |
|---|---|---|
| `shadow-soft` | `0 1px 2px rgb(ink/0.04), 0 1px 1px rgb(ink/0.02)` | 默认卡片 |
| `shadow-lift` | `0 4px 12px -2px rgb(ink/0.08), 0 2px 4px rgb(ink/0.04)` | Hover / Popover |
| 禁止 | 多层彩色 glow | — |

| Motion | 时长 | 缓动 |
|---|---|---|
| Press / 微交互 | `160ms` | `ease-out` |
| Popover / Dropdown | `180ms` | `ease-out` |
| Surface / Drawer | `200ms` | `ease-out` |
| 尊重 | `prefers-reduced-motion: reduce` → 时长归零或瞬时 |

**Hover 规则**：用 `border-color` / `background` / `shadow` 反馈；禁止 `scale` 造成布局抖动（`active:scale-[0.97]` 仅允许在按钮按下瞬间）。

---

### 1.5 控件尺寸

| Token | 高度 | 触控目标 |
|---|---|---|
| `--control-h` | 36px | 默认（桌面）；移动端可点击区 ≥ 44px（用 padding 扩大 hit area） |
| `--control-h-sm` | 28px | 行内紧凑（须保证相邻间距） |
| Icon button | 36×36 | Theme toggle、关闭、工具栏 |

焦点：`outline: 2px solid brand.500; outline-offset: 2px` 或 `ring-3 ring-brand/50`。

---

## 2. Token 架构（统一方案）

### 2.1 单一真相源

所有主题色写入 `:root` / `.dark`，**语义名**对外暴露：

```css
:root {
  /* Canvas & surface */
  --canvas: 246 248 251;
  --surface: 255 255 255;
  --surface-2: 241 245 249;
  --border: 221 227 237;
  --border-strong: 194 205 220;

  --ink: 21 32 51;
  --ink-2: 51 65 85;
  --muted: 91 103 124;
  --faint: 148 163 184;

  --brand: 37 99 235;
  --brand-strong: 29 78 216;
  --brand-cyan: 14 165 233;
  --on-brand: 255 255 255;

  --success: 21 128 61;
  --warning: 180 83 9;
  --danger: 220 38 38;

  --radius: 0.5rem;
  --control-h: 36px;
  --control-h-sm: 28px;

  --duration-press: 160ms;
  --duration-popover: 180ms;
  --duration-surface: 200ms;
}

.dark {
  --canvas: 9 14 24;
  --surface: 17 28 43;
  --surface-2: 13 23 38;
  --border: 255 255 255;          /* 使用时加 /0.12 */
  --border-strong: 255 255 255;   /* 使用时加 /0.18 */

  --ink: 241 245 249;
  --ink-2: 203 213 225;
  --muted: 154 168 187;
  --faint: 71 85 105;

  --brand: 96 165 250;
  --brand-strong: 147 197 253;
  --brand-cyan: 56 189 248;
  --on-brand: 7 17 31;

  --success: 74 222 128;
  --warning: 251 191 36;
  --danger: 248 113 113;
}
```

### 2.2 别名状态（P4 完成）

| 类别 | 状态 |
|---|---|
| `--bg` / `--fg` / `--brand-dark` | **已删除**；请用 `--canvas` / `--ink` / `--brand-strong` |
| Tailwind `bg` / `fg` / `brand-dark` | **已删除**；请用 `canvas` / `ink` / `brand-strong` |
| `--chat-*` / `--kf-*` | `--chat-*` 保留为 Chat 全色别名；`--kf-*` 色值别名已删；布局用 `--chat-composer-offset` 等 |
| `--text-subtle` | 保留（避免与 shadcn `--muted` 背景色冲突）；Tailwind 用 `subtle` / `.text-muted` |
| shadcn `--background` / `--primary` | 绑定 `rgb(var(--canvas))` / `rgb(var(--brand))` |

### 2.3 Tailwind 暴露

```ts
colors: {
  canvas: "rgb(var(--canvas) / <alpha-value>)",
  surface: "rgb(var(--surface) / <alpha-value>)",
  "surface-2": "rgb(var(--surface-2) / <alpha-value>)",
  ink: "rgb(var(--ink) / <alpha-value>)",
  subtle: "rgb(var(--text-subtle) / <alpha-value>)",
  brand: "rgb(var(--brand) / <alpha-value>)",
  "brand-strong": "rgb(var(--brand-strong) / <alpha-value>)",
  "on-brand": "rgb(var(--on-brand) / <alpha-value>)",
  // …semantic + shadcn full-color vars
}
```

---

## 3. 组件库

### 3.1 基础组件（唯一 API）

| 组件 | 变体 | 规格 |
|---|---|---|
| **Button** | `default` / `secondary` / `outline` / `ghost` / `destructive` / `link` | 高 36；`rounded-lg`；主色对比 ≥ 5.1:1 |
| **Input / Textarea** | default / error / disabled | 边框 `border`；focus → brand ring |
| **Select** | Radix | 触发器与 Input 同高；选项 `shadow-lift` |
| **Badge** | neutral / brand / success / warning / danger | `rounded-md` + 可见边框（非 pill） |
| **Card** | static / interactive | 默认无 hover 抬升；仅可点击卡片用 `shadow-lift` |
| **Dialog / Sheet / AlertDialog** | — | Header / Body / Footer 分区；Esc + 焦点陷阱 |
| **Tabs** | underline | 选中态底边 brand，不用填充 pill |
| **Switch** | — | 唯一保留 pill；hit area ≥ 44×24 |
| **Toast / StateView** | success / error / empty / loading | 文案 + 图标，不单靠色 |
| **Skeleton** | — | `surface-2` 脉冲；`prefers-reduced-motion` 关闭动画 |

### 3.2 领域组件

| 组件 | 职责 | 视觉要点 |
|---|---|---|
| **Brand** | Logo + Wordmark | 蓝青渐变方标 `rounded-lg`；三档 sm/md/lg |
| **Chat shell** | 侧栏 + 顶栏 + 主区 + Composer | Canvas 上轻 brand 顶部 wash（≤ 8% 透明度） |
| **MessageBubble** | 用户 / 助手消息 | 用户：brand 淡底；助手：surface + 引用条 |
| **ThinkingChain** | 透明 Agent 步骤 | 时间线 + 状态点（running / done / error） |
| **Composer** | KB / 模型 / 附件 / 发送 / 上下文环 | 结构化边框面板；发送按钮方形主色 |
| **ContextUsageRing** | Token 用量 | 圆形进度；hover/focus 显示详情；非假按钮 |
| **ReportView** | Markdown 报告 | 清晰标题层级；citation chip |
| **AdminPageShell** | 管理页壳 | 与 `app-page` 同一页眉语言 |

### 3.3 组件状态矩阵（全组件必备）

| 状态 | 要求 |
|---|---|
| Default | Token 色，无硬编码 |
| Hover | 160ms；边框或底色变化 |
| Active / Pressed | 轻微压感（可选 scale 0.97） |
| Focus-visible | 清晰环；键盘可达 |
| Disabled | opacity 0.5；`pointer-events-none` |
| Loading | 禁用重复提交；spinner 或文案 |
| Error | 边框 danger + 文案紧邻字段 |
| Empty | 一句说明 + 一个主行动 |

### 3.4 废弃 / 合并清单

| 现状 | 决策 |
|---|---|
| `.admin-btn-*` / `.btn-*` | **已删除** → `Button` / `buttonVariants` |
| 自定义 `Dialog.tsx` vs `ui/dialog` | 统一 Radix `ui/dialog` |
| 未使用的 `Sidebar.tsx` | 删除或改为导出 Chat 侧栏 |
| Chat 硬编码 dark hex + `!important` 桥 | Token 化后删除覆盖层 |
| 命名 `kf-*` / anykb / dcmf 混用 | **渐进**：新类用语义名；旧 `kf-*` 保留至下一次领域重构 |

---

## 4. 布局与关键界面

### 4.1 断点

| 名称 | 范围 | 布局行为 |
|---|---|---|
| Mobile | 320–639 | 单栏；侧栏 → Sheet；Composer 贴底 |
| Tablet | 640–1023 | 可折叠侧栏；双栏可选 |
| Desktop | 1024–1279 | 固定侧栏 + 主区 |
| Wide | 1280+ | 主内容 `max-w` 约束；Insight 面板可常驻 |

### 4.2 Chat 工作区（主构图）

```
┌──────────┬─────────────────────────────┬────────────┐
│ Sidebar  │ Topbar (title + utilities)  │  Insight   │
│ Brand    ├─────────────────────────────┤  (optional)│
│ New chat │                             │  Thinking  │
│ Search   │     Message thread          │  Sources   │
│ Recents  │                             │            │
│ Account  │     Composer (sticky)       │            │
└──────────┴─────────────────────────────┴────────────┘
```

- **第一视口焦点**：对话内容 + Composer，不是仪表盘卡片墙
- Draft `/c`：居中大 Composer + 一句标题 + 少量 starter（≤ 4）
- 检索事件、来源、导出：内联在助手回答下方，不进顶栏

### 4.3 非 Chat 页壳

统一 `app-page`：

- Sticky header `h-14`：Brand · 导航 · Theme · 主 CTA
- 内容 `max-w-7xl` + 水平 `px-4 sm:px-6 lg:px-8`
- 背景：`canvas` + 可选极淡 brand wash（顶部 ≤ 18rem 淡出）

### 4.4 Auth

- Desktop：左侧 BrandPanel（产品叙事）+ 右侧表单
- Mobile：隐藏 BrandPanel，顶部 Brand + 表单全宽
- 表单控件全部走统一 Input / Button 规格

### 4.5 Welcome（营销）

Hero 预算（遵守品牌优先）：

1. Brand（hero 级信号）
2. 一句价值主张
3. 一句支撑说明
4. 一组 CTA（开始 / 登录）
5. 一个产品实境视觉（工作台截图或 BrandPanel 式预览）— 全宽平面，非 inset 卡片拼贴

禁止 Hero 内堆：统计条、日程、地址、促销 chip 云。

---

## 5. 无障碍标准

### WCAG AA

- 正文对比 ≥ 4.5:1；大文本 ≥ 3:1
- 全功能键盘可达；逻辑 Tab 序 = 视觉序
- 图标按钮必须 `aria-label`
- 表单：可见 `<label>`；错误与字段 `aria-describedby` 关联
- 焦点不可被 `outline-none` 吃掉（除非提供等价 `focus-visible` 环）

### 包容性

- 触控目标 ≥ 44×44（移动）
- `prefers-reduced-motion` 关闭非必要动画
- 支持浏览器文字缩放至 200% 不破版
- 状态不只靠颜色（思考链用图标 + 文案）
- 上下文用量环：可聚焦的 informational 控件，非假 button

---

## 6. 响应式与性能

- 图片：WebP / 适当尺寸；营销图 `priority` 仅 Hero
- 动画：优先 `transform` / `opacity`
- 异步区：预留高度或 Skeleton，避免 CLS
- CSS：删除 Chat `!important` 覆盖森林，降低特异性战争
- 图标：统一 Lucide SVG，禁止 emoji 充当 UI 图标

---

## 7. 开发者交付

### 7.1 实施优先级

| 阶段 | 内容 | 验收 |
|---|---|---|
| **P0** ✅ | 合并 Token 到单一 `:root` / `.dark`；shadcn 变量绑定语义色 | `npm run build` 通过；别名经语义层解析 |
| **P1** ✅ | Chat 去掉硬编码 hex 与属性桥；Composer / Sidebar 用语义类 | 无 `bg-[#]` / slate 桥；控件走 surface/brand |
| **P2** ✅ | 按钮 / Dialog 统一到 `components/ui`；删死代码 Sidebar / ChatBox | `ConfirmDialog` + `Button` 为规范 API |
| **P2b** ✅ | 全站迁完 `admin-btn-*` 并删除 CSS 别名 | 零 `admin-btn` 残留 |
| **P3** ✅ | Welcome Hero 按预算收紧；Admin 工具类改 Token | Hero 五件套；admin/app-page 用 canvas/ink |
| **P4** ✅ | 删除 legacy 别名（`--bg`/`--fg`/`--brand-dark`） | 全站仅语义 Token + shadcn 绑定 |
| **Cleanup** ✅ | Chat 去冲突 `!important`；`ConfirmDialog` 文件化；toolbar/row → Button | `npm run build`；仅 motion `!important` |

### 7.2 设计 QA 清单

- [x] Light / Dark 关键页截图：Welcome、Login、Register、Chat、KB、Settings、Admin（看板/用户/知识库）
- [x] 主按钮对比度 ≥ 5.1:1（Light 5.17 / Dark 7.45）
- [x] 焦点环：Button / Select / Input / Switch / admin-icon-action / app-nav-link 均有 `focus-visible:ring`；KB 删除按钮补 `focus-visible:opacity-100`
- [x] 375 / 768 / 1024 / 1440 关键页无横向溢出（Welcome / Login / Chat / KB / Settings）
- [x] Composer、Select、Theme toggle 交互态抽查（Chat Composer + Theme toggle）
- [x] `prefers-reduced-motion` 规则存在于 `globals.css`
- [x] 无 emoji 图标；Lucide 尺寸一致（默认 16/20）

### 7.3 文件归属

| 文件 | 职责 |
|---|---|
| `app/globals.css` | 唯一 Token + 全局工具；目标 < 现体积 |
| `tailwind.config.ts` | 语义色与 motion 映射 |
| `components/ui/*` | 唯一基础组件库 |
| `components/Brand.tsx` | 品牌锁定 |
| `design-system.md` | 本规格（真相源） |
| `design-qa.md` | 每次视觉变更的 QA 记录 |

---

## 8. 成功指标

| 指标 | 目标 |
|---|---|
| Token / 组件一致性 | ≥ 95% 界面元素走语义 Token |
| 无障碍 | WCAG AA；主按钮 ≥ 5.1:1 |
| 设计返工 | 按本规格实现后修订率 ≤ 10% |
| 设计债务 | 零并行按钮 API；零 Chat hex 覆盖层 |
| 响应式 | 上述断点布局完整可用 |

---

## 附录 A · 快速对照（给实现者）

```
主色        #2563EB (light) / #60A5FA (dark)
画布        #F6F8FB / #090E18
表面        #FFFFFF / #111C2B
主文字      #152033 / #F1F5F9
辅助文字    #5B677C / #9AA8BB
圆角        8px
控件高      36px
阴影        soft / lift 两档
动效        160–200ms ease-out
字体        系统 + PingFang / YaHei
图标        Lucide only
```

## 附录 B · 反模式速查

| 不要 | 要 |
|---|---|
| 三套 Token 各写各的 | 一套语义 Token |
| 紫色玻璃拟态 | 蓝青企业清晰风 |
| Pill 主按钮 | `rounded-lg` 方形控件 |
| Hover 放大位移布局 | 颜色 / 边框 / 轻阴影 |
| Emoji 当图标 | Lucide SVG |
| Chat 硬编码暗色 hex | `bg-surface` / Token |
| Hero 塞满统计与 chip | Brand + 一句话 + CTA + 一图 |

---

**实施状态**：P0–P4 + Cleanup 已全部落地  
**QA 流程**：变更后更新 `design-qa.md`，双主题 + 四断点目视签收
```
