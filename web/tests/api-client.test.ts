import assert from "node:assert/strict";
import test from "node:test";

import {
  requestBlob,
  requestJson,
  requestVoid,
  setRuntimeAuthEnabled,
} from "../shared/api/client";
import { ApiError } from "../shared/api/errors";

function withFetch(stub: typeof fetch): () => void {
  const original = globalThis.fetch;
  globalThis.fetch = stub;
  return () => {
    globalThis.fetch = original;
  };
}

async function expectApiError(run: () => Promise<unknown>): Promise<ApiError> {
  try {
    await run();
  } catch (error) {
    assert.ok(error instanceof ApiError);
    return error;
  }
  assert.fail("expected an ApiError");
}

test("requestJson returns typed JSON and requestVoid accepts empty success", async () => {
  let count = 0;
  const restore = withFetch(async () => {
    count += 1;
    return count === 1
      ? Response.json({ worker_count: 4 })
      : new Response(null, { status: 204 });
  });
  try {
    assert.deepEqual(await requestJson<{ worker_count: number }>("/runtime"), {
      worker_count: 4,
    });
    await requestVoid("/turn", { method: "DELETE" });
  } finally {
    restore();
  }
});

test("requestBlob preserves binary bodies", async () => {
  const restore = withFetch(async () => new Response("artifact"));
  try {
    assert.equal(await (await requestBlob("/artifact")).text(), "artifact");
  } finally {
    restore();
  }
});

test("structured server errors retain stable fields and correlation IDs", async () => {
  const restore = withFetch(async () =>
    Response.json(
      { error_code: "worker_lost", message: "Owner exited", retryable: true },
      { status: 503, headers: { "x-correlation-id": "corr-7" } },
    ),
  );
  try {
    const error = await expectApiError(() =>
      requestJson("/turn", { scope: "turn" }),
    );
    assert.deepEqual(error.appError, {
      code: "worker_lost",
      message: "Owner exited",
      retryable: true,
      scope: "turn",
      correlationId: "corr-7",
      status: 503,
    });
  } finally {
    restore();
  }
});

test("invalid JSON success becomes a normalized response error", async () => {
  const restore = withFetch(
    async () =>
      new Response("not-json", { headers: { "x-request-id": "req-1" } }),
  );
  try {
    const error = await expectApiError(() => requestJson("/broken"));
    assert.equal(error.code, "invalid_response");
    assert.equal(error.correlationId, "req-1");
  } finally {
    restore();
  }
});

test("abort and network failures are distinguishable", async () => {
  const restoreAbort = withFetch(async () => {
    throw new DOMException("aborted", "AbortError");
  });
  try {
    const aborted = await expectApiError(() => requestJson("/turn"));
    assert.equal(aborted.code, "request_aborted");
    assert.equal(aborted.retryable, false);
  } finally {
    restoreAbort();
  }

  const restoreNetwork = withFetch(async () => {
    throw new TypeError("offline");
  });
  try {
    const offline = await expectApiError(() => requestJson("/turn"));
    assert.equal(offline.code, "network_error");
    assert.equal(offline.retryable, true);
  } finally {
    restoreNetwork();
  }
});

test("the shared boundary keeps the single apiFetch auth redirect gate", async () => {
  setRuntimeAuthEnabled(false);
  const restore = withFetch(async () =>
    Response.json({ detail: "no" }, { status: 401 }),
  );
  try {
    const error = await expectApiError(() => requestJson("/private"));
    assert.equal(error.status, 401);
  } finally {
    restore();
  }
});
