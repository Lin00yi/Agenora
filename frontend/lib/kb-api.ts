"use client";

import { authFetch } from "./auth";

/**
 * KB / Document API client.
 *
 * All calls go through authFetch which auto-attaches the Bearer token.
 * Server-side type is the source of truth; these mirrors live here so the UI
 * gets static checking. Keep them in sync with backend/src/kb/models.py.
 */

export type DocStatus = "pending" | "ingesting" | "done" | "failed";
export type SourceType = "file" | "url";
export type ChunkStrategy =
  | "recursive"
  | "markdown_heading"
  | "semantic"
  | "table_aware"
  | "code"
  | "parent_child";
/** v2-M9: caller's effective role for a KB. system KB is "viewer" for everyone. */
export type KbRole = "owner" | "editor" | "viewer";
export type MemberRole = "editor" | "viewer";

export function formatKbRole(role: KbRole | MemberRole | string): string {
  switch (role) {
    case "owner":
      return "所有者";
    case "editor":
      return "编辑者";
    case "viewer":
      return "只读";
    default:
      return role;
  }
}

export type KB = {
  id: string;
  name: string;
  description: string;
  embedding_model: string;
  vector_size: number;
  chunks_count: number;
  documents_count: number;
  document_status_counts?: {
    pending: number;
    ingesting: number;
    done: number;
    failed: number;
  };
  is_system: boolean;
  /** v3-M3: owner toggle. When true, KB search returns at most 1 chunk per
   *  document via Milvus group_by_field. */
  grouping_enabled: boolean;
  /** Knowledge-graph recall via LightRAG Server (opt-in). */
  kg_enabled: boolean;
  /** v4: KB-level chunking defaults (chars). Document can override. */
  chunk_strategy: ChunkStrategy;
  chunk_target: number;
  chunk_max_size: number;
  chunk_overlap: number;
  created_at: string | null;
  /** v2-M9: present when returned by list_kbs / get_kb. Absent on POST create. */
  my_role?: KbRole;
};

export type Document = {
  id: string;
  kb_id: string;
  filename: string;
  mime: string;
  size_bytes: number;
  source_type: SourceType;
  source_url: string;
  status: DocStatus;
  chunks_count: number;
  error: string | null;
  chunk_strategy: ChunkStrategy | null;
  chunk_target: number | null;
  chunk_max_size: number | null;
  chunk_overlap: number | null;
  effective_chunk_strategy: ChunkStrategy | null;
  effective_chunk_target: number | null;
  effective_chunk_max_size: number | null;
  effective_chunk_overlap: number | null;
  parsed_text_length: number;
  enabled: boolean;
  kg_status?: string | null;
  kg_error?: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type Chunk = {
  id: string;
  doc_id: string;
  kb_id: string;
  chunk_idx: number;
  text: string;
  char_count: number;
  enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
};

export type ChunkListResponse = {
  items: Chunk[];
  total: number;
  page: number;
  page_size: number;
};

export type DocumentDetail = Document & {
  parsed_text?: string;
};

export type KBDetail = KB & { documents: Document[] };

/** v2-M9: response shape for GET /kbs/{id}/members */
export type KbMemberListResponse = {
  owner: {
    user_id: string;
    email: string;
    display_name: string | null;
  } | null;
  members: {
    user_id: string;
    email: string;
    display_name: string | null;
    role: MemberRole;
    invited_by_email: string | null;
    created_at: string | null;
  }[];
};

/** Structured error from KB endpoints. v2-M2 BYOK gate surfaces `detail.code`
 *  (e.g. "embedding_not_configured") so the page can route to /settings. */
export class KbApiError extends Error {
  status: number;
  detail: unknown;
  code?: string;
  settings_url?: string;
  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.status = status;
    this.detail = detail;
    if (detail && typeof detail === "object") {
      const d = detail as { code?: string; settings_url?: string };
      this.code = d.code;
      this.settings_url = d.settings_url;
    }
  }
}

function localizeKbApiMessage(message: string): string {
  const text = message.trim();
  const lower = text.toLowerCase();
  if (lower === "kb not found") {
    return "未找到知识库。";
  }
  if (lower.includes("system kb is read-only") || lower.includes("system kbs cannot")) {
    return "系统知识库为只读，无法修改。";
  }
  if (lower.includes("owner role required")) {
    return "需要所有者权限。";
  }
  if (lower.includes("editor or owner role required")) {
    return "需要编辑者或所有者权限。";
  }
  return text;
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
    throw new KbApiError(r.status, detail, localizeKbApiMessage(message));
  }
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}

