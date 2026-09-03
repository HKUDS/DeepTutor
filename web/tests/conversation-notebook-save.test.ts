import assert from "node:assert/strict";
import test from "node:test";

import type { MessageItem } from "@/features/chat/ChatStateAdapter";
import { buildConversationNotebookSave } from "@/lib/conversation-notebook-save";

test("workspace transcripts share one selectable notebook payload", () => {
  const messages: MessageItem[] = [
    { role: "user", content: "Explain eigenvectors" },
    { role: "assistant", content: "Think of directions that do not rotate." },
  ];

  const save = buildConversationNotebookSave(messages, {
    source: "mastery_path",
    fallbackTitle: "Linear algebra",
    activeCapability: "mastery_path",
    language: "en",
    sessionId: "session-1",
  });

  assert.equal(save.payload?.title, "Explain eigenvectors");
  assert.deepEqual(save.modalMessages, [
    { role: "user", content: "Explain eigenvectors", capability: undefined },
    {
      role: "assistant",
      content: "Think of directions that do not rotate.",
      capability: undefined,
    },
  ]);
  assert.deepEqual(save.payload?.metadata, {
    source: "mastery_path",
    capability: "mastery_path",
    ui_language: "en",
    session_id: "session-1",
    total_message_count: 2,
  });
});

test("empty transcripts cannot open the save flow", () => {
  const save = buildConversationNotebookSave([], {
    source: "mastery_path",
    fallbackTitle: "Mastery Path",
    activeCapability: null,
    language: "en",
    sessionId: null,
  });

  assert.equal(save.payload, null);
  assert.deepEqual(save.modalMessages, []);
});
