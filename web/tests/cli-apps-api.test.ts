import test from "node:test";
import assert from "node:assert/strict";

import {
  CliAppError,
  getCliApps,
  getCliCatalog,
  installCliApp,
  setCliAppEnabled,
} from "../lib/cli-apps-api";

type Captured = { method: string; url: string; body: unknown };

function stubFetch(
  body: unknown,
  status = 200,
): { calls: Captured[]; restore: () => void } {
  const original = globalThis.fetch;
  const calls: Captured[] = [];
  (globalThis as { fetch: typeof fetch }).fetch = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => {
    calls.push({
      method: init?.method ?? "GET",
      url: String(input),
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };
  return {
    calls,
    restore: () => {
      (globalThis as { fetch: typeof fetch }).fetch = original;
    },
  };
}

test("an app row keeps the two separate facts about availability", async () => {
  // `granted` is the administrator's decision, `enabled` the account's own. A
  // client that collapsed them could not explain why an app is unavailable.
  const stub = stubFetch({
    apps: [
      {
        id: "blender",
        display_name: "Blender",
        tool_name: "cli_blender",
        granted: true,
        enabled: false,
        trust: "first-party",
        pin: "abc123",
      },
    ],
    access: { unrestricted: false, exec_denied: false },
    catalog_pin: "abc123",
  });
  try {
    const state = await getCliApps();
    assert.equal(state.apps[0].granted, true);
    assert.equal(state.apps[0].enabled, false);
    assert.equal(state.apps[0].tool_name, "cli_blender");
    assert.equal(state.catalog_pin, "abc123");
  } finally {
    stub.restore();
  }
});

test("an app the response says nothing about still reads as catalogued", async () => {
  // Treating an absent field as "withdrawn upstream" would put a warning badge
  // on every working app the moment the field is ever dropped.
  const stub = stubFetch({ apps: [{ id: "x" }], access: {} });
  try {
    assert.equal((await getCliApps()).apps[0].in_catalog, true);
  } finally {
    stub.restore();
  }
});

test("a refused install carries its code and its output", async () => {
  // The install log is the only actionable thing about a failed install.
  const stub = stubFetch(
    {
      detail: {
        code: "cli.install_failed",
        message: "`pip` exited 1",
        log: "ERROR: No matching distribution found",
      },
    },
    400,
  );
  try {
    await assert.rejects(
      () => installCliApp("blender"),
      (error: unknown) => {
        assert.ok(error instanceof CliAppError);
        assert.equal(error.code, "cli.install_failed");
        assert.match(error.log, /No matching distribution/);
        assert.match(error.message, /exited 1/);
        return true;
      },
    );
  } finally {
    stub.restore();
  }
});

test("a refusal without a structured detail still surfaces something readable", async () => {
  const stub = stubFetch({ detail: "not allowed" }, 403);
  try {
    await assert.rejects(() => installCliApp("blender"), /not allowed/);
  } finally {
    stub.restore();
  }
});

test("the catalog only sends installable_only when it is being turned off", async () => {
  // The backend defaults it to true; sending it every time makes the URL — and
  // therefore the cache key — differ for identical requests.
  const stub = stubFetch({ entries: [], next_cursor: "", total: 0 });
  try {
    await getCliCatalog({ q: "blend" });
    assert.equal(stub.calls[0].url.includes("installable_only"), false);

    await getCliCatalog({ q: "blend", installableOnly: false });
    assert.ok(stub.calls[1].url.includes("installable_only=false"));
  } finally {
    stub.restore();
  }
});

test("an app id with URL-significant characters is escaped in the path", async () => {
  const stub = stubFetch({ apps: [], access: {} });
  try {
    await setCliAppEnabled("a b/c", true);
    assert.equal(
      stub.calls[0].url,
      "/api/v1/space/cli-apps/apps/a%20b%2Fc/enabled",
    );
    assert.deepEqual(stub.calls[0].body, { enabled: true });
  } finally {
    stub.restore();
  }
});

test("a category count of zero is dropped rather than rendered as a chip", async () => {
  const stub = stubFetch({
    entries: [],
    next_cursor: "",
    total: 0,
    categories: { ai: 3, devops: 0 },
  });
  try {
    const page = await getCliCatalog();
    // The client keeps what the backend sent; the component filters. Pinned here
    // so a future "helpful" filter in the client cannot double-count.
    assert.deepEqual(page.categories, { ai: 3, devops: 0 });
  } finally {
    stub.restore();
  }
});
