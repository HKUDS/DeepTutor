import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  cancelVersionUpdate,
  checkVersionUpdates,
  compareVersionTags,
  getVersionStatus,
  getVersionUpdateStatus,
  isUpdateAvailable,
  startVersionUpdate,
  updateVersionCheckSettings,
} from "../lib/version-check";

const SETTINGS_HUB = path.resolve(
  process.cwd(),
  "components/settings/SettingsHub.tsx",
);
const PANEL = path.resolve(
  process.cwd(),
  "components/settings/VersionUpdatesPanel.tsx",
);

type Captured = { url: string; method: string; body: unknown };

function stubFetch(body: unknown, status = 200) {
  const original = globalThis.fetch;
  const calls: Captured[] = [];
  (globalThis as { fetch: typeof fetch }).fetch = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => {
    calls.push({
      url: String(input),
      method: init?.method ?? "GET",
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
      globalThis.fetch = original;
    },
  };
}

function versionPayload(overrides: Record<string, unknown> = {}) {
  return {
    current_version: "1.5.17",
    latest_release: null,
    checked_at: "",
    cached: false,
    check_enabled: true,
    installation: {
      mode: "pypi",
      update_supported: true,
      command: "pip install -U deeptutor",
      reason: "",
    },
    update: {
      state: "idle",
      message: "",
      previous_version: "1.5.17",
      installed_version: "1.5.17",
      target_version: "",
      restart_required: false,
      lines: [],
    },
    last_update: null,
    ...overrides,
  };
}

test("version comparison stays numeric through the first three segments", () => {
  assert.equal(compareVersionTags("v1.5.18", "1.5.17"), 1);
  assert.equal(compareVersionTags("1.5.17", "v1.5.17"), 0);
  assert.equal(compareVersionTags("v1.5.16", "1.5.17"), -1);
  assert.equal(compareVersionTags("development", "1.5.17"), null);
});

test("the panel reads cached state and only posts an explicit fresh check", async () => {
  const payload = versionPayload();
  const stub = stubFetch(payload);

  try {
    assert.deepEqual(await getVersionStatus(), payload);
    await checkVersionUpdates();
    assert.deepEqual(stub.calls, [
      { url: "/api/v1/settings/version", method: "GET", body: undefined },
      {
        url: "/api/v1/settings/version/check",
        method: "POST",
        body: { force: true },
      },
    ]);
  } finally {
    stub.restore();
  }
});

test("version actions use their dedicated settings and update endpoints", async () => {
  const stub = stubFetch(versionPayload({ check_enabled: false }));

  try {
    await updateVersionCheckSettings(false);
    await startVersionUpdate();
    await getVersionUpdateStatus();
    await cancelVersionUpdate();
    assert.deepEqual(stub.calls, [
      {
        url: "/api/v1/settings/version/settings",
        method: "PUT",
        body: { check_enabled: false },
      },
      { url: "/api/v1/settings/version/update", method: "POST", body: undefined },
      {
        url: "/api/v1/settings/version/update/status",
        method: "GET",
        body: undefined,
      },
      {
        url: "/api/v1/settings/version/update/cancel",
        method: "POST",
        body: undefined,
      },
    ]);
  } finally {
    stub.restore();
  }
});

test("a refused check surfaces a stable message rather than provider text", async () => {
  const stub = stubFetch({ detail: "upstream secret" }, 503);

  try {
    await assert.rejects(
      () => checkVersionUpdates(),
      /Unable to update version status/,
    );
  } finally {
    stub.restore();
  }
});

test("update availability prefers the backend's normalized decision", () => {
  assert.equal(
    isUpdateAvailable(
      {
        tag_name: "v1.5.18",
        name: "",
        published_at: "",
        html_url: "",
        excerpt: "",
        update_available: false,
        migration_bearing: false,
      },
      "1.5.17",
    ),
    false,
  );
});

test("the settings hub mounts the version panel exactly once", () => {
  const hub = readFileSync(SETTINGS_HUB, "utf8");
  const panel = readFileSync(PANEL, "utf8");

  assert.match(hub, /\{catalogEditable === true && <VersionUpdatesPanel \/>\}/);
  assert.match(panel, /getVersionStatus\(\)/);
  assert.match(panel, /checkVersionUpdates\(true\)/);
  assert.match(panel, /updateVersionCheckSettings/);
  assert.match(panel, /startVersionUpdate/);
  assert.match(panel, /cancelVersionUpdate/);
  assert.doesNotMatch(panel, /api\.github\.com/);
});
