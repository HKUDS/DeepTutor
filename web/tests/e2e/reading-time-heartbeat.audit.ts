import { expect, test } from "@playwright/test";
import { emptyTaskBoard } from "./fixtures/task-board";

/**
 * Effective reading-time heartbeats in the real Reader (#1988).
 *
 * The clock is Playwright's fake clock, so the acceptance timeline — two
 * active minutes, a 90 s idle gap and 30 s hidden — runs in seconds of wall
 * time. Every reading-time POST the page emits (fetch beats and the
 * pagehide/visibility beacon) is captured by the route mock; the credited
 * total must land within one heartbeat interval of the two active minutes.
 * Server-side clamping and multi-tab dedup are contract-tested in
 * tests/reading/test_reading_time.py; this audit proves the mounted Reader
 * only claims time while it is genuinely used.
 */

const MATERIAL = "dddddddddddddddd";
const SESSION = "reading-time-heartbeat";
const WORKSPACE_ID = "reading-time-workspace";

// Acceptance: two active minutes ± one 30 s heartbeat.
const ACTIVE_SECONDS = 120;
const BEAT_INTERVAL_SECONDS = 30;

interface Beat {
  seconds: number;
  method: string;
  at: number;
}

function material() {
  return {
    material_id: MATERIAL,
    filename: "Heartbeat material.md",
    unit: "section",
    unit_count: 2,
    mime: "text/markdown",
    title: "Heartbeat material",
    byte_size: 256,
    char_count: 128,
    created_at: 1,
    has_raw_view: false,
    render_mode: "text",
    annotation_count: 0,
    outline: [
      { title: "First", locator: 1, level: 1 },
      { title: "Second", locator: 2, level: 1 },
    ],
    outline_text: "",
    unit_refs: [],
  };
}

function libraryMaterial() {
  return {
    material_id: MATERIAL,
    content_id: MATERIAL,
    filename: "Heartbeat material.md",
    title: "Heartbeat material",
    source_kind: "file",
    source_url: "",
    mime: "text/markdown",
    render_mode: "text",
    cover_url: "",
    duration_seconds: 0,
    status: "ready",
    progress: 0,
    error_code: "",
    error_detail: "",
    created_at: 1,
    updated_at: 2,
    last_opened_at: 2,
    size_bytes: 256,
    unit_count: 2,
    collections: [],
  };
}

function workspace() {
  return {
    workspace_id: WORKSPACE_ID,
    title: "Reading time regression",
    description: "",
    active_material_id: MATERIAL,
    created_at: 1,
    updated_at: 2,
    tabs: [
      {
        material: libraryMaterial(),
        tab_order: 0,
        pinned: false,
        opened: true,
        added_at: 1,
      },
    ],
  };
}

function session() {
  return {
    id: SESSION,
    session_id: SESSION,
    title: "Reading time regression",
    created_at: 1,
    updated_at: 2,
    status: "idle",
    preferences: { capability: "immersive_reading" },
    active_turns: [],
    messages: [],
  };
}

test.use({ video: "on" });

