import { afterEach, describe, expect, it, vi } from "vitest";

import { importChatHistory } from "@/lib/imports-api";

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
});
