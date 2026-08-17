"use client";

import { authFetch } from "./auth";

/**
 * Settings API client (v2-M1).
 *
 * Mirrors backend/src/settings_user/routes.py. Throws `SettingsApiError` so the
 * page can branch on dim-conflict (HTTP 409 with structured detail).
 */

export type LLMProvider = "anthropic" | "openai-compat";
export type EmbeddingProvider = "openai-compat" | "ollama";
export type RerankerProvider = "siliconflow" | "cohere" | "openai-compat";

export type MyLLMSettings = {
  provider: LLMProvider | null;
  base_url: string | null;
  default_model: string | null;
  complex_model: string | null;
  /** Explicit user override. Null means resolve from the models.dev snapshot. */
  context_window: number | null;
  context_window_resolved?: number | null;
  context_window_source?: "manual" | "models.dev" | "fallback" | null;
  has_key: boolean;
  configured: boolean;
  effective_configured?: boolean;
  effective_source?: "user" | "system" | "missing";
  effective_model?: string | null;
  effective_complex_model?: string | null;
  effective_context_window?: number | null;
  effective_context_window_source?: "manual" | "models.dev" | "fallback" | null;
  complex_enabled?: boolean;
  default_profile_id?: string | null;
  complex_profile_id?: string | null;
  triage_profile_id?: string | null;
  fallback_profile_id?: string | null;
  triage_model?: string | null;
  fallback_model?: string | null;
  connections?: LLMConnection[];
  model_profiles?: LLMModelProfile[];
};

export type LLMConnection = {
  id: string;
  display_name: string;
  provider: LLMProvider;
  base_url: string;
  has_key: boolean;
  enabled: boolean;
  is_legacy_default: boolean;
  health?: {
    state: "open" | "closed";
    consecutive_failures: number;
    retry_at: string | null;
    last_success_at: string | null;
    last_error_category: string | null;
  };
};

export type LLMModelProfile = {
  id: string;
  connection_id: string | null;
  display_name: string;
  model_id: string;
  /** Explicit user override. Null means the server uses the models.dev snapshot. */
  context_window: number | null;
  context_window_resolved?: number | null;
  context_window_source?: "manual" | "models.dev" | "fallback" | null;
  /** User-specific reseller/proxy pricing, USD per 1M tokens. */
  pricing_override?: ModelPricing | null;
  /** Offline metadata generated from the models.dev SDK snapshot. */
  catalog?: {
    canonical_id: string;
    name: string;
    lab: string;
    context_window: number;
    max_output_tokens: number | null;
    pricing: ModelPricing | null;
    logo_url: string;
  } | null;
  enabled: boolean;
  supports_tools: boolean;
};

export type ModelPricing = {
  input: number;
  output: number;
  cache_read: number | null;
  cache_write: number | null;
};

export type MyEmbeddingSettings = {
  provider: EmbeddingProvider | null;
  base_url: string | null;
  model: string | null;
  dim: number | null;
  has_key: boolean;
  configured: boolean;
};

export type MyRerankerSettings = {
  /** v3-M4: per-user cross-encoder reranker (opt-in, default off). */
  provider: RerankerProvider | null;
  base_url: string | null;
  model: string | null;
  has_key: boolean;
  /** True when provider+base_url+model are all populated (api_key optional for self-hosted). */
  configured: boolean;
  /** Master toggle — both `configured` and `enabled` must be true for rerank to fire at chat time. */
  enabled: boolean;
};

export type MyKbOptions = {
  /** v2-M6: opt-in to mount web_search as a fallback tool when chatting against a user KB. */
  kb_web_search_enabled: boolean;
};

export type MySettings = {
  llm: MyLLMSettings;
  embedding: MyEmbeddingSettings;
  reranker: MyRerankerSettings;
  kb_options: MyKbOptions;
};

export type SaveLLMBody = {
  provider: LLMProvider;
  base_url: string;
  api_key: string;
  /** Required only for the first connection. Subsequent saves preserve routing. */
  default_model?: string;
  complex_model?: string;
  context_window: number | null;
};

export type SaveLLMModelProfileBody = {
  connection_id?: string | null;
  display_name: string;
  model_id: string;
  context_window: number | null;
  input_price_per_million?: number | null;
  output_price_per_million?: number | null;
  cache_read_price_per_million?: number | null;
  cache_write_price_per_million?: number | null;
  enabled: boolean;
  supports_tools: boolean;
};

export type SaveLLMConnectionBody = {
  display_name: string;
  provider: LLMProvider;
  base_url: string;
  api_key: string;
  enabled: boolean;
};

export type SaveLLMModelPolicyBody = {
  default_profile_id: string;
  complex_enabled: boolean;
  complex_profile_id: string | null;
  triage_profile_id: string | null;
  fallback_profile_id: string | null;
};

