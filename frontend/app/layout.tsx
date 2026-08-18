import type { Metadata } from "next";
import { Toaster } from "sonner";
import { PreviewPanelProvider } from "@/components/preview/PreviewPanelProvider";
import { ThemeProvider } from "@/components/ThemeProvider";
import { fontVariables } from "@/lib/fonts";
import "./globals.css";

const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME || "Agenora";

export const metadata: Metadata = {
  title: APP_NAME,
  description: "把任意知识库变成可对话的资料助手：上传文档、抓取网页，然后一句话问出答案。",
  icons: {
    icon: [{ url: "/logo.svg", type: "image/svg+xml" }],
  },
};

// Runs before paint so the dark class is applied before the first frame.
const NO_FLASH = `(function(){try{var t=localStorage.getItem('agenora:theme')||localStorage.getItem('anykb:theme')||'system';var d=t==='dark'||(t==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.classList.toggle('dark',d);}catch(e){}})()`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className={fontVariables} suppressHydrationWarning>
      <head>
        {/* eslint-disable-next-line react/no-danger */}
        <script dangerouslySetInnerHTML={{ __html: NO_FLASH }} />
      </head>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <ThemeProvider>
          <PreviewPanelProvider>
            {children}
            <Toaster
              position="top-center"
              richColors
              closeButton
              containerAriaLabel="通知"
              duration={5000}
              gap={10}
              visibleToasts={4}
              pauseWhenPageIsHidden
              className="agenora-toaster"
              toastOptions={{
                classNames: {
                  toast: "agenora-toast",
                  title: "agenora-toast-title",
                  description: "agenora-toast-description",
                  icon: "agenora-toast-icon",
                  closeButton: "agenora-toast-close",
                  actionButton: "agenora-toast-action",
                  cancelButton: "agenora-toast-cancel",
                },
              }}
            />
          </PreviewPanelProvider>
        </ThemeProvider>
        {process.env.NEXT_PUBLIC_PLAUSIBLE_DOMAIN && (
          /* eslint-disable-next-line @next/next/no-sync-scripts */
          <script
            defer
            data-domain={process.env.NEXT_PUBLIC_PLAUSIBLE_DOMAIN}
            src="https://plausible.io/js/script.js"
          />
        )}
      </body>
    </html>
  );
}
