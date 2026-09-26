import { afterEach, describe, expect, it, vi } from "vitest";

import {
  importChatHistory,
  importChatHistoryInBatches,
} from "@/lib/imports-api";
import type { NormalizedSession } from "@/lib/chat-import/types";

describe("importChatHistory", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("does not send an empty import request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(importChatHistory("codex", [])).rejects.toThrow(
      "No sessions to import",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("uploads large static exports in bounded batches", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            imported: 2,
            skipped: 0,
            sessions: [
              { external_id: "s1", imported: true },
              { external_id: "s2", imported: true },
            ],
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            imported: 0,
            skipped: 1,
            sessions: [{ external_id: "s3", imported: false }],
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const sessions = ["s1", "s2", "s3"].map(
      (external_id): NormalizedSession => ({
        external_id,
        title: external_id,
        source_cwd: "",
        created_at: 1,
        updated_at: 1,
        messages: [{ role: "user", content: "hello" }],
      }),
    );
    const progress: number[] = [];

    const result = await importChatHistoryInBatches("chatgpt", sessions, {
      batchSize: 2,
      onProgress: (done) => progress.push(done),
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const firstBody = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    const secondBody = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(firstBody.source).toBe("chatgpt");
    expect(firstBody.sessions).toHaveLength(2);
    expect(secondBody.sessions).toHaveLength(1);
    expect(progress).toEqual([2, 3]);
    expect(result).toMatchObject({ imported: 2, skipped: 1 });
    expect(result.sessions).toHaveLength(3);
  });
});