export type DeleteLLMModelProfileResult = {
  migrated_conversations: number;
};

export type SaveEmbeddingBody = {
  provider: EmbeddingProvider;
  base_url: string;
  api_key: string;
  model: string;
  dim: number;
};

export type SaveRerankerBody = {
  provider: RerankerProvider;
  base_url: string;
  /** Empty string = keep existing encrypted key (lets user toggle enable without re-entering). */
  api_key: string;
  model: string;
  enabled: boolean;
};

export type ProbeLLMBody = {
  provider: LLMProvider;
  base_url: string;
  api_key: string;
};

export type ProbeLLMResult = {
  models: string[];
  context_windows?: Record<string, { value: number; source: "models.dev" }>;
};

export type ProbeEmbeddingBody = {
  provider: EmbeddingProvider;
  base_url: string;
  api_key: string;
  model?: string;
};

export type ProbeRerankerBody = {
  provider: RerankerProvider;
  base_url: string;
  api_key: string;
};

export type DimConflictDetail = {
  code: "embedding_dim_conflict";
  message: string;
  new_dim: number;
  affected_kbs: Array<{ id: string; name: string; vector_size: number }>;
};

export class SettingsApiError extends Error {
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
      message =
        typeof detail === "string"
          ? detail
          : typeof (detail as { message?: string })?.message === "string"
            ? (detail as { message: string }).message
            : JSON.stringify(detail);
    } catch {
      /* keep default */
    }
    throw new SettingsApiError(r.status, detail, message);
  }
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------
export async function getMySettings(): Promise<MySettings> {
  return unwrap(await authFetch("/api/settings/me"));
}

export async function saveLLMSettings(body: SaveLLMBody): Promise<MySettings> {
  return unwrap(
    await authFetch("/api/settings/llm", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function clearLLMSettings(): Promise<void> {
  await unwrap(await authFetch("/api/settings/llm", { method: "DELETE" }));
}

export async function createLLMConnection(
  body: SaveLLMConnectionBody
): Promise<LLMConnection> {
  return unwrap(
    await authFetch("/api/settings/llm/connections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function deleteLLMConnection(id: string): Promise<void> {
  await unwrap(await authFetch(`/api/settings/llm/connections/${id}`, { method: "DELETE" }));
}

export async function createLLMModelProfile(
  body: SaveLLMModelProfileBody
): Promise<LLMModelProfile> {
  return unwrap(
    await authFetch("/api/settings/llm/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function probeLLMConnection(connectionId: string): Promise<ProbeLLMResult> {
  return unwrap(
    await authFetch(`/api/settings/llm/connections/${connectionId}/probe`, {
      method: "POST",
    })
  );
}

export async function updateLLMModelProfile(
  id: string,
  body: SaveLLMModelProfileBody
): Promise<LLMModelProfile> {
  return unwrap(
    await authFetch(`/api/settings/llm/models/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function deleteLLMModelProfile(
  id: string,
  replacementProfileId?: string | null
): Promise<DeleteLLMModelProfileResult> {
  return unwrap(
    await authFetch(`/api/settings/llm/models/${id}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ replacement_profile_id: replacementProfileId ?? null }),
    })
  );
}

export async function saveLLMModelPolicy(body: SaveLLMModelPolicyBody): Promise<MySettings> {
  return unwrap(
    await authFetch("/api/settings/llm/policy", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function saveEmbeddingSettings(
  body: SaveEmbeddingBody
): Promise<MySettings> {
  return unwrap(
    await authFetch("/api/settings/embedding", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function clearEmbeddingSettings(): Promise<void> {
  await unwrap(await authFetch("/api/settings/embedding", { method: "DELETE" }));
}

export async function probeLLM(body: ProbeLLMBody): Promise<{
  models: string[];
  context_windows?: Record<string, { value: number; source: "models.dev" }>;
}> {
  return unwrap(
    await authFetch("/api/settings/probe/llm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function probeEmbedding(
  body: ProbeEmbeddingBody
): Promise<{ models: string[]; dim: number | null }> {
  return unwrap(
    await authFetch("/api/settings/probe/embedding", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

// v2-M6: KB-mode toggles (currently just web_search opt-in).
export async function saveKbOptions(body: MyKbOptions): Promise<MySettings> {
  return unwrap(
    await authFetch("/api/settings/kb-options", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

// v3-M4: cross-encoder reranker (opt-in, default off).
export async function saveRerankerSettings(body: SaveRerankerBody): Promise<MySettings> {
  return unwrap(
    await authFetch("/api/settings/reranker", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function clearRerankerSettings(): Promise<void> {
  await unwrap(await authFetch("/api/settings/reranker", { method: "DELETE" }));
}

export async function probeReranker(
  body: ProbeRerankerBody
): Promise<{ models: string[] }> {
  return unwrap(
    await authFetch("/api/settings/probe/reranker", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}