test.beforeEach(async ({ page }) => {
  const beats: Beat[] = [];
  (page as unknown as { _beats: Beat[] })._beats = beats;
  await page.clock.install();
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (payload: unknown, status = 200) =>
      route.fulfill({ status, json: payload });

    if (path.endsWith("/reading-time") && request.method() === "POST") {
      const body = JSON.parse(request.postData() || "{}") as {
        active_seconds?: number;
      };
      beats.push({
        seconds: Number(body.active_seconds || 0),
        method: request.method(),
        at: Date.now(),
      });
      return json({
        day: "2026-10-21",
        material_id: MATERIAL,
        active_seconds: body.active_seconds || 0,
        credited_seconds: Math.min(body.active_seconds || 0, 120),
      });
    }
    if (path === "/api/partners" || path === "/api/partner-groups") return json([]);
    if (path === "/api/task-board") return json(emptyTaskBoard);
    if (path === "/api/auth/status") {
      return json({ enabled: false, authenticated: true });
    }
    if (path === "/api/settings/ui") return json({ language: "en" });
    if (path === "/api/dashboard/suggestions") {
      return json({ suggestions: [], stale: false });
    }
    if (path === "/api/settings/llm-options") {
      return json({
        active: { profile_id: "p", model_id: "m" },
        options: [
          {
            profile_id: "p",
            model_id: "m",
            profile_name: "Profile",
            model_name: "Model",
            model: "model",
            provider: "provider",
            is_active_default: true,
          },
        ],
      });
    }
    if (path === `/api/sessions/${SESSION}`) return json(session());
    if (path === "/api/sessions") return json({ sessions: [] });
    if (path === "/api/reading/supported-formats") {
      return json({
        extensions: [".md"],
        max_bytes: 1024,
        raw_view_extensions: [],
      });
    }
    if (path === "/api/reading/extensions") return json([]);
    if (path === `/api/reading/workspaces/${WORKSPACE_ID}`) {
      return json({ workspace: workspace(), sessions: [] });
    }
    if (path === `/api/reading/workspaces/${WORKSPACE_ID}/sessions`) {
      return json({ sessions: [] });
    }
    if (path === "/api/reading/materials") return json([material()]);
    if (path === `/api/reading/materials/${MATERIAL}`) return json(material());
    if (path.endsWith("/annotations")) return json([]);
    if (path.endsWith("/position") || path.endsWith("/activities")) return json({});
    const unit = /\/api\/reading\/materials\/([^/]+)\/units\/(\d+)/.exec(path);
    if (unit) {
      return json({
        locator: Number(unit[2]),
        unit: "section",
        text: `# Section ${unit[2]}\n\nHeartbeat material section ${unit[2]} text.`,
      });
    }
    return json({});
  });
});

async function setHidden(page: import("@playwright/test").Page, hidden: boolean) {
  await page.evaluate((next) => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => (next ? "hidden" : "visible"),
    });
    document.dispatchEvent(new Event("visibilitychange"));
  }, hidden);
}

test("heartbeats credit two active minutes and drop idle and hidden time", async ({
  page,
}) => {
  test.setTimeout(240_000);
  const beats = (page as unknown as { _beats: Beat[] })._beats;

  await page.goto(`/learning/reading/${WORKSPACE_ID}/sessions/${SESSION}`, {
    waitUntil: "domcontentloaded",
  });
  await expect(page.getByText("Heartbeat material section 1 text.")).toBeVisible();

  // Two active minutes: an interaction every 10 s keeps the clock running.
  // runFor (not fastForward) — fastForward fires each timer at most once, so
  // the 1 s tick must be advanced one second at a time.
  for (let step = 0; step < ACTIVE_SECONDS; step += 1) {
    if (step % 10 === 0) {
      await page.mouse.move(300 + step, 300);
      await page.mouse.down();
      await page.mouse.up();
    }
    await page.clock.runFor(1_000);
  }

  // A 90 s idle gap: at most one grace window can still be credited.
  await page.clock.runFor(90_000);

  // 30 s hidden: the clock stops and a beacon beat flushes what is pending.
  await setHidden(page, true);
  await page.clock.runFor(30_000);
  await setHidden(page, false);

  const claimed = beats.reduce((sum, beat) => sum + beat.seconds, 0);
  // Evidence trail: every captured beat, for the run report.
  console.log(
    "reading-time beats:",
    JSON.stringify(beats.map((beat) => beat.seconds)),
    "total:",
    claimed,
  );
  expect(
    beats.length,
    "heartbeats must have been sent while reading",
  ).toBeGreaterThan(0);
  expect(claimed).toBeGreaterThanOrEqual(ACTIVE_SECONDS - BEAT_INTERVAL_SECONDS);
  expect(claimed).toBeLessThanOrEqual(ACTIVE_SECONDS + BEAT_INTERVAL_SECONDS);
});
