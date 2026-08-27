import Image from "next/image";
import { cn } from "@/lib/cn";

export const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME || "Agenora";

type BrandSize = "sm" | "md" | "lg" | "xl";
type BrandTone = "solid" | "soft";

type BrandProps = {
  size?: BrandSize;
  showWordmark?: boolean;
  /** Kept for call-site compatibility; mark is full-color either way. */
  tone?: BrandTone;
  className?: string;
};

const SIZES: Record<BrandSize, { box: string; mark: string; text: string }> = {
  sm: {
    box: "h-7 w-7",
    mark: "h-7 w-7",
    text: "text-sm font-semibold",
  },
  md: {
    box: "h-8 w-8",
    mark: "h-8 w-8",
    text: "text-base font-semibold",
  },
  lg: {
    box: "h-14 w-14",
    mark: "h-14 w-14",
    text: "text-3xl font-semibold tracking-tight sm:text-4xl",
  },
  xl: {
    box: "size-16 sm:size-[4.5rem]",
    mark: "size-16 sm:size-[4.5rem]",
    text: "text-4xl font-semibold tracking-tight sm:text-5xl",
  },
};

function BrandMark({ className }: { className?: string }) {
  return (
    <Image
      aria-hidden="true"
      alt=""
      className={className}
      height={56}
      src="/logo.svg"
      width={56}
    />
  );
}

export default function Brand({
  size = "md",
  showWordmark = true,
  className,
}: BrandProps) {
  const s = SIZES[size];
  return (
    <div className={cn("inline-flex items-center gap-2", className)}>
      <div className={cn("kf-brand-mark relative flex items-center justify-center", s.box)} aria-hidden>
        <BrandMark className={s.mark} />
      </div>
      {showWordmark && <span className={s.text}>{APP_NAME}</span>}
    </div>
  );
}
