"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { CheckCircle2, CircleAlert, FolderCog, Globe2, Network, Plus, RefreshCw, Send, ShieldCheck, Terminal, Upload } from "lucide-react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { StateView } from "@/components/ui/state-view";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import {
  getMcpCatalog,
  publishMcpCatalog,
  saveMcpCatalogDraft,
  testMcpServer,
  type AdminMcpCatalog,
  type McpCatalogPayload,
  type McpServerHealth,
} from "@/lib/admin-api";
import { toast } from "@/lib/toast";

const EMPTY_CATALOG: McpCatalogPayload = { servers: [], capabilities: [], contracts: [], plugins: [] };

// The built-in orders plugin owns these contracts. Discovery never grants an
// arbitrary remote tool access to the orders agent: a provider must explicitly
// implement one of these reviewed interfaces (or ship a future Agent plugin).
const ORDER_CONTRACT_BY_TOOL: Record<string, string> = {
  list_orders: "commerce.orders.list",
  get_order: "commerce.orders.get",
  list_refunds: "commerce.refunds.list",
  get_refund: "commerce.refunds.get",
  prepare_refund: "commerce.refund.prepare",
  confirm_refund: "commerce.refund.confirm",
};
const ORDER_TOOL_BY_CONTRACT: Record<string, string> = Object.fromEntries(
  Object.entries(ORDER_CONTRACT_BY_TOOL).map(([tool, contract]) => [contract, tool])
);

export default function McpManagementPage() {
  return <McpManagementModule />;
}

