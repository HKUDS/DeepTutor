import test from "node:test";
import assert from "node:assert/strict";

import { listLearningRecords } from "../lib/learning-records-api";

test("learning records request the account reading summary", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let requestedInit: RequestInit | undefined;
  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    requestedUrl = String(input);
    requestedInit = init;
    return new Response(
      JSON.stringify({
        progress: [],
        activities: [],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    const records = await listLearningRecords();
    assert.equal(requestedUrl, "/api/v1/learning/reading/records");
    assert.equal(requestedInit?.method, undefined);
    assert.deepEqual(requestedInit?.credentials, "include");
    assert.deepEqual(records, { progress: [], activities: [] });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("learning records preserve the backend's two-part response shape", async () => {
  const originalFetch = globalThis.fetch;
  const payload = {
    progress: [
      {
        material_id: "rm_one",
        latest_locator: 3,
        latest_percentage: 0.3,
        furthest_locator: 5,
        furthest_percentage: 0.5,
        updated_at: 1,
      },
    ],
    activities: [
      {
        activity_id: "racc_one",
        material_id: "rm_one",
        extension_id: "guided_learning",
        action: "guide",
        locator: 4,
        result_type: "card",
        created_at: 2,
      },
    ],
  };
  globalThis.fetch = async () =>
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });

  try {
    assert.deepEqual(await listLearningRecords(), payload);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
