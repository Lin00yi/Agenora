import type { LLMModelProfile, LLMProvider } from "@/lib/settings-api";

export type ProviderBrandKey = "anthropic" | "deepseek" | "openai" | "compatible" | "models.dev";

export type ProviderBrand = {
  key: ProviderBrandKey;
  label: string;
  iconPath?: string;
  colorClassName: string;
};

type ProviderBrandInput = {
  provider: LLMProvider;
  base_url: string;
};

type ModelCatalogBrand = NonNullable<LLMModelProfile["catalog"]>;

function hostname(baseUrl: string) {
  try {
    return new URL(baseUrl).hostname.toLowerCase();
  } catch {
    return baseUrl.toLowerCase();
  }
}

function matchesDomain(host: string, domain: string) {
  return host === domain || host.endsWith(`.${domain}`);
}

/**
 * Model profiles use the models.dev lab mapping first, so an OpenAI-compatible
 * proxy can still identify its actual model. Connection-only surfaces retain
 * the conservative official-domain branding fallback.
 */
export function resolveProviderBrand(
  connection?: ProviderBrandInput,
  catalog?: ModelCatalogBrand | null,
): ProviderBrand {
  if (catalog) {
    return {
      key: "models.dev",
      label: catalog.name,
      iconPath: catalog.logo_url,
      colorClassName: "text-ink",
    };
  }
  if (!connection) return { key: "compatible", label: "兼容服务", colorClassName: "text-muted" };

  const host = hostname(connection.base_url);
  if (matchesDomain(host, "deepseek.com")) {
    return { key: "deepseek", label: "DeepSeek", iconPath: "/provider-logos/deepseek.svg", colorClassName: "text-[#4D6BFE]" };
  }
  if (matchesDomain(host, "openai.com")) {
    return { key: "openai", label: "OpenAI", iconPath: "/provider-logos/openai.svg", colorClassName: "text-ink" };
  }
  if (connection.provider === "anthropic" || matchesDomain(host, "anthropic.com")) {
    return { key: "anthropic", label: "Anthropic", iconPath: "/provider-logos/anthropic.svg", colorClassName: "text-[#C7663A]" };
  }
  return { key: "compatible", label: "兼容服务", colorClassName: "text-muted" };
}
