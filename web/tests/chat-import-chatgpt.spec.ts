import { File as NodeFile } from "node:buffer";

import { describe, expect, it } from "vitest";

import {
  parseChatGptExport,
  parseChatGptExportFile,
} from "@/lib/chat-import/chatgpt";
import { ImportScanError } from "@/lib/chat-import/types";

function node(
  id: string,
  parent: string | null,
  role: string,
  content: unknown,
  createdAt: number,
  options?: { children?: string[]; hidden?: boolean },
) {
  return {
    id,
    parent,
    children: options?.children ?? [],
    message: {
      id: `message-${id}`,
      author: { role },
      create_time: createdAt,
      content: { content_type: "text", parts: [content] },
      metadata: options?.hidden
        ? { is_visually_hidden_from_conversation: true }
        : {},
    },
  };
}

describe("parseChatGptExport", () => {
  it("keeps only the active branch and visible user/assistant messages", () => {
    const parsed = parseChatGptExport([
      {
        id: "conversation-1",
        title: "Calculus review",
        create_time: 100,
        update_time: 140,
        current_node: "a-current",
        mapping: {
          root: node("root", null, "system", "hidden prompt", 100, {
            children: ["u1"],
          }),
          u1: node("u1", "root", "user", "Explain the chain rule", 110, {
            children: ["a-old", "a-current"],
          }),
          "a-old": node("a-old", "u1", "assistant", "Old branch", 120),
          "a-current": node(
            "a-current",
            "u1",
            "assistant",
            { text: "Differentiate the outer function first." },
            130,
          ),
        },
      },
    ]);

    expect(parsed).toEqual([
      {
        external_id: "conversation-1",
        title: "Calculus review",
        source_cwd: "",
        created_at: 100,
        updated_at: 140,
        messages: [
          {
            role: "user",
            content: "Explain the chain rule",
            created_at: 110,
          },
          {
            role: "assistant",
            content: "Differentiate the outer function first.",
            created_at: 130,
          },
        ],
      },
    ]);
  });

  it("chooses the newest leaf when current_node is absent", () => {
    const parsed = parseChatGptExport([
      {
        conversation_id: "conversation-2",
        title: "",
        mapping: {
          user: node("user", null, "user", "Original question", 10, {
            children: ["older", "newer"],
          }),
          older: node("older", "user", "assistant", "Older answer", 20),
          newer: node("newer", "user", "assistant", "Newer answer", 30),
        },
      },
    ]);

    expect(parsed[0].title).toBe("Original question");
    expect(parsed[0].messages.map((message) => message.content)).toEqual([
      "Original question",
      "Newer answer",
    ]);
  });

  it("skips hidden, tool, and non-text media rows without breaking lineage", () => {
    const parsed = parseChatGptExport([
      {
        id: "conversation-3",
        current_node: "assistant",
        mapping: {
          user: node("user", null, "user", "Read this chart", 10, {
            children: ["hidden"],
          }),
          hidden: node("hidden", "user", "assistant", "internal", 11, {
            children: ["tool"],
            hidden: true,
          }),
          tool: node("tool", "hidden", "tool", "tool output", 12, {
            children: ["assistant"],
          }),
          assistant: node(
            "assistant",
            "tool",
            "assistant",
            "The trend rises.",
            13,
          ),
        },
      },
    ]);

    expect(parsed[0].messages.map((message) => message.content)).toEqual([
      "Read this chart",
      "The trend rises.",
    ]);
  });

  it("deduplicates repeated conversation ids", () => {
    const conversation = {
      id: "same-id",
      current_node: "user",
      mapping: { user: node("user", null, "user", "Keep once", 10) },
    };
    expect(parseChatGptExport([conversation, conversation])).toHaveLength(1);
  });

  it("rejects malformed JSON and exports without readable conversations", async () => {
    const invalid = new NodeFile(["{"], "conversations.json");
    await expect(
      parseChatGptExportFile(invalid as unknown as File),
    ).rejects.toMatchObject({
      code: "invalid_export",
    });

    expect(() => parseChatGptExport({ conversations: [] })).toThrow(
      ImportScanError,
    );
    expect(() =>
      parseChatGptExport([
        { id: "empty", current_node: "root", mapping: { root: {} } },
      ]),
    ).toThrow(/no readable ChatGPT conversations/i);
  });
});
