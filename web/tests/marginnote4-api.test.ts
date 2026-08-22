import assert from "node:assert/strict";
import test from "node:test";

import { connectMarginNote4Library } from "../lib/knowledge-api";
import {
  getMarginNote4Status,
  listMarginNote4Devices,
  pairMarginNote4Device,
  revokeMarginNote4Device,
} from "../lib/marginnote4-api";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubFetch(
  handler: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
): () => void {
  const original = globalThis.fetch;
  (globalThis as { fetch: typeof fetch }).fetch = handler;
  return () => {
    (globalThis as { fetch: typeof fetch }).fetch = original;
  };
}

const header = (init: RequestInit | undefined, name: string): string | null =>
  new Headers(init?.headers).get(name);

test("every device-bridge call names its library through X-MN4-KB", async () => {
  // The backend derives one SQLite store from this name, so a call that omits
  // it pairs a device into a library the add-on's syncs never look at.
  const calls: { input: string; method: string; kb: string | null }[] = [];
  const restore = stubFetch(async (input, init) => {
    calls.push({
      input: String(input),
      method: init?.method || "GET",
      kb: header(init, "X-MN4-KB"),
    });
    if (String(input).endsWith("/devices") && (init?.method || "GET") === "GET")
      return jsonResponse(200, []);
    return jsonResponse(200, {
      status: "ok",
      devices: 0,
      objects: 0,
      device_id: "d1",
      token: "t1",
      device_name: "",
      device_kind: "macos",
    });
  });
  try {
    await pairMarginNote4Device({ kbName: "My Lib", deviceName: "iPad" });
    await listMarginNote4Devices("My Lib");
    await revokeMarginNote4Device({ kbName: "My Lib", deviceId: "d1" });
    await getMarginNote4Status("My Lib");

    assert.deepEqual(
      calls.map((c) => [c.method, c.input, c.kb]),
      [
        ["POST", "/api/v1/marginnote4/pair", "My Lib"],
        ["GET", "/api/v1/marginnote4/devices", "My Lib"],
        ["DELETE", "/api/v1/marginnote4/devices/d1", "My Lib"],
        ["GET", "/api/v1/marginnote4/status", "My Lib"],
      ],
    );
  } finally {
    restore();
  }
});

test("pairing sends the device name and returns the one-time token", async () => {
  let body: unknown = null;
  const restore = stubFetch(async (_input, init) => {
    body = JSON.parse(String(init?.body));
    return jsonResponse(200, {
      device_id: "dev-1",
      token: "secret",
      device_name: "iPad",
      device_kind: "macos",
    });
  });
  try {
    const pairing = await pairMarginNote4Device({
      kbName: "Lib",
      deviceName: "iPad",
    });
    assert.deepEqual(body, { device_name: "iPad", device_kind: "macos" });
    assert.equal(pairing.token, "secret");
  } finally {
    restore();
  }
});

test("a device id is escaped into the revoke path", async () => {
  let url = "";
  const restore = stubFetch(async (input) => {
    url = String(input);
    return jsonResponse(200, { status: "revoked" });
  });
  try {
    await revokeMarginNote4Device({ kbName: "Lib", deviceId: "a/b?c" });
    assert.equal(url, "/api/v1/marginnote4/devices/a%2Fb%3Fc");
  } finally {
    restore();
  }
});

test("a failed call surfaces the server's detail", async () => {
  const restore = stubFetch(async () =>
    jsonResponse(501, { detail: "pairing and sync would resolve differently" }),
  );
  try {
    await assert.rejects(
      pairMarginNote4Device({ kbName: "Lib", deviceName: "" }),
      /resolve differently/,
    );
  } finally {
    restore();
  }
});

test("connecting a library never pins db_path", async () => {
  // Leaving it blank is what keeps one rule for where the store lives, so
  // pairing, the add-on's syncs and the capability binding cannot disagree.
  let body: Record<string, unknown> = {};
  const restore = stubFetch(async (_input, init) => {
    body = JSON.parse(String(init?.body));
    return jsonResponse(200, { status: "connected", name: "Lib" });
  });
  try {
    await connectMarginNote4Library({ name: "Lib" });
    assert.deepEqual(body, { name: "Lib", description: "" });
    assert.equal("db_path" in body, false);
  } finally {
    restore();
  }
});
