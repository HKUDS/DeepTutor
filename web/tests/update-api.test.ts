import test from "node:test";
import assert from "node:assert/strict";
import {
  fetchUpdateJob,
  fetchUpdateStatus,
  requestWebUpdate,
} from "../lib/update-api";

test("fetchUpdateStatus returns the system update payload", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  globalThis.fetch = async (input) => {
    requestedUrl = String(input);
    return new Response(
      JSON.stringify({
        status: "available",
        current_version: "1.5.4",
        latest_version: "1.6.0",
        install_mode: "pypi",
        can_auto_update: true,
        release_url:
          "https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.0",
        detail: "installed distribution",
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    const result = await fetchUpdateStatus();

    assert.equal(requestedUrl, "/api/v1/system/update");
    assert.equal(result.status, "available");
    assert.equal(result.latest_version, "1.6.0");
    assert.equal(result.install_mode, "pypi");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("fetchUpdateStatus preserves API error details", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: "Release provider unavailable" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });

  try {
    await assert.rejects(fetchUpdateStatus(), {
      message: "Release provider unavailable",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("requestWebUpdate sends the fixed restart confirmation", async () => {
  const originalFetch = globalThis.fetch;
  let request: RequestInit | undefined;
  globalThis.fetch = async (_input, init) => {
    request = init;
    return new Response(
      JSON.stringify({
        id: "job-1",
        status: "pending",
        current_version: "1.5.4",
        target_version: "1.6.0",
        error: null,
        restart_count: 0,
      }),
      { status: 202, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    const job = await requestWebUpdate();

    assert.equal(request?.method, "POST");
    assert.equal(request?.body, JSON.stringify({ confirmation: "update-and-restart" }));
    assert.equal(job.status, "pending");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("fetchUpdateJob restores a persisted restart state", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        id: "job-1",
        status: "restarting",
        current_version: "1.5.4",
        target_version: "1.6.0",
        error: null,
        restart_count: 1,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );

  try {
    assert.equal((await fetchUpdateJob())?.status, "restarting");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
