/**
 * Build the small, runtime-safe model catalog consumed by the Python API.
 *
 * `@opencode-ai/models` is the official typed SDK for models.dev. Its bundled
 * snapshot means deployments and context-budget calculations never depend on a
 * third-party network request. Run `npm run sync:model-catalog` whenever the
 * SDK version is updated.
 */
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

import { generatedAt, models, providers } from "@opencode-ai/models/snapshot";

const outputPath = resolve(import.meta.dirname, "../../backend/config/models.dev.snapshot.json");

const catalog = Object.entries(models)
  .map(([canonicalId, model]) => {
    const [lab, ...modelParts] = canonicalId.split("/");
    const modelId = modelParts.join("/");
    const contextWindow = model.limit?.context;
    const maxOutputTokens = model.limit?.output;
    // The global model list describes capabilities. Pricing is deliberately
    // provider-specific in models.dev, so select the matching first-party lab
    // instead of borrowing a reseller's price for the same model ID.
    const cost = providers[lab]?.models?.[modelId]?.cost;

    if (!lab || !modelId || !Number.isInteger(contextWindow) || contextWindow < 4_096) return null;

    return {
      canonical_id: canonicalId,
      model_id: modelId,
      name: model.name || modelId,
      lab,
      context_window: contextWindow,
      max_output_tokens: Number.isInteger(maxOutputTokens) ? maxOutputTokens : null,
      // Costs in models.dev are USD per 1M tokens. Keep the optional cache
      // dimensions too: Anthropic and some other providers price them
      // differently from ordinary input.
      pricing: cost && Number.isFinite(cost.input) && Number.isFinite(cost.output)
        ? {
            input: cost.input,
            output: cost.output,
            cache_read: Number.isFinite(cost.cache_read) ? cost.cache_read : null,
            cache_write: Number.isFinite(cost.cache_write) ? cost.cache_write : null,
          }
        : null,
      logo_url: `https://models.dev/logos/labs/${encodeURIComponent(lab)}.svg`,
    };
  })
  .filter(Boolean)
  .sort((left, right) => left.canonical_id.localeCompare(right.canonical_id));

const modelIds = {};
for (const entry of catalog) (modelIds[entry.model_id] ??= []).push(entry.canonical_id);

await mkdir(dirname(outputPath), { recursive: true });
await writeFile(
  outputPath,
  `${JSON.stringify({ schema_version: 1, generated_at: generatedAt, models: catalog, model_ids: modelIds }, null, 2)}\n`,
  "utf8",
);

console.log(`Wrote ${catalog.length} models from models.dev (${generatedAt}) to ${outputPath}`);
