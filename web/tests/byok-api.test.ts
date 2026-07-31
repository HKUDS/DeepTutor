import assert from "node:assert/strict";
import test from "node:test";

import { saveByokProfile } from "../features/byok/api";
import { parseEndpointAllowlist, readApiError } from "../features/byok/helpers";

test("BYOK endpoint allowlist parsing waits until save and preserves complete draft lines", () => {
  const draft = "  https://api.example.com/v1/  \r\n\nhttps://backup.example.com/v1\n";

  assert.deepEqual(parseEndpointAllowlist(draft), [
    "https://api.example.com/v1/",
    "https://backup.example.com/v1",
  ]);
});

test("BYOK API errors support FastAPI validation details and non-JSON fallbacks", async () => {
  const validation = new Response(
    JSON.stringify({ detail: [{ msg: "field required" }, { msg: "invalid URL" }] }),
    { status: 422, headers: { "Content-Type": "application/json" } },
  );
  assert.equal(await readApiError(validation, "fallback"), "field required; invalid URL");

  const nonJson = new Response("proxy error", { status: 502 });
  assert.equal(await readApiError(nonJson, "fallback"), "fallback");
});

test("BYOK profile updates always include the generation token", async () => {
  const originalFetch = globalThis.fetch;
  let requestUrl = "";
  let requestMethod = "";
  let requestBody = "";
  (globalThis as { fetch: typeof fetch }).fetch = async (input, init) => {
    requestUrl = String(input);
    requestMethod = init?.method || "GET";
    requestBody = String(init?.body || "");
    return new Response(
      JSON.stringify({
        profile: {
          id: "profile-1",
          service: "llm",
          provider: "openai",
          generation: 1,
        },
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    await saveByokProfile({
      profileId: "profile-1",
      service: "llm",
      provider: "openai",
      generation: 0,
    });
  } finally {
    (globalThis as { fetch: typeof fetch }).fetch = originalFetch;
  }

  assert.equal(requestUrl, "/api/v1/byok/profiles/profile-1");
  assert.equal(requestMethod, "PATCH");
  const body = JSON.parse(requestBody) as { generation?: number | null };
  assert.equal(Object.hasOwn(body, "generation"), true);
  assert.equal(body.generation, 0);
});
