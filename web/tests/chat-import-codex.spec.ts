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

  // Codex delivers its own context to the model as `role: "user"` items. The
  // session this came from had exactly one user turn — a 4KB plugin catalogue
  // — so the import gave the learner a message they never wrote and a title
  // made of it (#1354).
  it("drops the harness's own injected turns, whatever they are tagged", async () => {
    const injected = (text: string) => ({
      timestamp: "2026-06-25T10:00:01Z",
      type: "response_item",
      payload: {
        type: "message",
        role: "user",
        content: [{ type: "input_text", text }],
      },
    });
    const ref = sessionRef([
      {
        timestamp: "2026-06-25T10:00:00Z",
        type: "session_meta",
        payload: { id: "session-1", cwd: "/workspace/project", thread_source: "user" },
      },
      injected("<recommended_plugins>\nAirtable, Alpaca, …\n</recommended_plugins>\n<environment_context>\n  <shell>zsh</shell>\n</environment_context>"),
      injected('<codex_internal_context source="goal">\nContinue the thread goal.\n</codex_internal_context>'),
      injected("<turn_aborted>\nThe user interrupted the previous turn.\n</turn_aborted>"),
      {
        timestamp: "2026-06-25T10:00:02Z",
        type: "response_item",
        payload: {
          type: "message",
          role: "user",
          content: [{ type: "input_text", text: "Explain Fourier transforms" }],
        },
      },
    ]);

    const parsed = await parseCodexSession(ref);

    expect(parsed?.messages.map((message) => message.content)).toEqual([
      "Explain Fourier transforms",
    ]);
    expect(parsed?.title).toBe("Explain Fourier transforms");
  });

  // The most common machine prefix of all, and the one that must survive: an
  // attachment turn is `<image …></image>` followed by the actual question.
  it("keeps a turn whose markup is only a prefix to what the person typed", async () => {
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
          role: "user",
          content: [
            {
              type: "input_text",
              text: "<image name=[Image #1]></image>[Image #1] Can you read this chart?",
            },
          ],
        },
      },
    ]);

    const parsed = await parseCodexSession(ref);

    expect(parsed?.messages).toHaveLength(1);
    expect(parsed?.messages[0].content).toContain("Can you read this chart?");
  });

  // A person pasting markup with no prose is the false positive this trades
  // away, so keep the trade narrow: anything that does not close cleanly, or
  // that has a single character outside the elements, stays.
  it("keeps markup that does not resolve into whole top-level elements", async () => {
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
          role: "user",
          content: [{ type: "input_text", text: "<config>\n  <port>8080</port>\nwhy does this fail?" }],
        },
      },
    ]);

    const parsed = await parseCodexSession(ref);

    expect(parsed?.messages[0].content).toContain("why does this fail?");
  });
});
