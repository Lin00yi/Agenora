import { KbWorkspaceShell } from "@/components/kb/KbWorkspaceShell";

export default async function KnowledgeBaseLayout({ children, params }: { children: React.ReactNode; params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <KbWorkspaceShell kbId={id}>{children}</KbWorkspaceShell>;
}
