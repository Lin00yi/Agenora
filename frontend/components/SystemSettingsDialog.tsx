"use client";

/**
 * The settings workspace owns personal, model and memory configuration.
 * Knowledge bases live on /kbs as a first-class destination.
 */

import { toast } from "@/lib/toast";
import {
  AlertTriangle,
  BrainCircuit,
  Download,
  Info,
  SlidersHorizontal,
  Trash2,
  User as UserIcon,
} from "lucide-react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useState } from "react";

import AppModal from "@/components/AppModal";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useTheme, type Theme } from "@/components/ThemeProvider";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  changePassword,
  deleteAccount,
  updateProfile,
  type User,
} from "@/lib/auth";
import { cn } from "@/lib/cn";
import {
  deleteAllConversations,
  exportConversations,
} from "@/lib/conversations-api";

const ModelSettingsModule = dynamic(
  () => import("@/components/settings/ModelSettingsModule").then((module) => module.ModelSettingsModule),
  { ssr: false }
);
const MemorySystemModule = dynamic(
  () => import("@/components/settings/MemorySystemModule").then((module) => module.MemorySystemModule),
  { ssr: false }
);

type SettingsModule = "personal" | "model" | "memory" | "about";
type PersonalTab = "general" | "appearance" | "account" | "data";

const MODULES: { key: SettingsModule; label: string; Icon: typeof UserIcon }[] = [
  { key: "personal", label: "个人", Icon: UserIcon },
  { key: "model", label: "模型", Icon: SlidersHorizontal },
  { key: "memory", label: "记忆系统", Icon: BrainCircuit },
  { key: "about", label: "关于", Icon: Info },
];

const PERSONAL_TABS: { key: PersonalTab; label: string }[] = [
  { key: "general", label: "通用" },
  { key: "appearance", label: "外观" },
  { key: "account", label: "账号" },
  { key: "data", label: "数据迁移" },
];

type Props = {
  open: boolean;
  onClose: () => void;
  user: User;
  onUserChanged: (u: User) => void;
};

export default function SystemSettingsDialog({
  open,
  onClose,
  user,
  onUserChanged,
}: Props) {
  const [module, setModule] = useState<SettingsModule>("personal");
  const [personalTab, setPersonalTab] = useState<PersonalTab>("general");
  const [confirmClear, setConfirmClear] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const router = useRouter();

  const doClear = async () => {
    setClearing(true);
    try {
      await deleteAllConversations();
      toast.success("已清空所有对话");
      setConfirmClear(false);
      window.location.reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "清空失败");
      setClearing(false);
    }
  };

  const doDelete = async () => {
    setDeleting(true);
    try {
      await deleteAccount();
      toast.success("账号已删除");
      onClose();
      router.replace("/login");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
      setDeleting(false);
    }
  };

  return (
    <>
      <AppModal
        open={open}
        onOpenChange={(next) => {
          if (!next) onClose();
        }}
        bare
        size="xl"
        className="h-[min(760px,calc(100dvh-2rem))] max-w-6xl sm:max-w-6xl"
        showCloseButton
      >
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden sm:flex-row">
          <nav className="flex w-full shrink-0 gap-1 overflow-x-auto border-b border-surface-border/70 bg-surface-2/50 p-2 sm:w-48 sm:flex-col sm:overflow-visible sm:border-b-0 sm:border-r">
            <div className="hidden px-2 py-2 text-xs font-semibold text-muted sm:block">
              设置
            </div>
            {MODULES.map(({ key, label, Icon }) => {
              const active = module === key;
              return (
                <button
                  key={key}
                  onClick={() => setModule(key)}
                  className={cn(
                    "flex h-[var(--control-h)] shrink-0 cursor-pointer items-center gap-2 rounded-md border border-transparent px-3 text-sm font-medium transition-[background-color,border-color,color,box-shadow] duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30 sm:w-full sm:px-2",
                    active
                      ? "border-brand/25 bg-surface text-ink shadow-sm"
                      : "text-muted hover:border-surface-border/80 hover:bg-surface/75 hover:text-ink"
                  )}
                  aria-pressed={active}
                  type="button"
                >
                  <Icon className={cn("h-4 w-4", active ? "text-brand" : "text-muted")} />
                  {label}
                </button>
              );
            })}
          </nav>

          <div className="flex min-h-0 flex-1 flex-col">
            <header className="flex h-14 shrink-0 items-center border-b border-surface-border/70 bg-surface px-5 pr-14">
              <h2 className="text-[15px] font-semibold tracking-tight">
                {MODULES.find((item) => item.key === module)?.label}
              </h2>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto">
              {module === "personal" && (
                <PersonalModule
                  activeTab={personalTab}
                  onTabChange={setPersonalTab}
                  user={user}
                  onUserChanged={onUserChanged}
                  onRequestClear={() => setConfirmClear(true)}
                  onRequestDelete={() => setConfirmDelete(true)}
                />
              )}
              {module === "model" && <ModelSettingsModule embedded />}
              {module === "memory" && <MemorySystemModule embedded />}
              {module === "about" && (
                <div className="px-5 py-5 sm:px-6">
                  <AboutTab />
                </div>
              )}
            </div>
          </div>
        </div>
      </AppModal>

      <ConfirmDialog
        open={confirmClear}
        onOpenChange={setConfirmClear}
        title="清空所有对话？"
        description="所有对话历史将被永久删除，无法恢复。KB 和账号设置不受影响。"
        variant="danger"
        confirmLabel="确认清空"
        onConfirm={doClear}
        busy={clearing}
      />

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="删除账号？"
        description="账号、对话、我所拥有的 KB 和上传文档都会被永久删除。此操作不可恢复。"
        variant="danger"
        confirmLabel="确认删除账号"
        onConfirm={doDelete}
        busy={deleting}
      />
    </>
  );
}

