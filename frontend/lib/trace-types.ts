export type TraceSummary = {
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

export type TraceObservationNode = {
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
  ttft_ms?: number | null;
  children?: TraceObservationNode[];
};

export type TraceDetail = TraceSummary & {
  observations: TraceObservationNode[];
  observations_flat: TraceObservationNode[];
};
