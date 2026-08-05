export type SourceRow = {
  title: string;
  meta: string;
  score: string;
  detail?: string[];
};

export type LlmSource = "user" | "system" | "missing";
