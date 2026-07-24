import { ChatPage } from "../../page";

export default function ConversationPage({ params }: { params: { id: string } }) {
  return <ChatPage routeConversationId={params.id} />;
}
