import { cn } from "@/lib/cn";

export const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME || "Agenora";

type BrandSize = "sm" | "md" | "lg";
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
};

function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      viewBox="0 0 1254 1254"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        fill="#272e3e"
        fillRule="evenodd"
        d="M810.6 612.93a187.5 187.5 0 1 1-375 0 187.5 187.5 0 1 1 375 0ZM803.5 498a67.1 67.1 0 1 0-134.2 0 67.1 67.1 0 1 0 134.2 0Z"
      />
      <path
        d="M899.77 582.87a278.3 278.3 0 0 1-429.06 262.93"
        stroke="#575e72"
        strokeWidth="65.7"
        strokeLinecap="round"
      />
      <path
        d="M370.08 748.6a287.1 287.1 0 0 1 347.44-406.8"
        stroke="#202737"
        strokeWidth="68.5"
        strokeLinecap="round"
      />
      <circle cx="845.4" cy="435.5" r="50.2" fill="#7e89cb" />
    </svg>
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
