"use client";

import { authFetch } from "./auth";

/**
 * Admin dashboard API client (06-01).
 *
 * Mirrors backend/src/api/routes/admin.py. All calls go through authFetch (Bearer
 * token) and hit /api/admin/* — the backend rejects non-admins with 403.
 * Self-protection invariants surface as 400 (self) / 409 (last admin); we
 * throw the backend `detail` so the page can toast it verbatim.
 */

// ---------------------------------------------------------------------------
// Types — keep in sync with the backend response contract.
// ---------------------------------------------------------------------------
export type AdminStats = {
  users: {
    total: number;
    active: number;
    banned: number;
    admins: number;
    new_last_7d: number;
  };
  kbs: {
    total: number;
    system: number;
  };
  documents: number;
  conversations: number;
  messages: number;
};

export type AdminUser = {
  id: string;
  email: string;
  display_name: string;
  created_at: string | null;
  is_admin: boolean;
  is_active: boolean;
  byok_configured: boolean;
  kb_count: number;
  conversation_count: number;
};

export type AdminUserListResponse = {
  total: number;
  limit: number;
  offset: number;
  users: AdminUser[];
};

export type AdminKb = {
  id: string;
  name: string;
  description: string;
  owner_id: string;
  owner_email: string | null;
  is_system: boolean;
  documents_count: number;
  chunks_count: number;
  member_count: number;
  created_at: string | null;
};

export type AdminKbListResponse = {
  total: number;
  limit: number;
  offset: number;
  kbs: AdminKb[];
};

export class AdminApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function unwrap<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail: unknown = null;
    let message = `HTTP ${r.status}`;
    try {
      const j = await r.json();
      detail = j.detail ?? j;
      if (typeof detail === "string") {
        message = detail;
      } else if (detail && typeof detail === "object") {
        const d = detail as { message?: string };
        message = typeof d.message === "string" ? d.message : JSON.stringify(detail);
      }
    } catch {
      /* keep default */
    }
    throw new AdminApiError(r.status, detail, message);
  }
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------
export async function getStats(): Promise<AdminStats> {
  return unwrap(await authFetch("/api/admin/stats"));
}

// ---------------------------------------------------------------------------
// Prompt Registry
// ---------------------------------------------------------------------------
export type AdminPromptVersion = {
  id: string;
  version: number;
  status: "draft" | "published" | "archived";
  content: string;
  digest: string;
  created_by_admin_id: string | null;
  created_at: string | null;
  published_at: string | null;
};

export type AdminPromptTemplateSummary = {
  key: string;
  display_name: string;
  description: string;
  allowed_variables: string[];
  published_version: number | null;
  latest_version: AdminPromptVersion | null;
  source: "code" | "registry";
};

export type AdminPromptTemplateDetail = {
  key: string;
  display_name: string;
  description: string;
  allowed_variables: string[];
  published_version: number | null;
  fallback_content: string;
  versions: AdminPromptVersion[];
};

export async function listPromptTemplates(): Promise<{ templates: AdminPromptTemplateSummary[] }> {
  return unwrap(await authFetch("/api/admin/prompts"));
}

export async function getPromptTemplate(key: string): Promise<AdminPromptTemplateDetail> {
  return unwrap(await authFetch(`/api/admin/prompts/${encodeURIComponent(key)}`));
}

export async function savePromptDraft(key: string, content: string): Promise<AdminPromptVersion> {
  return unwrap(
    await authFetch(`/api/admin/prompts/${encodeURIComponent(key)}/draft`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    })
  );
}

export async function publishPromptVersion(key: string, version: number): Promise<AdminPromptVersion> {
  return unwrap(
    await authFetch(`/api/admin/prompts/${encodeURIComponent(key)}/publish/${version}`, {
      method: "POST",
    })
  );
}