function PersonalModule({
  activeTab,
  onTabChange,
  user,
  onUserChanged,
  onRequestClear,
  onRequestDelete,
}: {
  activeTab: PersonalTab;
  onTabChange: (tab: PersonalTab) => void;
  user: User;
  onUserChanged: (user: User) => void;
  onRequestClear: () => void;
  onRequestDelete: () => void;
}) {
  return (
    <div className="px-5 py-5 sm:px-6">
      <Tabs
        value={activeTab}
        onValueChange={(value) => onTabChange(value as PersonalTab)}
        className="gap-0"
      >
        <div className="mb-6 max-w-full overflow-x-auto pb-1">
          <TabsList
            aria-label="个人设置"
          >
            {PERSONAL_TABS.map(({ key, label }) => (
              <TabsTrigger
                key={key}
                value={key}
              >
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>

        <TabsContent value="general" className="m-0">
          <GeneralTab user={user} onUserChanged={onUserChanged} />
        </TabsContent>
        <TabsContent value="appearance" className="m-0">
          <AppearanceTab />
        </TabsContent>
        <TabsContent value="account" className="m-0">
          <AccountTab user={user} onRequestDelete={onRequestDelete} />
        </TabsContent>
        <TabsContent value="data" className="m-0">
          <DataTab onRequestClear={onRequestClear} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Personal: 通用 / 外观
// ---------------------------------------------------------------------------
function GeneralTab({
  user,
  onUserChanged,
}: {
  user: User;
  onUserChanged: (u: User) => void;
}) {
  const initialName =
    user.display_name?.trim() || user.email.split("@")[0];
  const [name, setName] = useState(initialName);
  const [saving, setSaving] = useState(false);

  const dirty = name.trim() !== initialName && name.trim().length >= 1;

  const save = async () => {
    const v = name.trim();
    if (!v) {
      toast.error("名称不能为空");
      return;
    }
    setSaving(true);
    try {
      const updated = await updateProfile(v);
      onUserChanged(updated);
      toast.success("已保存");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <Field label="显示名称" hint="出现在侧边栏底部、对话署名等位置">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={64}
          placeholder={user.email.split("@")[0]}
          className={inputClass}
        />
        <div className="mt-2 flex justify-end">
          <Button
            onClick={save}
            disabled={!dirty || saving}
            type="button"
          >
            {saving ? "保存中..." : "保存"}
          </Button>
        </div>
      </Field>

    </div>
  );
}

function AppearanceTab() {
  const { theme, setTheme } = useTheme();

  return (
    <div>
      <h3 className="text-balance text-sm font-semibold text-ink">主题</h3>
      <p className="mt-1 text-pretty text-sm leading-6 text-muted">
        选择应用外观。跟随系统会根据设备偏好自动切换。
      </p>
      <div className="mt-5 grid gap-4 sm:grid-cols-3">
        <ThemePreview value="system" label="系统" selected={theme === "system"} onSelect={setTheme} />
        <ThemePreview value="light" label="浅色" selected={theme === "light"} onSelect={setTheme} />
        <ThemePreview value="dark" label="深色" selected={theme === "dark"} onSelect={setTheme} />
      </div>
    </div>
  );
}

function ThemePreview({
  value,
  label,
  selected,
  onSelect,
}: {
  value: Theme;
  label: string;
  selected: boolean;
  onSelect: (theme: Theme) => void;
}) {
  const dark = value === "dark";
  const system = value === "system";

  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-label={`切换为${label}主题`}
      onClick={() => onSelect(value)}
      className={cn(
        "group rounded-xl text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40 focus-visible:ring-offset-2 focus-visible:ring-offset-surface",
        selected && "ring-2 ring-brand"
      )}
    >
      <span className="relative block aspect-[4/3] overflow-hidden rounded-xl border border-surface-border bg-zinc-100">
        {system ? (
          <span className="absolute inset-0 flex" aria-hidden="true">
            <span className="w-1/2 bg-zinc-100" />
            <span className="w-1/2 bg-zinc-700" />
          </span>
        ) : (
          <span className={cn("absolute inset-0", dark ? "bg-zinc-700" : "bg-zinc-100")} aria-hidden="true" />
        )}
        <span className="absolute inset-x-[9%] top-[22%] h-[70%] overflow-hidden rounded-t-[1.15rem] bg-white shadow-sm">
          <span className="mx-auto mt-[12%] block h-2 w-[46%] rounded-full bg-zinc-300" />
          <span className="mx-[8%] mt-[5%] block h-1.5 rounded-full bg-zinc-200" />
          <span className="mt-[7%] block border-t border-zinc-100" />
          <span className="mx-[8%] mt-[6%] block h-2 w-[34%] rounded-full bg-zinc-300" />
          <span className="mx-[8%] mt-[5%] block h-1.5 w-[48%] rounded-full bg-zinc-200" />
          <span className="mt-[7%] block border-t border-zinc-100" />
          <span className="mx-[8%] mt-[6%] block h-2 w-[34%] rounded-full bg-zinc-300" />
        </span>
      </span>
      <span className={cn("mt-3 block text-center text-sm font-medium", selected ? "text-ink" : "text-muted")}>
        {label}
      </span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Tab: 账号
// ---------------------------------------------------------------------------
function AccountTab({
  user,
  onRequestDelete,
}: {
  user: User;
  onRequestDelete: () => void;
}) {
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (newPw.length < 8) {
      toast.error("新密码至少 8 位");
      return;
    }
    if (newPw !== confirmPw) {
      toast.error("两次输入的新密码不一致");
      return;
    }
    setSaving(true);
    try {
      await changePassword(oldPw, newPw);
      toast.success("密码已更新");
      setOldPw("");
      setNewPw("");
      setConfirmPw("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "修改失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <Field label="邮箱（登录账号）">
        <input
          type="email"
          value={user.email}
          readOnly
          className={cn(inputClass, "cursor-not-allowed bg-surface text-muted")}
        />
        <p className="mt-2 text-xs text-muted">邮箱目前不支持修改。</p>
      </Field>

      <div className="rounded-lg border border-surface-border/75 bg-surface p-4 shadow-sm">
        <h3 className="mb-3 text-sm font-semibold">修改密码</h3>
        <div className="space-y-3">
          <Field label="当前密码">
            <input
              type="password"
              value={oldPw}
              onChange={(e) => setOldPw(e.target.value)}
              className={inputClass}
              autoComplete="current-password"
            />
          </Field>
          <Field label="新密码（至少 8 位）">
            <input
              type="password"
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              className={inputClass}
              autoComplete="new-password"
              minLength={8}
            />
          </Field>
          <Field label="再次输入新密码">
            <input
              type="password"
              value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)}
              className={inputClass}
              autoComplete="new-password"
            />
          </Field>
          <div className="flex justify-end pt-1">
            <Button
              onClick={submit}
              disabled={!oldPw || !newPw || saving}
              type="button"
            >
              {saving ? "提交中..." : "更新密码"}
            </Button>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-danger/30 bg-danger/5 p-4 shadow-sm">
        <div className="flex items-start gap-3">
          <span className="admin-icon-tile admin-icon-tile-danger">
            <AlertTriangle className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-danger">危险操作</h3>
            <p className="mt-1 text-xs leading-5 text-muted">
              删除账号会同时删除你的对话、拥有的知识库和上传文档，且无法恢复。
            </p>
            <Button
              onClick={onRequestDelete}
              className="mt-4"
              variant="destructive"
              type="button"
            >
              删除我的账号
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Personal: 数据迁移
// ---------------------------------------------------------------------------
function DataTab({ onRequestClear }: {
  onRequestClear: () => void;
}) {
  const [exporting, setExporting] = useState(false);

  const doExport = async () => {
    setExporting(true);
    try {
      await exportConversations();
      toast.success("已开始下载");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "导出失败");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-5">
      <DataRow
        title="导出对话历史"
        description="下载所有对话和消息为 JSON，方便迁移或本地备份。"
        action={
          <Button
            onClick={doExport}
            disabled={exporting}
            variant="ghost"
            type="button"
          >
            <Download className="h-4 w-4" />
            {exporting ? "导出中..." : "导出 JSON"}
          </Button>
        }
      />

      <DataRow
        title="清空所有对话"
        description="不可恢复，但 KB / 账号配置不受影响。"
        action={
          <Button onClick={onRequestClear} variant="destructive" type="button">
            <Trash2 className="h-4 w-4" />
            清空对话
          </Button>
        }
      />

    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: 关于
// ---------------------------------------------------------------------------
function AboutTab() {
  return (
    <div className="space-y-4 text-sm">
      <div>
        <h3 className="font-medium">Agenora</h3>
        <p className="mt-1 text-muted">
          Private knowledge base and transparent agents — grounded answers you can trace.
        </p>
      </div>

      <dl className="grid grid-cols-[100px_1fr] gap-y-2 text-xs">
        <dt className="text-muted">版本</dt>
        <dd>v3-M5</dd>
        <dt className="text-muted">协议</dt>
        <dd>MIT</dd>
        <dt className="text-muted">仓库</dt>
        <dd className="break-all text-brand">
          <a
            href="https://github.com/Lin00yi/Agenora"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:underline"
          >
            github.com/Lin00yi/Agenora
          </a>
        </dd>
      </dl>

      <div className="rounded-lg border border-surface-border/70 bg-surface p-4 text-xs leading-5 text-muted shadow-sm">
        <p>
          Agenora 是个人维护的本地优先知识库与 Agent 项目，数据保存在你自己的数据库中。
          使用本服务即表示你了解：LLM 输出可能不准确；上传到知识库的文档会经过
          embedding 提供商处理。详见仓库 README。
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------
const inputClass =
  "admin-input";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <label className="mb-1.5 block text-xs font-medium text-muted">
        {label}
      </label>
      {children}
      {hint && <p className="mt-1.5 text-xs text-muted">{hint}</p>}
    </div>
  );
}

function DataRow({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-surface-border/80 bg-surface p-4 shadow-sm transition-[background-color,border-color,box-shadow] duration-200 hover:border-brand/25 hover:bg-surface-2/45 hover:shadow-[0_10px_24px_rgb(15_23_42/0.07)] sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 flex-1">
        <h3 className="text-sm font-medium">{title}</h3>
        <p className="mt-1 text-xs leading-5 text-muted">{description}</p>
      </div>
      <div className="flex shrink-0 justify-end">{action}</div>
    </div>
  );
}