/** Reused inside the administrator-only system settings dialog. */
export function McpManagementModule({ embedded = false }: { embedded?: boolean }) {
  const [activeTab, setActiveTab] = useState<"mcp" | "restricted">("mcp");
  const [snapshot, setSnapshot] = useState<AdminMcpCatalog | null>(null);
  const [catalogText, setCatalogText] = useState("");
  const [secretsText, setSecretsText] = useState("{}");
  const [serverId, setServerId] = useState("");
  const [health, setHealth] = useState<McpServerHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"save" | "test" | "publish" | null>(null);
  const [error, setError] = useState("");
  const [publishOpen, setPublishOpen] = useState(false);
  const [newServerId, setNewServerId] = useState("");
  const [newTransport, setNewTransport] = useState<"stdio" | "streamable_http">("streamable_http");
  const [newEndpoint, setNewEndpoint] = useState("");
  const [newCommand, setNewCommand] = useState("");
  const [newArgs, setNewArgs] = useState<string[]>([]);
  const [newEnvironment, setNewEnvironment] = useState<Array<{ key: string; value: string }>>([]);
  const [newInheritedEnvironment, setNewInheritedEnvironment] = useState<string[]>(["PATH"]);
  const [newCwd, setNewCwd] = useState("");
  const [newBearerToken, setNewBearerToken] = useState("");
  const [newTools, setNewTools] = useState("");
  const [restrictedServerId, setRestrictedServerId] = useState("");
  const [restrictedMappings, setRestrictedMappings] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const next = await getMcpCatalog();
      setSnapshot(next);
      setCatalogText(JSON.stringify(next.catalog, null, 2));
      setServerId(String(next.catalog.servers[0]?.id ?? ""));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取 MCP 配置");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const parsed = useMemo(() => parseDraft(catalogText, secretsText), [catalogText, secretsText]);
  const server = parsed.ok ? parsed.catalog.servers.find((item) => String(item.id) === serverId) : undefined;

  const save = async () => {
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    setBusy("save");
    setError("");
    try {
      const next = await saveMcpCatalogDraft({ catalog: parsed.catalog, secrets: parsed.secrets });
      setSnapshot(next);
      setCatalogText(JSON.stringify(next.catalog, null, 2));
      setSecretsText("{}");
      setServerId(String(next.catalog.servers[0]?.id ?? ""));
      toast.success("MCP 草稿已保存，尚未影响线上能力。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存 MCP 草稿失败");
    } finally {
      setBusy(null);
    }
  };

  const test = async () => {
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    if (!server) {
      setError("请选择需要测试的 MCP 服务。");
      return;
    }
    setBusy("test");
    setError("");
    try {
      const next = await testMcpServer({ server, secrets: parsed.secrets });
      setHealth(next);
      if (next.healthy) toast.success(`连接正常，发现 ${next.tool_count ?? 0} 个 allowlist 工具。`);
      else setError(next.error ?? "MCP 服务不可用");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "MCP 连通性测试失败");
    } finally {
      setBusy(null);
    }
  };

  const addService = async () => {
    const id = newServerId.trim().toLowerCase().replace(/\s+/g, "-");
    const endpoint = newEndpoint.trim();
    const command = newCommand.trim();
    const tools = parseToolNames(newTools);
    if (!id || !tools.length || (newTransport === "streamable_http" && !endpoint) || (newTransport === "stdio" && !command)) {
      setError(newTransport === "stdio" ? "请填写服务标识、启动命令和至少一个工具名。" : "请填写服务标识、HTTPS 地址和至少一个工具名。");
      return;
    }
    let parsedEndpoint: URL | null = null;
    if (newTransport === "streamable_http") {
      try {
        parsedEndpoint = new URL(endpoint);
      } catch {
        setError("服务地址格式不正确。");
        return;
      }
      if (parsedEndpoint.protocol !== "https:") {
        setError("管理页面只允许 HTTPS Streamable HTTP 服务。");
        return;
      }
    }
    const base = snapshot?.source === "environment" || !parsed.ok ? EMPTY_CATALOG : parsed.catalog;
    if (base.servers.some((item) => String(item.id) === id)) {
      setError(`服务标识 ${id} 已存在，请换一个标识或使用高级编辑修改。`);
      return;
    }
    const secretRef = `${id}_bearer`;
    const environment = Object.fromEntries(
      newEnvironment.map(({ key, value }) => [key.trim(), value]).filter(([key]) => key)
    );
    const server: Record<string, unknown> = {
      id,
      transport: newTransport,
      enabled: true,
      allowed_tools: tools,
      identity_argument: "actor_id",
      ...(newTransport === "streamable_http" ? {
        endpoint: parsedEndpoint?.toString(),
        ...(newBearerToken.trim() ? { secret_headers: { Authorization: secretRef } } : {}),
      } : {
        command,
        args: newArgs.map((value) => value.trim()).filter(Boolean),
        ...(newCwd.trim() ? { cwd: newCwd.trim() } : {}),
        ...(Object.keys(environment).length ? { environment } : {}),
        inherit_environment: newInheritedEnvironment.map((value) => value.trim()).filter(Boolean),
      }),
    };
    const catalog: McpCatalogPayload = {
      servers: [...base.servers, server],
      capabilities: base.capabilities,
      contracts: base.contracts,
      plugins: base.plugins,
    };
    const previousSecrets = parsed.ok ? parsed.secrets : {};
    const secrets = newBearerToken.trim() ? { ...previousSecrets, [secretRef]: newBearerToken.trim() } : previousSecrets;
    setBusy("save");
    setError("");
    try {
      const next = await saveMcpCatalogDraft({ catalog, secrets });
      setSnapshot(next);
      setCatalogText(JSON.stringify(next.catalog, null, 2));
      setSecretsText("{}");
      setServerId(id);
      setNewServerId("");
      setNewEndpoint("");
      setNewCommand("");
      setNewArgs([]);
      setNewEnvironment([]);
      setNewInheritedEnvironment(["PATH"]);
      setNewCwd("");
      setNewTransport("streamable_http");
      setNewBearerToken("");
      setNewTools("");
      setRestrictedServerId(id);
      toast.success("MCP 连接已加入草稿；如需让 Agent 使用，请转到“受限 MCP”映射能力契约。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存 MCP 服务失败");
    } finally {
      setBusy(null);
    }
  };

  const addRestrictedBindings = async () => {
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    const server = parsed.catalog.servers.find((item) => String(item.id) === restrictedServerId);
    const mappings = parseToolMappings(restrictedMappings);
    if (!server || !mappings.length) {
      setError("请选择已配置的 MCP 服务，并至少填写一项“工具=业务契约”映射。");
      return;
    }
    const unsupported = mappings.filter(({ contract }) => !ORDER_TOOL_BY_CONTRACT[contract]);
    if (unsupported.length) {
      setError(`以下契约不属于内置订单受限能力：${unsupported.map(({ contract }) => contract || "未填写").join("、")}。`);
      return;
    }
    const existingExposed = new Set(parsed.catalog.capabilities.map((item) => `${String(item.agent_id)}:${String(item.exposed_name)}`));
    const duplicate = mappings.find(({ contract }) => existingExposed.has(`orders:${ORDER_TOOL_BY_CONTRACT[contract]}`));
    if (duplicate) {
      setError(`订单 Agent 已绑定 ${ORDER_TOOL_BY_CONTRACT[duplicate.contract]}，请先在高级目录编辑中替换现有绑定。`);
      return;
    }
    const tools = Array.from(new Set(mappings.map(({ tool }) => tool)));
    const servers = parsed.catalog.servers.map((item) => String(item.id) === restrictedServerId ? {
      ...item,
      allowed_tools: Array.from(new Set([...(Array.isArray(item.allowed_tools) ? item.allowed_tools.map(String) : []), ...tools])),
    } : item);
    const capabilities = mappings.map(({ tool, contract }) => ({
      id: `${restrictedServerId}.${tool}`,
      contract_id: contract,
      contract_version: 1,
      server_id: restrictedServerId,
      tool_name: tool,
      exposed_name: ORDER_TOOL_BY_CONTRACT[contract],
      agent_id: "orders",
      risk: contract === "commerce.refund.confirm" ? "high_risk_write" : contract === "commerce.refund.prepare" ? "write" : "read",
      ...(contract === "commerce.refund.confirm" ? { policy_id: "refund_confirmation_v1" } : contract === "commerce.refund.prepare" ? { policy_id: "refund_v1" } : {}),
      description: `${ORDER_TOOL_BY_CONTRACT[contract]}（${restrictedServerId}）`,
      input_schema: { type: "object", properties: {} },
    }));
    setBusy("save");
    setError("");
    try {
      const next = await saveMcpCatalogDraft({
        catalog: { ...parsed.catalog, servers, capabilities: [...parsed.catalog.capabilities, ...capabilities] },
        secrets: parsed.secrets,
      });
      setSnapshot(next);
      setCatalogText(JSON.stringify(next.catalog, null, 2));
      setSecretsText("{}");
      setServerId(restrictedServerId);
      setRestrictedMappings("");
      toast.success("受限 MCP 能力已加入草稿，尚未发布到 Agent。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存受限 MCP 草稿失败");
    } finally {
      setBusy(null);
    }
  };

  const discoverNewServiceTools = async () => {
    const id = newServerId.trim().toLowerCase().replace(/\s+/g, "-");
    const endpoint = newEndpoint.trim();
    const command = newCommand.trim();
    if (!id || (newTransport === "streamable_http" && !endpoint) || (newTransport === "stdio" && !command)) {
      setError(newTransport === "stdio" ? "请先填写服务标识和启动命令，再发现工具。" : "请先填写服务标识和 HTTPS 地址，再发现工具。");
      return;
    }
    if (newTransport === "streamable_http") {
      try {
        if (new URL(endpoint).protocol !== "https:") throw new Error();
      } catch {
        setError("服务地址必须是有效的 HTTPS 地址。");
        return;
      }
    }
    const secretRef = `${id}_bearer`;
    setBusy("test");
    setError("");
    try {
      const result = await testMcpServer({
        server: {
          id,
          transport: newTransport,
          enabled: true,
          allowed_tools: [],
          identity_argument: "actor_id",
          ...(newTransport === "streamable_http" ? {
            endpoint,
            ...(newBearerToken.trim() ? { secret_headers: { Authorization: secretRef } } : {}),
          } : {
            command,
            args: newArgs.map((value) => value.trim()).filter(Boolean),
            ...(newCwd.trim() ? { cwd: newCwd.trim() } : {}),
            environment: Object.fromEntries(newEnvironment.map(({ key, value }) => [key.trim(), value]).filter(([key]) => key)),
            inherit_environment: newInheritedEnvironment.map((value) => value.trim()).filter(Boolean),
          }),
        },
        secrets: newBearerToken.trim() ? { [secretRef]: newBearerToken.trim() } : {},
      });
      setHealth(result);
      if (!result.healthy) {
        setError(result.error ?? "MCP 服务不可用");
        return;
      }
      const tools = result.tools ?? [];
      setNewTools(tools.map((tool) => tool.name).join(", "));
      toast.success(`已发现 ${tools.length} 个工具，并带入工具 allowlist。`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "工具发现失败");
    } finally {
      setBusy(null);
    }
  };

  const publish = async () => {
    setBusy("publish");
    setError("");
    try {
      const next = await publishMcpCatalog();
      setSnapshot(next);
      setCatalogText(JSON.stringify(next.catalog, null, 2));
      setPublishOpen(false);
      toast.success(`已发布 MCP catalog v${next.active_version}。`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "发布 MCP catalog 失败");
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return <StateView variant="loading" title="正在读取 MCP 管理配置" description="正在加载可发布的服务与能力目录。" />;
  }

  return (
    <div className={embedded ? "space-y-6 p-5 sm:p-6" : "space-y-6"} aria-busy={busy !== null}>
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-surface-border/70 pb-6">
        <div className="max-w-3xl">
          <p className="text-xs font-semibold text-brand">MCP 管理</p>
          <h2 className="mt-2 text-balance text-2xl font-semibold">MCP 连接与受限能力</h2>
          <p className="mt-2 text-pretty text-sm leading-6 text-muted">
            MCP Tab 只配置连接；只有“受限 MCP”中经过契约映射并发布的能力会挂载到 Agent。身份、密钥和高风险写操作策略始终由 Host 控制。
          </p>
        </div>
        <Button variant="outline" onClick={() => void load()} disabled={busy !== null}>
          <RefreshCw className="mr-2 h-4 w-4" />刷新
        </Button>
      </header>

      <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(12rem,1fr))]">
        <Metric icon={Network} label="草稿版本" value={`v${snapshot?.draft_version ?? 0}`} detail={snapshot?.source === "environment" ? "当前来自环境配置" : "数据库草稿"} />
        <Metric icon={Upload} label="线上版本" value={snapshot?.active_version ? `v${snapshot.active_version}` : "未发布"} detail={snapshot?.published_at ? `发布于 ${new Date(snapshot.published_at).toLocaleString()}` : "仍使用环境回退"} />
        <Metric icon={ShieldCheck} label="密钥引用" value={String(Object.keys(snapshot?.secret_refs ?? {}).length)} detail="仅展示已配置状态，不返回密钥内容" />
      </div>

      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as "mcp" | "restricted")} orientation="vertical" className="gap-0 rounded-xl border border-surface-border/80 bg-surface sm:flex-row">
        <aside className="shrink-0 border-b border-surface-border/70 bg-surface-2/40 p-2 sm:w-52 sm:border-b-0 sm:border-r" aria-label="MCP 管理类别">
          <TabsList className="h-auto w-full flex-col items-stretch bg-transparent p-0" aria-label="MCP 管理类别">
            <TabsTrigger value="mcp" className="w-full flex-none justify-start data-[state=active]:bg-surface data-[state=active]:shadow-sm"><Network />MCP</TabsTrigger>
            <TabsTrigger value="restricted" className="mt-1 w-full flex-none justify-start data-[state=active]:bg-surface data-[state=active]:shadow-sm"><ShieldCheck />受限 MCP</TabsTrigger>
          </TabsList>
          <p className="hidden px-3 pt-4 text-xs leading-5 text-muted sm:block">普通 MCP 只管理连接；受限 MCP 才能挂载给订单 Agent 并执行发布。</p>
        </aside>
        <div className="min-w-0 flex-1 p-5 sm:p-6">
          {error ? <p id="mcp-catalog-error" className="mb-5 flex items-center gap-2 rounded-md border border-danger/25 bg-danger/5 p-3 text-sm text-danger" role="alert"><CircleAlert className="h-4 w-4" />{error}</p> : null}
          <TabsContent value="mcp" className="m-0 space-y-6">
      <section className="admin-panel p-5" aria-labelledby="mcp-quick-add-heading">
        <div>
          <h3 id="mcp-quick-add-heading" className="text-balance text-base font-semibold">连接 MCP 服务</h3>
          <p className="mt-1 text-pretty text-sm leading-6 text-muted">此处只建立 MCP 连接与工具 allowlist，不会自动授予任何 Agent 权限。HTTP 可发布到平台；STDIO 仅在本地开发环境可用，不会在生产管理面执行任意命令。</p>
        </div>
        <fieldset className="mt-5">
          <legend className="text-sm font-medium">连接类型</legend>
          <div className="mt-2 inline-flex rounded-lg border border-surface-border bg-surface-2 p-1">
            <label className={cn("inline-flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors focus-within:ring-2 focus-within:ring-brand focus-within:ring-offset-2", newTransport === "stdio" ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink")}>
              <input className="sr-only" type="radio" name="mcp-transport" value="stdio" checked={newTransport === "stdio"} onChange={() => setNewTransport("stdio")} />
              <Terminal className="h-4 w-4" aria-hidden="true" />STDIO
            </label>
            <label className={cn("inline-flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors focus-within:ring-2 focus-within:ring-brand focus-within:ring-offset-2", newTransport === "streamable_http" ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink")}>
              <input className="sr-only" type="radio" name="mcp-transport" value="streamable_http" checked={newTransport === "streamable_http"} onChange={() => setNewTransport("streamable_http")} />
              <Globe2 className="h-4 w-4" aria-hidden="true" />流式 HTTP
            </label>
          </div>
        </fieldset>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <Field label="服务标识" htmlFor="mcp-new-server-id" hint="例如 inventory 或 crm；保存后不可重复。">
            <input id="mcp-new-server-id" value={newServerId} onChange={(event) => setNewServerId(event.target.value)} className="admin-input" placeholder="inventory" autoComplete="off" />
          </Field>
          {newTransport === "streamable_http" ? (
            <Field label="Streamable HTTP 地址" htmlFor="mcp-new-endpoint" hint="仅允许 HTTPS，例如 https://mcp.example.com/mcp。">
              <input id="mcp-new-endpoint" type="url" value={newEndpoint} onChange={(event) => setNewEndpoint(event.target.value)} className="admin-input font-mono" placeholder="https://mcp.example.com/mcp" autoComplete="off" />
            </Field>
          ) : (
            <Field label="启动命令" htmlFor="mcp-new-command" hint="仅开发环境。例如 npx、uvx 或已安装的 MCP 可执行文件。">
              <input id="mcp-new-command" value={newCommand} onChange={(event) => setNewCommand(event.target.value)} className="admin-input font-mono" placeholder="openai-dev-mcp-server-sqlite" autoComplete="off" />
            </Field>
          )}
          <Field label="工具 allowlist" htmlFor="mcp-new-tools" hint="可先通过“发现工具”自动填入；也可手动用英文逗号分隔。">
            <input id="mcp-new-tools" value={newTools} onChange={(event) => setNewTools(event.target.value)} className="admin-input font-mono" placeholder="list_orders, get_order" autoComplete="off" />
          </Field>
          {newTransport === "streamable_http" ? (
            <Field label="Bearer Token（可选）" htmlFor="mcp-new-token" hint="只在本次提交时写入加密存储，之后不会回显。">
              <input id="mcp-new-token" type="password" value={newBearerToken} onChange={(event) => setNewBearerToken(event.target.value)} className="admin-input" placeholder="Bearer eyJ…" autoComplete="new-password" />
            </Field>
          ) : null}
        </div>
        {newTransport === "stdio" ? <StdioConnectionFields
          args={newArgs}
          environment={newEnvironment}
          inheritedEnvironment={newInheritedEnvironment}
          cwd={newCwd}
          onArgsChange={setNewArgs}
          onEnvironmentChange={setNewEnvironment}
          onInheritedEnvironmentChange={setNewInheritedEnvironment}
          onCwdChange={setNewCwd}
        /> : null}
        <div className="mt-5 flex flex-wrap justify-end gap-3">
          <Button onClick={() => void discoverNewServiceTools()} disabled={busy !== null} variant="outline" type="button"><Send className="mr-2 h-4 w-4" />发现工具</Button>
          <Button onClick={() => void addService()} disabled={busy !== null} type="button"><Plus className="mr-2 h-4 w-4" />加入草稿</Button>
        </div>
      </section>

      <section className="admin-panel p-5" aria-labelledby="mcp-test-heading">
        <h3 id="mcp-test-heading" className="text-balance text-base font-semibold">测试与发现工具</h3>
        <p className="mt-1 text-pretty text-sm leading-6 text-muted">测试只初始化连接并读取工具目录，不会执行任何业务工具。普通 MCP 可以独立保存；需要让订单 Agent 调用时，再到“受限 MCP”完成契约映射。</p>
        <div className="mt-4 flex flex-wrap items-end gap-3">
          <div className="min-w-56 flex-1">
            <label htmlFor="mcp-server-id" className="block text-sm font-medium">已保存服务</label>
            <select id="mcp-server-id" value={serverId} onChange={(event) => { setServerId(event.target.value); setHealth(null); }} className="admin-input mt-1.5 w-full" disabled={!parsed.ok || busy !== null}>
              <option value="">选择服务</option>
              {parsed.ok ? parsed.catalog.servers.map((item) => <option key={String(item.id)} value={String(item.id)}>{String(item.id)} · {String(item.transport)}</option>) : null}
            </select>
          </div>
          <Button variant="outline" onClick={() => void test()} disabled={!server || busy !== null}><Send className="mr-2 h-4 w-4" />测试连接</Button>
        </div>
        {health ? <p className={`mt-4 flex items-center gap-2 text-sm ${health.healthy ? "text-success" : "text-danger"}`} role="status"><CheckCircle2 className="h-4 w-4" />{health.healthy ? `连接正常：${health.tool_count ?? 0} 个 allowlist 工具，${health.latency_ms} ms。` : health.error ?? "服务不可用"}</p> : null}
      </section>
          </TabsContent>

          <TabsContent value="restricted" className="m-0 space-y-6">
      <section className="admin-panel p-5" aria-labelledby="mcp-restricted-heading">
        <div>
          <h3 id="mcp-restricted-heading" className="text-balance text-base font-semibold">订单受限能力</h3>
          <p className="mt-1 text-pretty text-sm leading-6 text-muted">选择已配置的 MCP 连接，并把远端工具明确映射到订单/退款业务契约。只有此处的能力会挂载给 orders Agent，并受身份注入、确认策略和 PluginSet 发布保护。</p>
        </div>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <Field label="MCP 服务" htmlFor="mcp-restricted-server" hint="服务来自左侧 MCP 连接配置；不会重新创建连接。">
            <select id="mcp-restricted-server" value={restrictedServerId} onChange={(event) => setRestrictedServerId(event.target.value)} className="admin-input" disabled={!parsed.ok || busy !== null}>
              <option value="">选择 MCP 服务</option>
              {parsed.ok ? parsed.catalog.servers.map((item) => <option key={String(item.id)} value={String(item.id)}>{String(item.id)} · {String(item.transport)}</option>) : null}
            </select>
          </Field>
          <Field label="工具 → 订单契约" htmlFor="mcp-restricted-mapping" hint="例如 acme_list=commerce.orders.list；多个用英文逗号分隔。">
            <input id="mcp-restricted-mapping" value={restrictedMappings} onChange={(event) => setRestrictedMappings(event.target.value)} className="admin-input font-mono" placeholder="list_orders=commerce.orders.list" autoComplete="off" />
          </Field>
        </div>
        <div className="mt-5 flex justify-end"><Button onClick={() => void addRestrictedBindings()} disabled={busy !== null || !parsed.ok} type="button"><ShieldCheck className="mr-2 h-4 w-4" />加入受限草稿</Button></div>
      </section>

      <section className="admin-panel p-5" aria-labelledby="mcp-catalog-heading">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h3 id="mcp-catalog-heading" className="text-balance text-base font-semibold">目录草稿</h3>
            <p className="mt-1 text-pretty text-sm leading-6 text-muted">这里管理受限能力的完整 catalog：契约、Agent 绑定、策略与发布版本。普通连接请在左侧 MCP Tab 配置。</p>
          </div>
          <Button onClick={() => void save()} disabled={busy !== null}>
            <Upload className="mr-2 h-4 w-4" />保存草稿
          </Button>
        </div>
        {snapshot?.source === "environment" ? <p className="mt-4 rounded-md border border-info/25 bg-info/5 p-3 text-sm leading-6 text-info">当前是部署环境回退目录。它可包含本地 STDIO Mock；开发环境可以保存为草稿，生产环境必须以受审核的部署配置或 HTTPS MCP 替换后再发布。</p> : null}
        <details className="mt-5 rounded-md border border-surface-border/75 bg-surface-2/35 p-4">
          <summary className="cursor-pointer text-sm font-medium text-ink">高级目录编辑（复杂参数 schema、非默认能力绑定）</summary>
          <label htmlFor="mcp-catalog-json" className="mt-4 block text-sm font-medium">Catalog JSON</label>
          <textarea
            id="mcp-catalog-json"
            value={catalogText}
            onChange={(event) => { setCatalogText(event.target.value); setHealth(null); }}
            className="admin-input mt-1.5 min-h-80 w-full font-mono text-xs leading-5"
            aria-describedby="mcp-catalog-help mcp-catalog-error"
            aria-invalid={Boolean(error)}
            spellCheck={false}
          />
          <p id="mcp-catalog-help" className="mt-2 text-sm leading-6 text-muted">高风险能力必须声明已实现的 <code>policy_id</code>。保存仅创建草稿，不会热更新线上 Agent。</p>

          <label htmlFor="mcp-secrets-json" className="mt-5 block text-sm font-medium">本次提交的密钥 JSON（可选）</label>
          <textarea
            id="mcp-secrets-json"
            value={secretsText}
            onChange={(event) => setSecretsText(event.target.value)}
            className="admin-input mt-1.5 min-h-24 w-full font-mono text-xs leading-5"
            aria-describedby="mcp-secrets-help mcp-catalog-error"
            autoComplete="off"
            spellCheck={false}
          />
          <p id="mcp-secrets-help" className="mt-2 text-sm leading-6 text-muted">例如 <code>{'{"orders_bearer":"Bearer …"}'}</code>。空值不会覆盖已加密保存的密钥，读取后不会回显。</p>
        </details>
      </section>

      <section className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-brand/25 bg-brand/5 p-5" aria-labelledby="mcp-publish-heading">
        <div>
          <h3 id="mcp-publish-heading" className="text-balance text-base font-semibold">发布目录</h3>
          <p className="mt-1 max-w-2xl text-pretty text-sm leading-6 text-muted">发布后，所有 API 副本会在下一次对话编译时读取该版本；已在执行的图继续使用原版本，避免中断工具调用。</p>
        </div>
        <Button onClick={() => setPublishOpen(true)} disabled={busy !== null || !snapshot?.draft_version}>
          <ShieldCheck className="mr-2 h-4 w-4" />发布 v{snapshot?.draft_version ?? 0}
        </Button>
      </section>

      <ConfirmDialog
        open={publishOpen}
        onOpenChange={setPublishOpen}
        title="发布 MCP 能力目录？"
        description="发布会改变新对话可调用的外部服务与工具。请确认已完成连通性检查、allowlist 审核和高风险操作策略审查。"
        confirmLabel="确认发布"
        onConfirm={publish}
        busy={busy === "publish"}
      />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}

function parseDraft(catalogText: string, secretsText: string): { ok: true; catalog: McpCatalogPayload; secrets: Record<string, string> } | { ok: false; error: string } {
  try {
    const catalog = JSON.parse(catalogText || JSON.stringify(EMPTY_CATALOG)) as McpCatalogPayload;
    const secrets = JSON.parse(secretsText || "{}") as Record<string, unknown>;
    if (!Array.isArray(catalog.servers) || !Array.isArray(catalog.capabilities) || !Array.isArray(catalog.contracts) || !Array.isArray(catalog.plugins)) throw new Error("catalog 必须包含 servers、capabilities、contracts 与 plugins 数组。");
    if (!secrets || typeof secrets !== "object" || Array.isArray(secrets) || Object.values(secrets).some((value) => typeof value !== "string")) throw new Error("密钥必须是字符串键值对象。");
    return { ok: true, catalog, secrets: secrets as Record<string, string> };
  } catch (cause) {
    return { ok: false, error: cause instanceof Error ? `JSON 格式错误：${cause.message}` : "JSON 格式错误" };
  }
}

function parseToolMappings(value: string): Array<{ tool: string; contract: string }> {
  return Array.from(new Set(value.split(",").map((item) => item.trim()).filter(Boolean))).map((item) => {
    const [toolPart, contractPart] = item.split("=", 2).map((part) => part.trim());
    return {
      tool: toolPart,
      contract: contractPart || ORDER_CONTRACT_BY_TOOL[toolPart] || "",
    };
  }).filter((item) => item.tool);
}

function parseToolNames(value: string): string[] {
  return Array.from(new Set(value.split(",").map((item) => item.split("=", 1)[0].trim()).filter(Boolean)));
}

function Metric({ icon: Icon, label, value, detail }: { icon: typeof Network; label: string; value: string; detail: string }) {
  return <section className="rounded-lg border border-surface-border/80 bg-surface p-4 shadow-sm"><div className="flex items-center justify-between gap-3"><span className="text-xs font-medium text-muted">{label}</span><Icon className="h-4 w-4 text-brand" /></div><p className="mt-4 text-2xl font-semibold tabular-nums">{value}</p><p className="mt-1 text-xs text-muted">{detail}</p></section>;
}

function Field({ label, htmlFor, hint, children }: { label: string; htmlFor: string; hint: string; children: ReactNode }) {
  return <div className="min-w-0"><label htmlFor={htmlFor} className="block text-sm font-medium">{label}</label>{children}<p className="mt-1.5 text-xs leading-5 text-muted">{hint}</p></div>;
}

type EnvironmentEntry = { key: string; value: string };

function StdioConnectionFields({
  args,
  environment,
  inheritedEnvironment,
  cwd,
  onArgsChange,
  onEnvironmentChange,
  onInheritedEnvironmentChange,
  onCwdChange,
}: {
  args: string[];
  environment: EnvironmentEntry[];
  inheritedEnvironment: string[];
  cwd: string;
  onArgsChange: (next: string[]) => void;
  onEnvironmentChange: (next: EnvironmentEntry[]) => void;
  onInheritedEnvironmentChange: (next: string[]) => void;
  onCwdChange: (next: string) => void;
}) {
  const updateArgument = (index: number, value: string) => onArgsChange(args.map((item, i) => i === index ? value : item));
  const updateEnvironment = (index: number, key: "key" | "value", value: string) => onEnvironmentChange(environment.map((item, i) => i === index ? { ...item, [key]: value } : item));

  return <div className="mt-5 space-y-5 border-t border-surface-border/75 pt-5">
    <div>
      <p className="text-sm font-medium">参数</p>
      <p className="mt-1 text-xs leading-5 text-muted">每项是一个独立 argv 参数，避免 Shell 拼接和转义歧义。</p>
      <div className="mt-3 space-y-2">
        {args.map((value, index) => <div className="flex gap-2" key={`arg-${index}`}>
          <input aria-label={`参数 ${index + 1}`} className="admin-input flex-1 font-mono" value={value} onChange={(event) => updateArgument(index, event.target.value)} placeholder="--database=/tmp/app.db" autoComplete="off" />
          <Button type="button" variant="outline" onClick={() => onArgsChange(args.filter((_, itemIndex) => itemIndex !== index))} aria-label={`删除参数 ${index + 1}`}>删除</Button>
        </div>)}
      </div>
      <Button type="button" variant="outline" className="mt-3" onClick={() => onArgsChange([...args, ""])}>添加参数</Button>
    </div>

    <div>
      <p className="text-sm font-medium">环境变量</p>
      <p className="mt-1 text-xs leading-5 text-muted">仅填写非敏感配置。密钥请通过部署级 Secret 引用配置，避免以明文写入草稿。</p>
      <div className="mt-3 space-y-2">
        {environment.map((entry, index) => <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]" key={`env-${index}`}>
          <input aria-label={`环境变量 ${index + 1} 的键`} className="admin-input font-mono" value={entry.key} onChange={(event) => updateEnvironment(index, "key", event.target.value)} placeholder="MCP_LOG_LEVEL" autoComplete="off" />
          <input aria-label={`环境变量 ${index + 1} 的值`} className="admin-input font-mono" value={entry.value} onChange={(event) => updateEnvironment(index, "value", event.target.value)} placeholder="info" autoComplete="off" />
          <Button type="button" variant="outline" onClick={() => onEnvironmentChange(environment.filter((_, itemIndex) => itemIndex !== index))} aria-label={`删除环境变量 ${index + 1}`}>删除</Button>
        </div>)}
      </div>
      <Button type="button" variant="outline" className="mt-3" onClick={() => onEnvironmentChange([...environment, { key: "", value: "" }])}>添加环境变量</Button>
    </div>

    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="环境变量传递" htmlFor="mcp-new-inherit-env" hint="仅传递明确列出的宿主变量；默认 PATH。多个用英文逗号分隔。">
        <input id="mcp-new-inherit-env" className="admin-input font-mono" value={inheritedEnvironment.join(", ")} onChange={(event) => onInheritedEnvironmentChange(event.target.value.split(",").map((item) => item.trim()).filter(Boolean))} placeholder="PATH, LANG" autoComplete="off" />
      </Field>
      <Field label="工作目录（可选）" htmlFor="mcp-new-cwd" hint="MCP 命令运行的目录；留空时使用应用进程目录。">
        <div className="relative"><FolderCog className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden="true" /><input id="mcp-new-cwd" className="admin-input w-full pl-9 font-mono" value={cwd} onChange={(event) => onCwdChange(event.target.value)} placeholder="/workspace/my-mcp" autoComplete="off" /></div>
      </Field>
    </div>
  </div>;
}