export async function rollbackPromptVersion(key: string, version: number): Promise<AdminPromptVersion> {
  return unwrap(
    await authFetch(`/api/admin/prompts/${encodeURIComponent(key)}/rollback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version }),
    })
  );
}

export type RagMonitorAlert = {
  code: string;
  severity: "warning" | "critical";
  message: string;
  value: number;
  threshold: number;
};

export type RagMonitorSnapshot = {
  window_hours: number;
  generated_at: string;
  sample_sufficient: boolean;
  min_calls: number;
  status: "healthy" | "alert";
  alerts: RagMonitorAlert[];
  metrics: {
    retrieval_calls: number;
    retrieval_traces: number;
    kb_calls: number;
    kg_calls: number;
    error_calls: number;
    error_rate: number;
    measurable_empty_calls: number;
    empty_calls: number;
    empty_rate: number | null;
    p95_latency_ms: number | null;
    avg_top_score: number | null;
  };
};

export async function getRagMonitor(hours = 24): Promise<RagMonitorSnapshot> {
  return unwrap(await authFetch(`/api/admin/rag/monitor?hours=${hours}`));
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------
export async function listUsers(
  limit = 50,
  offset = 0
): Promise<AdminUserListResponse> {
  return unwrap(
    await authFetch(`/api/admin/users?limit=${limit}&offset=${offset}`)
  );
}

export async function getUser(id: string): Promise<AdminUser> {
  return unwrap(await authFetch(`/api/admin/users/${id}`));
}

export async function updateUser(
  id: string,
  body: { is_active?: boolean; is_admin?: boolean }
): Promise<AdminUser> {
  return unwrap(
    await authFetch(`/api/admin/users/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function resetUserPassword(
  id: string,
  newPassword: string
): Promise<{ ok: true }> {
  return unwrap(
    await authFetch(`/api/admin/users/${id}/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_password: newPassword }),
    })
  );
}

export async function deleteUser(id: string): Promise<void> {
  await unwrap(await authFetch(`/api/admin/users/${id}`, { method: "DELETE" }));
}

// ---------------------------------------------------------------------------
// Knowledge bases
// ---------------------------------------------------------------------------
export async function listKbs(
  limit = 50,
  offset = 0
): Promise<AdminKbListResponse> {
  return unwrap(
    await authFetch(`/api/admin/kbs?limit=${limit}&offset=${offset}`)
  );
}

export async function deleteKb(id: string): Promise<void> {
  await unwrap(await authFetch(`/api/admin/kbs/${id}`, { method: "DELETE" }));
}

// ---------------------------------------------------------------------------
// Traces (internal observability)
// ---------------------------------------------------------------------------
export type AdminTraceSummary = {
  id: string;
  conversation_id: string | null;
  user_id: string | null;
  name: string;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  status: string;
  total_cost_usd: number | null;
  metadata: Record<string, unknown>;
  observation_count: number;
};

export type AdminObservationNode = {
  id: string;
  trace_id: string;
  parent_observation_id: string | null;
  type: string;
  name: string;
  lifecycle: "active" | "legacy" | "retired" | "unknown";
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  status: string;
  error: string | null;
  model: string | null;
  usage: Record<string, number> | null;
  cost_usd: number | null;
  input_preview: string | null;
  output_preview: string | null;
  metadata: Record<string, unknown>;
  children?: AdminObservationNode[];
};

export type AdminTraceListResponse = {
  total: number;
  limit: number;
  offset: number;
  traces: AdminTraceSummary[];
};

export type AdminTraceDetail = AdminTraceSummary & {
  input_preview: string | null;
  output_preview: string | null;
  observations: AdminObservationNode[];
  observations_flat: AdminObservationNode[];
};

export async function listTraces(params?: {
  conversation_id?: string;
  user_id?: string;
  min_risk?: "low" | "medium" | "high";
  limit?: number;
  offset?: number;
}): Promise<AdminTraceListResponse> {
  const qs = new URLSearchParams();
  qs.set("limit", String(params?.limit ?? 50));
  qs.set("offset", String(params?.offset ?? 0));
  if (params?.conversation_id?.trim()) {
    qs.set("conversation_id", params.conversation_id.trim());
  }
  if (params?.user_id?.trim()) {
    qs.set("user_id", params.user_id.trim());
  }
  if (params?.min_risk && params.min_risk !== "low") {
    qs.set("min_risk", params.min_risk);
  }
  return unwrap(await authFetch(`/api/admin/traces?${qs.toString()}`));
}

export async function getTrace(id: string): Promise<AdminTraceDetail> {
  return unwrap(await authFetch(`/api/admin/traces/${id}`));
}
