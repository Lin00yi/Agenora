import type { Config } from "tailwindcss";
import tailwindcssAnimate from "tailwindcss-animate";
import plugin from "tailwindcss/plugin";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "PingFang SC",
          "Microsoft YaHei",
          "system-ui",
          "sans-serif",
        ],
        mono: ["Menlo", "Monaco", "Consolas", "monospace"],
      },
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        card: {
          DEFAULT: "var(--card)",
          foreground: "var(--card-foreground)",
        },
        popover: {
          DEFAULT: "var(--popover)",
          foreground: "var(--popover-foreground)",
        },
        primary: {
          DEFAULT: "var(--primary)",
          foreground: "var(--primary-foreground)",
        },
        secondary: {
          DEFAULT: "var(--secondary)",
          foreground: "var(--secondary-foreground)",
        },
        muted: {
          DEFAULT: "var(--muted)",
          foreground: "var(--muted-foreground)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          foreground: "var(--accent-foreground)",
        },
        destructive: {
          DEFAULT: "var(--destructive)",
          foreground: "var(--destructive-foreground, var(--foreground))",
        },
        border: "var(--border)",
        input: "var(--input)",
        ring: "var(--ring)",
        brand: "rgb(var(--brand) / <alpha-value>)",
        "brand-dark": "rgb(var(--brand-dark) / <alpha-value>)",
        subtle: "rgb(var(--text-subtle) / <alpha-value>)",
        // Legacy aliases used across the app (gradual migration)
        bg: "rgb(var(--bg) / <alpha-value>)",
        fg: "rgb(var(--fg) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        "surface-2": "rgb(var(--surface-2) / <alpha-value>)",
        "surface-border": "rgb(var(--surface-border) / <alpha-value>)",
        "border-strong": "rgb(var(--surface-border-strong) / <alpha-value>)",
        success: "rgb(var(--success) / <alpha-value>)",
        warning: "rgb(var(--warning) / <alpha-value>)",
        danger: "rgb(var(--danger) / <alpha-value>)",
        info: "rgb(var(--info) / <alpha-value>)",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      boxShadow: {
        soft: "0 1px 2px 0 rgb(var(--fg) / 0.04), 0 1px 1px 0 rgb(var(--fg) / 0.02)",
        lift: "0 4px 12px -2px rgb(var(--fg) / 0.08), 0 2px 4px 0 rgb(var(--fg) / 0.04)",
      },
      ringWidth: {
        3: "3px",
      },
      transitionDuration: {
        press: "var(--duration-press)",
        popover: "var(--duration-popover)",
        surface: "var(--duration-surface)",
      },
      transitionTimingFunction: {
        "ui-out": "var(--ease-out)",
        "ui-in-out": "var(--ease-in-out)",
        "ui-drawer": "var(--ease-drawer)",
      },
    },
  },
  plugins: [
    tailwindcssAnimate,
    // shadcn v4 presets use Tailwind v4 utilities — polyfill for v3
    plugin(({ addUtilities }) => {
      addUtilities({
        ".outline-hidden": { outline: "2px solid transparent", "outline-offset": "2px" },
        // Legacy secondary text — avoids collision with shadcn --muted
        ".text-muted": { color: "rgb(var(--text-subtle))" },
      });
    }),
  ],
};
export default config;
