import { describe, expect, it } from "vitest";

import {
  compactEvents,
  formatDagPlan,
  formatRouteReason,
  formatToolAction,
  type ToolEvent,
} from "./ThinkingChain";

function tool(partial: Partial<ToolEvent> & Pick<ToolEvent, "name">): ToolEvent {
  return { status: "ok", ...partial };
}

describe("formatDagPlan", () => {
  it("joins task types for users", () => {
    expect(
      formatDagPlan([
        { id: "task_1", type: "qa_kb", agent: "rag" },
        { id: "task_2", type: "qa_chat", agent: "chat" },
      ])
    ).toBe("查阅知识库 → 通用对话");
  });

  it("handles a single task", () => {
    expect(formatDagPlan([{ type: "qa_chat", agent: "chat" }])).toBe("通用对话");
  });
});

describe("compactEvents", () => {
  it("hides agent_route when a DAG plan is present", () => {
    const events = [
      tool({
        name: "dag_ready",
        input: { tasks: [{ type: "qa_kb", agent: "rag" }], reason: "needs_kb_fact" },
      }),
      tool({ name: "agent_route", input: { agent: "rag", reason: "needs_kb_fact" } }),
      tool({ name: "search_kb", input: { query: "退款" } }),
      tool({ name: "agent_route", input: { agent: "chat", reason: "next_task" } }),
    ];
    const compacted = compactEvents(events);
    expect(compacted.map((event) => event.name)).toEqual(["dag_ready", "search_kb"]);
  });

  it("keeps the latest plan and empty-RAG handoff", () => {
    const events = [
      tool({
        name: "dag_ready",
        input: { tasks: [{ type: "qa_kb", agent: "rag" }] },
      }),
      tool({ name: "search_kb" }),
      tool({ name: "agent_handoff", input: { from: "rag", to: "chat", reason: "rag_empty_evidence" } }),
      tool({
        name: "dag_ready",
        input: {
          tasks: [
            { type: "qa_kb", agent: "rag" },
            { type: "qa_chat", agent: "chat" },
          ],
        },
      }),
    ];
    const compacted = compactEvents(events);
    expect(compacted.map((event) => event.name)).toEqual([
      "dag_ready",
      "search_kb",
      "agent_handoff",
    ]);
    expect(formatDagPlan(compacted[0].input?.tasks)).toBe("查阅知识库 → 通用对话");
  });

  it("still collapses duplicate agent_route without a plan", () => {
    const events = [
      tool({ name: "agent_route", input: { agent: "chat" } }),
      tool({ name: "agent_route", input: { agent: "chat" } }),
      tool({ name: "web_search" }),
    ];
    expect(compactEvents(events).map((event) => event.name)).toEqual(["agent_route", "web_search"]);
  });
});

describe("formatRouteReason", () => {
  it("maps hybrid plan reasons", () => {
    expect(formatRouteReason("needs_kb_then_web")).toBe("先查知识库，不够再联网");
    expect(formatRouteReason("rag_empty_evidence")).toBe("知识库暂无相关内容");
  });
});

describe("dynamic capability presentation", () => {
  it("uses a server-supplied MCP label instead of a frontend tool-name map", () => {
    expect(
      formatToolAction(
        tool({
          name: "inventory_lookup_v2",
          display: {
            kind: "mcp",
            label: "查询仓库库存",
            server_id: "inventory",
            capability_id: "inventory.stock.lookup",
            risk: "read",
          },
        })
      )
    ).toBe("已查询仓库库存");
  });
});
