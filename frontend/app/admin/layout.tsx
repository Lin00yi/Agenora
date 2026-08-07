"use client";

import type { ReactNode } from "react";
import AdminShell from "./AdminShell";

/**
 * Shared chrome for /admin/* so tab switches remount only page content,
 * not the header/auth shell.
 */
export default function AdminLayout({ children }: { children: ReactNode }) {
  return <AdminShell>{children}</AdminShell>;
}