// ---------------------------------------------------------------------------
// KB CRUD
// ---------------------------------------------------------------------------
export async function listKbs(): Promise<KB[]> {
  return unwrap(await authFetch("/api/kbs"));
}

export async function getKb(id: string): Promise<KBDetail> {
  return unwrap(await authFetch(`/api/kbs/${id}`));
}

/** v3-M7: optional per-KB embedding + reranker override at creation time. */
export type CreateKbBody = {
  name: string;
  description?: string;
  embedding_provider?: "openai-compat" | "ollama" | null;
  embedding_base_url?: string | null;
  embedding_api_key?: string;
  embedding_model?: string | null;
  embedding_dim?: number | null;
  reranker_provider?: "siliconflow" | "cohere" | "openai-compat" | null;
  reranker_base_url?: string | null;
  reranker_api_key?: string;
  reranker_model?: string | null;
  reranker_enabled?: boolean;
  chunk_strategy?: ChunkStrategy;
};

export async function createKb(
  nameOrBody: string | CreateKbBody,
  description = ""
): Promise<KB> {
  // Back-compat overload: createKb("name", "desc") still works.
  const body: CreateKbBody =
    typeof nameOrBody === "string"
      ? { name: nameOrBody, description }
      : nameOrBody;
  return unwrap(
    await authFetch("/api/kbs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function deleteKb(id: string): Promise<void> {
  await unwrap(await authFetch(`/api/kbs/${id}`, { method: "DELETE" }));
}

/** Owner-only KB settings PATCH. Returns the updated KB. */
export async function patchKb(
  id: string,
  body: {
    grouping_enabled?: boolean;
    kg_enabled?: boolean;
    chunk_strategy?: ChunkStrategy;
    chunk_target?: number;
    chunk_max_size?: number;
    chunk_overlap?: number;
  }
): Promise<KB> {
  return unwrap(
    await authFetch(`/api/kbs/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

/** v3-M3: owner-only KB rebuild. Drops the vector collection and re-ingests
 *  every document — used to upgrade a pre-v3-M3 dense-only collection to
 *  the hybrid (dense + BM25) schema. Returns count of docs being re-ingested.
 *  During the rebuild window chat against this KB sees empty hits. */
export async function rebuildKb(
  id: string
): Promise<{ rebuilding: boolean; doc_count: number; collection: string }> {
  return unwrap(
    await authFetch(`/api/kbs/${id}/rebuild`, { method: "POST" })
  );
}

// ---------------------------------------------------------------------------
// Document operations
// ---------------------------------------------------------------------------
export async function listDocuments(kbId: string): Promise<Document[]> {
  return unwrap(await authFetch(`/api/kbs/${kbId}/documents`));
}

export async function uploadFile(kbId: string, file: File): Promise<Document> {
  const fd = new FormData();
  fd.append("file", file);
  return unwrap(
    await authFetch(`/api/kbs/${kbId}/documents`, {
      method: "POST",
      body: fd,
    })
  );
}

export async function uploadUrl(kbId: string, url: string): Promise<Document> {
  const fd = new FormData();
  fd.append("url", url);
  return unwrap(
    await authFetch(`/api/kbs/${kbId}/documents`, {
      method: "POST",
      body: fd,
    })
  );
}

export async function deleteDocument(kbId: string, docId: string): Promise<void> {
  await unwrap(
    await authFetch(`/api/kbs/${kbId}/documents/${docId}`, { method: "DELETE" })
  );
}

export async function getDocument(
  kbId: string,
  docId: string,
  opts?: { includeParsedText?: boolean }
): Promise<DocumentDetail> {
  const q = opts?.includeParsedText ? "?include_parsed_text=true" : "";
  return unwrap(await authFetch(`/api/kbs/${kbId}/documents/${docId}${q}`));
}

export async function patchDocument(
  kbId: string,
  docId: string,
  body: {
    filename?: string;
    chunk_strategy?: ChunkStrategy | null;
    chunk_target?: number | null;
    chunk_max_size?: number | null;
    chunk_overlap?: number | null;
    enabled?: boolean;
  }
): Promise<Document> {
  return unwrap(
    await authFetch(`/api/kbs/${kbId}/documents/${docId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function reingestDocument(kbId: string, docId: string): Promise<Document> {
  return unwrap(
    await authFetch(`/api/kbs/${kbId}/documents/${docId}/reingest`, {
      method: "POST",
    })
  );
}

export function documentDownloadUrl(kbId: string, docId: string): string {
  return `/api/kbs/${kbId}/documents/${docId}/download`;
}

/** Authenticated file download (plain <a> won't send Bearer token). */
export async function downloadDocumentFile(
  kbId: string,
  docId: string,
  filename: string
): Promise<void> {
  const r = await authFetch(`/api/kbs/${kbId}/documents/${docId}/download`);
  if (!r.ok) {
    throw new KbApiError(r.status, null, `download failed: HTTP ${r.status}`);
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function listDocumentChunks(
  kbId: string,
  docId: string,
  page = 1,
  pageSize = 20,
  opts?: { q?: string; enabled?: boolean | null }
): Promise<ChunkListResponse> {
  const q = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  if (opts?.q?.trim()) q.set("q", opts.q.trim());
  if (opts?.enabled === true) q.set("enabled", "true");
  if (opts?.enabled === false) q.set("enabled", "false");
  return unwrap(
    await authFetch(`/api/kbs/${kbId}/documents/${docId}/chunks?${q}`)
  );
}

export async function batchPatchAllChunks(
  kbId: string,
  docId: string,
  enabled: boolean
): Promise<{ updated: number; enabled: boolean }> {
  return unwrap(
    await authFetch(`/api/kbs/${kbId}/documents/${docId}/chunks/batch-all`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    })
  );
}

export async function batchPatchChunks(
  kbId: string,
  docId: string,
  chunkIds: string[],
  enabled: boolean
): Promise<{ updated: number; items: Chunk[] }> {
  return unwrap(
    await authFetch(`/api/kbs/${kbId}/documents/${docId}/chunks/batch`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chunk_ids: chunkIds, enabled }),
    })
  );
}

export async function patchChunk(
  kbId: string,
  docId: string,
  chunkId: string,
  body: { text?: string; enabled?: boolean }
): Promise<Chunk> {
  return unwrap(
    await authFetch(`/api/kbs/${kbId}/documents/${docId}/chunks/${chunkId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function deleteChunk(
  kbId: string,
  docId: string,
  chunkId: string
): Promise<void> {
  await unwrap(
    await authFetch(`/api/kbs/${kbId}/documents/${docId}/chunks/${chunkId}`, {
      method: "DELETE",
    })
  );
}

export async function splitChunk(
  kbId: string,
  docId: string,
  chunkId: string,
  offset: number
): Promise<{ chunks: Chunk[] }> {
  return unwrap(
    await authFetch(`/api/kbs/${kbId}/documents/${docId}/chunks/${chunkId}/split`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ offset }),
    })
  );
}

export async function mergeChunks(
  kbId: string,
  docId: string,
  chunkIds: [string, string]
): Promise<Chunk> {
  return unwrap(
    await authFetch(`/api/kbs/${kbId}/documents/${docId}/chunks/merge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chunk_ids: chunkIds }),
    })
  );
}

// ---------------------------------------------------------------------------
// v2-M9: Members management
// ---------------------------------------------------------------------------
export async function listMembers(kbId: string): Promise<KbMemberListResponse> {
  return unwrap(await authFetch(`/api/kbs/${kbId}/members`));
}

export async function inviteMember(
  kbId: string,
  email: string,
  role: MemberRole
): Promise<KbMemberListResponse["members"][number]> {
  return unwrap(
    await authFetch(`/api/kbs/${kbId}/members`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, role }),
    })
  );
}

