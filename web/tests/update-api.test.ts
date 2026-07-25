import test from "node:test";
import assert from "node:assert/strict";
import { fetchUpdateStatus } from "../lib/update-api";

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
