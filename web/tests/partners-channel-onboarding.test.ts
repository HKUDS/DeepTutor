import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

import {
  applyChannelOnboarding,
  cancelChannelOnboarding,
  getChannelOnboarding,
  getPartnerChannelRuntime,
  startChannelOnboarding,
  supportsChannelOnboarding,
} from "../lib/partners-api";

const onboardingPanelSource = readFileSync(
  path.resolve(process.cwd(), "components/partners/ChannelOnboardingPanel.tsx"),
  "utf8",
);
const runtimeStatusSource = readFileSync(
  path.resolve(process.cwd(), "components/partners/ChannelRuntimeStatus.tsx"),
  "utf8",
);

type Captured = { method: string; url: string; body?: unknown };

function stubFetch(body: unknown): {
  calls: Captured[];
  restore: () => void;
} {
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

test("QR onboarding is exposed only for available Feishu and WeCom", () => {
  assert.equal(supportsChannelOnboarding("feishu", true), true);
  assert.equal(supportsChannelOnboarding("wecom", undefined), true);
  assert.equal(supportsChannelOnboarding("feishu", false), false);
  assert.equal(supportsChannelOnboarding("telegram", true), false);
});

test("QR action controls are rendered with a non-null onboarding session", () => {
  assert.match(onboardingPanelSource, /\{session && active \? \(/);
});

test("channel runtime setup output is rendered in the WebUI", () => {
  assert.match(runtimeStatusSource, /setup\.qr_data_url/);
  assert.match(runtimeStatusSource, /setup\.message/);
  assert.match(runtimeStatusSource, /getPartnerChannelRuntime/);
  assert.match(runtimeStatusSource, /Listener running/);
  assert.match(runtimeStatusSource, /Configuration required/);
  assert.match(runtimeStatusSource, /if \(!enabled\)/);
});

test("onboarding client sends the partner-scoped lifecycle requests", async () => {
  const session = {
    session_id: "session id",
    partner_id: "partner id",
    channel: "feishu",
    status: "ready",
    qr_payload: "https://example",
    qr_data_url: null,
    fallback_url: "https://example",
    poll_interval_seconds: 5,
    expires_at: "2026-08-22T00:00:00Z",
  };
  const stub = stubFetch(session);
  try {
    await startChannelOnboarding("partner id", "feishu");
    await getChannelOnboarding("partner id", "session id");
    await cancelChannelOnboarding("partner id", "session id");
    await applyChannelOnboarding("partner id", "session id");

    assert.deepEqual(stub.calls[0], {
      method: "POST",
      url: "/api/partners/partner%20id/channel-onboarding/start",
      body: { channel: "feishu" },
    });
    assert.equal(
      stub.calls[1].url,
      "/api/partners/partner%20id/channel-onboarding/session%20id",
    );
    assert.equal(stub.calls[2].method, "DELETE");
    assert.equal(stub.calls[3].method, "POST");
    assert.match(stub.calls[3].url, /\/apply$/);
  } finally {
    stub.restore();
  }
});

test("channel runtime client reads the partner-scoped status endpoint", async () => {
  const stub = stubFetch({ partner_id: "p", running: true, channels: {} });
  try {
    await getPartnerChannelRuntime("partner id");
    assert.deepEqual(stub.calls, [
      {
        method: "GET",
        url: "/api/partners/partner%20id/channels/status",
        body: undefined,
      },
    ]);
  } finally {
    stub.restore();
  }
});
