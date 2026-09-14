import assert from "node:assert/strict";
import test from "node:test";

import { listCoWriterDocuments } from "../lib/co-writer-api";

test("co-writer errors surface the server detail", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        detail: "This learning account cannot use the requested server surface.",
      }),
      { status: 403, headers: { "Content-Type": "application/json" } },
    );

  try {
    await assert.rejects(
      listCoWriterDocuments(),
      (error: unknown) =>
        error instanceof Error &&
        error.message ===
          "This learning account cannot use the requested server surface.",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("co-writer errors keep their fallback for non-detail bodies", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response("proxy failed", { status: 502 });

  try {
    await assert.rejects(
      listCoWriterDocuments(),
      (error: unknown) =>
        error instanceof Error &&
        error.message === "Request failed (502): proxy failed",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
