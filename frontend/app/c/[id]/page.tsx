import { redirect } from "next/navigation";

export default function ConversationPage({ params }: { params: { id: string } }) {
  redirect(`/?conversation=${encodeURIComponent(params.id)}`);
}