export async function patchMember(
  kbId: string,
  userId: string,
  role: MemberRole
): Promise<void> {
  await unwrap(
    await authFetch(`/api/kbs/${kbId}/members/${userId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    })
  );
}

export async function removeMember(kbId: string, userId: string): Promise<void> {
  await unwrap(
    await authFetch(`/api/kbs/${kbId}/members/${userId}`, { method: "DELETE" })
  );
}

// ---------------------------------------------------------------------------
// Per-KB golden-set evaluation
// ---------------------------------------------------------------------------
export type KbEvalTemplate = {
  id: string;
  name: string;
  case_count: number;
  k: number;
};

export type KbEvalCaseSummary = {
  id: string;
  query: string;
  tags: string[];
  expected_document_ids: string[];
};

export type KbEvalMetrics = {
  recall_at_k: number | null;
  precision_at_k: number | null;
  mrr: number | null;
  ndcg_at_k: number | null;
  citation_precision: number | null;
  citation_recall: number | null;
};

export type KbEvalConfig = {
  configured: boolean;
  case_count: number;
  k: number;
  golden_set_hash: string | null;
  minimums: {
    recall_at_k?: number | null;
    mrr?: number | null;
    ndcg_at_k?: number | null;
    citation_precision?: number | null;
  };
  baseline: Record<string, number>;
  notes: string;
  cases: KbEvalCaseSummary[];
  updated_at: string | null;
};

export type KbEvalPerCase = {
  id: string;
  query?: string;
  tags: string[];
  retrieved_document_ids: string[];
  expected_document_ids: string[];
  citation_document_ids: string[];
  expected_citation_document_ids: string[];
  recall: number;
  mrr: number;
  ndcg: number;
  citation_recall: number | null;
  citation_precision: number | null;
};

export type KbEvalReport = {
  schema_version: number;
  case_count: number;
  prediction_count: number;
  missing_prediction_ids: string[];
  k: number;
  metrics: KbEvalMetrics;
  per_case: KbEvalPerCase[];
  gate_passed?: boolean;
  gate_error?: string;
};

export type KbEvalRun = {
  id: string;
  kb_id: string;
  run_type: "regression" | "replay" | string;
  golden_set_hash: string;
  k: number;
  gate_passed: boolean;
  metrics: KbEvalMetrics;
  case_count: number | null;
  missing_count: number;
  created_by: string | null;
  created_at: string | null;
  report?: KbEvalReport;
};

export type KbEvalRunList = {
  total: number;
  limit: number;
  offset: number;
  runs: KbEvalRun[];
};

export type KbEvalMonitorSnapshot = {
  kb_id?: string;
  window_hours: number;
  generated_at: string;
  sample_sufficient: boolean;
  min_calls: number;
  status: "healthy" | "alert";
  alerts: Array<{
    code: string;
    severity: "warning" | "critical";
    message: string;
    value: number;
    threshold: number;
  }>;
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
  scope_note?: string;
};

export async function listKbEvalTemplates(
  kbId: string
): Promise<{ templates: KbEvalTemplate[] }> {
  return unwrap(await authFetch(`/api/kbs/${kbId}/eval/templates`));
}

export async function getKbEvalConfig(kbId: string): Promise<KbEvalConfig> {
  return unwrap(await authFetch(`/api/kbs/${kbId}/eval/config`));
}

export async function putKbEvalConfig(
  kbId: string,
  body: { golden_set_jsonl?: string; gate_json?: string; template?: "roogoo" }
): Promise<KbEvalConfig> {
  return unwrap(
    await authFetch(`/api/kbs/${kbId}/eval/config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function runKbEvalRegression(kbId: string): Promise<KbEvalRun> {
  return unwrap(
    await authFetch(`/api/kbs/${kbId}/eval/run`, { method: "POST" })
  );
}

export async function listKbEvalRuns(
  kbId: string,
  limit = 20,
  offset = 0
): Promise<KbEvalRunList> {
  return unwrap(
    await authFetch(`/api/kbs/${kbId}/eval/runs?limit=${limit}&offset=${offset}`)
  );
}

export async function getKbEvalRun(kbId: string, runId: string): Promise<KbEvalRun> {
  return unwrap(await authFetch(`/api/kbs/${kbId}/eval/runs/${runId}`));
}

export async function replayKbEval(
  kbId: string,
  source: { runId: string } | { file: File }
): Promise<KbEvalRun> {
  if ("runId" in source) {
    return unwrap(
      await authFetch(`/api/kbs/${kbId}/eval/replay?run_id=${encodeURIComponent(source.runId)}`, {
        method: "POST",
      })
    );
  }
  const fd = new FormData();
  fd.append("retrieval_jsonl", source.file);
  return unwrap(
    await authFetch(`/api/kbs/${kbId}/eval/replay`, { method: "POST", body: fd })
  );
}

export async function getKbEvalMonitor(
  kbId: string,
  hours = 24
): Promise<KbEvalMonitorSnapshot> {
  return unwrap(await authFetch(`/api/kbs/${kbId}/eval/monitor?hours=${hours}`));
}
