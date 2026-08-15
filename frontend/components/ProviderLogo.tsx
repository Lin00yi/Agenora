import { Boxes } from "lucide-react";

import { resolveProviderBrand } from "@/lib/provider-brand";
import type { LLMConnection } from "@/lib/settings-api";
import { cn } from "@/lib/utils";

type ProviderLogoProps = {
  connection?: Pick<LLMConnection, "provider" | "base_url">;
  className?: string;
  size?: "sm" | "md";
};

export function ProviderLogo({ connection, className, size = "sm" }: ProviderLogoProps) {
  const brand = resolveProviderBrand(connection);
  const sizeClass = size === "md" ? "size-8 rounded-lg" : "size-6 rounded-md";

  return (
    <span
      className={cn("inline-flex shrink-0 items-center justify-center border border-surface-border/80 bg-surface-2", sizeClass, className)}
      title={brand.label}
      aria-label={brand.label}
    >
      {brand.iconPath ? (
        <span
          aria-hidden
          className={cn("block bg-current", brand.colorClassName, size === "md" ? "size-4" : "size-3.5")}
          style={{
            WebkitMaskImage: `url(${brand.iconPath})`,
            WebkitMaskPosition: "center",
            WebkitMaskRepeat: "no-repeat",
            WebkitMaskSize: "contain",
            maskImage: `url(${brand.iconPath})`,
            maskPosition: "center",
            maskRepeat: "no-repeat",
            maskSize: "contain",
          }}
        />
      ) : (
        <Boxes className={cn(brand.colorClassName, size === "md" ? "size-4" : "size-3.5")} aria-hidden />
      )}
    </span>
  );
}
