"use client";

import { Suspense } from "react";
import { NewConversationChatPage } from "@/components/ChatPageClient";
import { ChatLoadingShell } from "@/components/chat";

export default function NewConversationPage() {
  return (
    <Suspense fallback={<ChatLoadingShell animated={false} label="正在打开工作台" />}>
      <NewConversationChatPage />
    </Suspense>
  );
}
