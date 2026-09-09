import { File as NodeFile } from "node:buffer";

import { describe, expect, it } from "vitest";

import { parseCodexSession } from "@/lib/chat-import/codex";
import type { SessionRef } from "@/lib/chat-import/types";

function sessionRef(records: unknown[]): SessionRef {
  const jsonl = records.map((record) => JSON.stringify(record)).join("\n");
  const file = new NodeFile([jsonl], "rollout-test.jsonl", {
    lastModified: Date.parse("2026-06-25T12:00:00Z"),
  });

  return {
    externalId: "session-1",
    provisionalTitle: "",
    cwd: "/workspace/project",
    date: "2026-06-25",
    lastModified: file.lastModified,
    sizeBytes: file.size,
    handle: {
      getFile: async () => file as unknown as File,
    } as FileSystemFileHandle,
  };
}

describe("parseCodexSession", () => {
  it("parses current response_item message records", async () => {
    const ref = sessionRef([
      {
        timestamp: "2026-06-25T10:00:00Z",
        type: "session_meta",
        payload: { id: "session-1", cwd: "/workspace/project", thread_source: "user" },
      },
      {
        timestamp: "2026-06-25T10:00:01Z",
        type: "response_item",
        payload: {
          type: "message",
          role: "developer",
          content: [{ type: "input_text", text: "hidden instructions" }],
        },
      },
      {
        timestamp: "2026-06-25T10:00:02Z",
        type: "response_item",
        payload: {
          type: "message",
          role: "user",
          content: [{ type: "input_text", text: "Explain Fourier transforms" }],
        },
      },
      {
        timestamp: "2026-06-25T10:00:03Z",
        type: "response_item",
        payload: {
          type: "message",
          role: "assistant",
          content: [
            { type: "output_text", text: "A Fourier transform" },
            { type: "output_text", text: "decomposes a signal." },
          ],
        },
      },
    ]);

    const parsed = await parseCodexSession(ref);

    expect(parsed).not.toBeNull();
    expect(parsed?.title).toBe("Explain Fourier transforms");
    expect(parsed?.messages).toEqual([
      {
        role: "user",
        content: "Explain Fourier transforms",
        created_at: Date.parse("2026-06-25T10:00:02Z") / 1000,
      },
      {
        role: "assistant",
        content: "A Fourier transform\n\ndecomposes a signal.",
        created_at: Date.parse("2026-06-25T10:00:03Z") / 1000,
      },
    ]);
  });

  it("prefers legacy event messages when both storage layers are present", async () => {
    const ref = sessionRef([
      {
        timestamp: "2026-06-25T10:00:00Z",
        type: "session_meta",
        payload: { cwd: "/workspace/project", thread_source: "user" },
      },
      {
        timestamp: "2026-06-25T10:00:01Z",
        type: "response_item",
        payload: {
          type: "message",
          role: "user",
          content: [{ type: "input_text", text: "duplicate user" }],
        },
      },
      {
        timestamp: "2026-06-25T10:00:01Z",
        type: "event_msg",
        payload: { type: "user_message", message: "legacy user" },
      },
      {
        timestamp: "2026-06-25T10:00:02Z",
        type: "response_item",
        payload: {
          type: "message",
          role: "assistant",
          content: [{ type: "output_text", text: "duplicate assistant" }],
        },
      },
      {
        timestamp: "2026-06-25T10:00:02Z",
        type: "event_msg",
        payload: { type: "agent_message", message: "legacy assistant" },
      },
    ]);

    const parsed = await parseCodexSession(ref);

    expect(parsed?.messages.map((message) => message.content)).toEqual([
      "legacy user",
      "legacy assistant",
    ]);
  });
});
