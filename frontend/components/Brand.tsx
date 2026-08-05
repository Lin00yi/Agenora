import { cn } from "@/lib/cn";

export const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME || "KnowFlow";

type BrandSize = "sm" | "md" | "lg";
type BrandTone = "solid" | "soft";

type BrandProps = {
  size?: BrandSize;
  showWordmark?: boolean;
  /** solid = filled ink mark (default); soft = quiet surface mark for sidebars */
  tone?: BrandTone;
  className?: string;
};

const SIZES: Record<BrandSize, { box: string; mark: string; text: string }> = {
  sm: {
    box: "h-7 w-7 rounded-lg",
    mark: "h-5 w-5",
    text: "text-sm font-semibold",
  },
  md: {
    box: "h-8 w-8 rounded-lg",
    mark: "h-6 w-6",
    text: "text-base font-semibold",
  },
  lg: {
    box: "h-14 w-14 rounded-lg",
    mark: "h-10 w-10",
    text: "text-3xl font-semibold tracking-tight sm:text-4xl",
  },
};

function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      viewBox="0 0 64 64"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M18 12h21.8L50 22.2V50H18V12Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="5"
      />
      <path
        d="M40 13v12h10"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="5"
      />
      <path
        d="M26 28h12M26 38h20"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="5"
      />
      <path
        d="M14 21H9v31h28v-5"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeOpacity=".58"
        strokeWidth="5"
      />
      <circle cx="49" cy="43" r="4" fill="currentColor" />
    </svg>
  );
}

export default function Brand({
  size = "md",
  showWordmark = true,
  tone = "solid",
  className,
}: BrandProps) {
  const s = SIZES[size];
  const soft = tone === "soft";
  return (
    <div className={cn("inline-flex items-center gap-2", className)}>
      <div
        className={cn(
          "kf-brand-mark relative isolate flex items-center justify-center overflow-hidden",
          soft
            ? "border border-surface-border bg-surface-2 text-ink shadow-none"
            : [
                "bg-ink text-on-brand shadow-soft ring-1 ring-white/20",
                "before:absolute before:inset-0 before:bg-[radial-gradient(circle_at_70%_18%,rgba(255,255,255,0.22),transparent_28%)]",
                "after:absolute after:inset-x-1 after:bottom-1 after:h-px after:bg-white/20",
                "dark:bg-ink dark:ring-white/15",
              ],
          s.box
        )}
        aria-hidden
      >
        <BrandMark className={cn("relative z-10", !soft && "drop-shadow-sm", s.mark)} />
      </div>
      {showWordmark && <span className={s.text}>{APP_NAME}</span>}
    </div>
  );
}
