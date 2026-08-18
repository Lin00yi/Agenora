import { ChatPage } from "@/components/ChatPageClient";

export default async function ConversationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ChatPage routeConversationId={id} />;
}
