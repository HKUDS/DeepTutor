import { afterEach, expect, it, vi } from "vitest";

import { deleteMessage } from "@/lib/session-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("passes the detached tutor threads through to the caller", async () => {
  const fetchMock = vi.fn(async () =>
    Response.json({
      deleted: true,
      detached_thread_ids: ["thread-1", "thread-2"],
      deleted_message_ids: [7, 8],
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await expect(deleteMessage("session-1", 7)).resolves.toEqual({
    detachedThreadIds: ["thread-1", "thread-2"],
    deletedMessageIds: [7, 8],
  });
  expect(fetchMock).toHaveBeenCalledWith(
    expect.stringContaining("/api/sessions/session-1/messages/7"),
    expect.objectContaining({ method: "DELETE" }),
  );
});

it("returns no threads when an older server omits the list", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ deleted: true })),
  );

  await expect(deleteMessage("session-1", 7)).resolves.toEqual({
    detachedThreadIds: [],
    deletedMessageIds: [7],
  });
});
