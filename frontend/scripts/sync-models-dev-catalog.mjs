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

import { generatedAt, models } from "@opencode-ai/models/snapshot";

const outputPath = resolve(import.meta.dirname, "../../backend/config/models.dev.snapshot.json");

const catalog = Object.entries(models)
  .map(([canonicalId, model]) => {
    const [lab, ...modelParts] = canonicalId.split("/");
    const modelId = modelParts.join("/");
    const contextWindow = model.limit?.context;
    const maxOutputTokens = model.limit?.output;

    if (!lab || !modelId || !Number.isInteger(contextWindow) || contextWindow < 4_096) return null;

    return {
      canonical_id: canonicalId,
      model_id: modelId,
      name: model.name || modelId,
      lab,
      context_window: contextWindow,
      max_output_tokens: Number.isInteger(maxOutputTokens) ? maxOutputTokens : null,
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
