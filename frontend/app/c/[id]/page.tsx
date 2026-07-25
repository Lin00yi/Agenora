import { ChatPage } from "@/components/ChatPageClient";

export default function ConversationPage({ params }: { params: { id: string } }) {
  return <ChatPage routeConversationId={params.id} />;
}
