import { JetBrains_Mono, Noto_Sans_SC, Plus_Jakarta_Sans } from "next/font/google";

/** Latin UI — Plus Jakarta Sans */
export const fontSansLatin = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-sans-latin",
  display: "swap",
});

/** CJK body — Noto Sans SC */
export const fontSansCjk = Noto_Sans_SC({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans-cjk",
  display: "swap",
});

/** Mono — JetBrains Mono (IDs, code, tokens) */
export const fontMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const fontVariables = [
  fontSansLatin.variable,
  fontSansCjk.variable,
  fontMono.variable,
].join(" ");
