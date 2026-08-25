import { redirect } from "next/navigation";

export default async function KnowledgeGraphRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/kbs/${id}?tab=graph`);
}
