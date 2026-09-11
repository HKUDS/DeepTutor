import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  checkAppUpdate,
  fetchAppUpdateJob,
  fetchAppUpdateStatus,
  requestAppUpdate,
  setAppUpdateChecks,
  subscribeAppUpdateStatus,
  updateJobIsActive,
} from "../lib/app-update";

const statusPayload = {
  current_version: "1.6.1",
  check_enabled: true,
  checked_at: "2026-08-30T00:00:00Z",
  cached: false,
  check_error: "",
  update_available: true,
  release: {
    version: "1.7.0",
    name: "DeepTutor 1.7",
    published_at: "2026-08-30T00:00:00Z",
    url: "https://github.com/HKUDS/DeepTutor/releases/tag/v1.7.0",
    excerpt: "A stable release.",
    migration_warning: false,
  },
  installation: {
    mode: "pypi",
    automatic_update: true,
    command: "pip install -U deeptutor",
    reason: "",
  },
  launcher_managed: true,
  is_admin: true,
  job: null,
} as const;

const jobPayload = {
  id: "job-1",
  status: "pending",
  current_version: "1.6.1",
  target_version: "1.7.0",
  created_at: "2026-08-30T00:00:00Z",
  started_at: null,
  finished_at: null,
  error: null,
  restart_count: 0,
} as const;

test("app update client uses the canonical system routes", async () => {
  const requests: Array<{ path: string; method: string; body?: string }> = [];
  const signals: Array<{ version?: string; error: string }> = [];
  const unsubscribe = subscribeAppUpdateStatus((signal) => {
    signals.push({
      version: signal.status?.current_version,
      error: signal.error,
    });
  });
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    requests.push({
      path: String(input),
      method: init?.method ?? "GET",
      body: typeof init?.body === "string" ? init.body : undefined,
    });
    const updateRequest =
      String(input) === "/api/system/update" && init?.method === "POST";
    const body =
      String(input).endsWith("/job") || updateRequest
        ? jobPayload
        : statusPayload;
    return new Response(JSON.stringify(body), {
      status: updateRequest ? 202 : 200,
      headers: { "content-type": "application/json" },
    });
  };

  try {
    assert.equal((await fetchAppUpdateStatus()).current_version, "1.6.1");
    assert.equal((await checkAppUpdate()).release?.version, "1.7.0");
    assert.equal((await setAppUpdateChecks(false)).check_enabled, true);
    assert.equal((await requestAppUpdate()).id, "job-1");
    assert.equal((await fetchAppUpdateJob())?.id, "job-1");
  } finally {
    globalThis.fetch = originalFetch;
    unsubscribe();
  }

  assert.deepEqual(
    requests.map(({ path, method }) => ({ path, method })),
    [
      { path: "/api/system/update", method: "GET" },
      { path: "/api/system/update/check", method: "POST" },
      { path: "/api/system/update/settings", method: "PUT" },
      { path: "/api/system/update", method: "POST" },
      { path: "/api/system/update/job", method: "GET" },
    ],
  );
  assert.equal(requests[2]?.body, JSON.stringify({ enabled: false }));
  assert.equal(
    requests[3]?.body,
    JSON.stringify({ confirmation: "update-and-restart" }),
  );
  assert.deepEqual(signals, [
    { version: "1.6.1", error: "" },
    { version: "1.6.1", error: "" },
    { version: "1.6.1", error: "" },
  ]);
});

test("failed version checks notify compact status surfaces", async () => {
  const signals: string[] = [];
  const unsubscribe = subscribeAppUpdateStatus((signal) =>
    signals.push(signal.error),
  );
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: "Unable to check for updates" }), {
      status: 503,
      headers: { "content-type": "application/json" },
    });

  try {
    await assert.rejects(checkAppUpdate(), /Unable to check for updates/);
  } finally {
    globalThis.fetch = originalFetch;
    unsubscribe();
  }

  assert.deepEqual(signals, ["Unable to check for updates"]);
});

test("app update client preserves FastAPI error details", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({ detail: "Finish the active conversation." }),
      {
        status: 409,
        headers: { "content-type": "application/json" },
      },
    );

  try {
    await assert.rejects(requestAppUpdate(), /Finish the active conversation/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("only non-terminal jobs remain active", () => {
  for (const status of [
    "pending",
    "handoff",
    "running",
    "restarting",
  ] as const) {
    assert.equal(updateJobIsActive(status), true);
  }
  assert.equal(updateJobIsActive("succeeded"), false);
  assert.equal(updateJobIsActive("failed"), false);
});

test("sidebar presents the version as a synced status dot and branded footer marks", () => {
  const badge = readFileSync(
    path.join(process.cwd(), "components", "sidebar", "VersionBadge.tsx"),
    "utf8",
  );
  const shell = readFileSync(
    path.join(process.cwd(), "components", "sidebar", "SidebarShell.tsx"),
    "utf8",
  );

  assert.match(badge, /subscribeAppUpdateStatus/);
  assert.match(badge, /font-serif/);
  assert.match(badge, /bg-emerald-500/);
  assert.match(badge, /bg-amber-500/);
  assert.match(badge, /bg-red-500/);
  // The footer GitHub mark is now an inline CC0 octocat (kept out of the
  // app-shell chunk) instead of a lookup into the generated brand table.
  assert.match(shell, /GitHubMarkLink/);
  assert.match(shell, /GITHUB_REPO_URL/);
  assert.match(shell, /GITHUB_MARK_PATH/);
  assert.match(shell, /text-\[#181717\] dark:text-white/);
  assert.match(shell, /text-blue-600 dark:text-blue-400/);
});
