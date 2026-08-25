import { expect, test, type BrowserContext, type Page, type TestInfo } from "@playwright/test";

import type { TimedMediaMaterial, VideoLearningMark } from "../../lib/video-learning-api";

const material: TimedMediaMaterial = {
  version: 1,
  type: "timed_media",
  material_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  source: {
    provider: "youtube",
    video_id: "dQw4w9WgXcQ",
    url: "https://youtu.be/dQw4w9WgXcQ",
    entry_time_seconds: 0,
    duration_seconds: 120,
  },
  metadata: { title: "Gradient descent", author: "Tutor", duration_seconds: 120, chapters: [] },
  transcript: {
    language: "en",
    source: "invidious",
    cues: [
      { start: 10, end: 18, text: "Gradient descent finds a local minimum." },
      { start: 18, end: 30, text: "Why does the learning rate matter?" },
    ],
  },
  segments: [
    {
      locator: 1,
      start: 10,
      end: 30,
      text: "Gradient descent finds a local minimum. Why does the learning rate matter?",
    },
  ],
  playback: { formats: {}, official_url: "https://youtu.be/dQw4w9WgXcQ" },
  learning: { last_position: 0, notes: [], marks: [] },
};

async function mockWatchingApis(page: Page, marks: VideoLearningMark[], options: { failCreate?: boolean } = {}) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (payload: unknown, status = 200) => route.fulfill({ status, json: payload });

    if (path === "/api/v1/auth/status") {
      return json({
        enabled: true,
        authenticated: true,
        user_id: "u_admin",
        username: "admin",
        role: "admin",
        is_admin: true,
      });
    }
    if (path === "/api/v1/settings/ui") return json({ language: "en" });
    if (path === "/api/v1/tools") return json({ enabled_optional_tools: [] });
    if (path === "/api/v1/settings/llm-options") {
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
    if (path === "/api/v1/knowledge/list") return json([]);
    if (path === "/api/v1/subagents/settings") return json({});
    if (path === "/api/v1/sessions") return json([]);
    if (path === "/api/v1/video-learning/invidious/status") {
      return json({
        configured: true,
        connected: false,
        invidious_base_url: "http://127.0.0.1:3000",
        invidious_public_base_url: "http://127.0.0.1:3000",
        user_preferences: null,
      });
    }
    if (path === "/api/v1/video-learning/invidious/home") {
      return json({
        connected: false,
        default_home: "Popular",
        current_tab: "Popular",
        tabs: ["Popular"],
        items: [],
        invidious_public_base_url: "http://127.0.0.1:3000",
      });
    }
    if (path === "/api/v1/video-learning/resolve" && request.method() === "POST") {
      return json({ ...material, learning: { ...material.learning, marks: [...marks] } });
    }
    if (path === `/api/v1/video-learning/materials/${material.material_id}` && request.method() === "GET") {
      return json({ ...material, learning: { ...material.learning, marks: [...marks] } });
    }
    if (path === `/api/v1/video-learning/materials/${material.material_id}/marks` && request.method() === "POST") {
      if (options.failCreate) {
        return json({ detail: "Mark kind must be key_point, question, or review." }, 400);
      }
      const body = request.postDataJSON() as Partial<VideoLearningMark>;
      if (!body?.kind || !["key_point", "question", "review"].includes(String(body.kind))) {
        return json({ detail: "Mark kind must be key_point, question, or review." }, 400);
      }
      const saved: VideoLearningMark = {
        mark_id: `mark-${marks.length + 1}`,
        kind: body.kind as VideoLearningMark["kind"],
        start_seconds: Number(body.start_seconds || 0),
        end_seconds: Number(body.end_seconds || 0),
        start_locator: Number(body.start_locator || 1),
        end_locator: Number(body.end_locator || 1),
        quote: String(body.quote || ""),
        note: String(body.note || ""),
        author: (body.author as VideoLearningMark["author"]) || "user",
        created_at: "2026-08-24T00:00:00Z",
        updated_at: "2026-08-24T00:00:00Z",
      };
      marks.push(saved);
      return json(saved, 201);
    }
    if (path.includes("/mark-suggestions") && request.method() === "POST") {
      return json({
        suggestions: [
          {
            kind: "key_point",
            start_seconds: 10,
            end_seconds: 18,
            start_locator: 1,
            end_locator: 1,
            quote: "Gradient descent finds a local minimum.",
            note: "",
            author: "assistant",
          },
        ],
      });
    }
    if (path.endsWith("/watch-progress") || path.endsWith("/position") || path.endsWith("/notes")) {
      return json({ ok: true, time_seconds: 0, cumulative_played_seconds: 0, synced_to_invidious: false });
    }
    return json({ detail: "unmocked" }, 404);
  });
}

async function openWatching(page: Page, context: BrowserContext, testInfo: TestInfo, marks: VideoLearningMark[], options: { failCreate?: boolean } = {}) {
  await context.addCookies([
    {
      name: "dt_token",
      value: "e30.eyJleHAiOjQxMDI0NDQ4MDB9.fixture",
      url: String(testInfo.project.use.baseURL || "http://localhost:3782"),
    },
  ]);
  await mockWatchingApis(page, marks, options);
  await page.goto("/home");
  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await page.getByRole("button", { name: /Immersive Watching/ }).click();
  await page.getByPlaceholder("Paste a YouTube or Invidious video URL...").fill("https://youtu.be/dQw4w9WgXcQ");
  await page.getByRole("button", { name: "Start Learning" }).click();
  await expect(page.getByRole("heading", { name: "Gradient descent" })).toBeVisible();
}

test("desktop: select subtitles, save a key point, and replay from the list", async ({ page, context }, testInfo) => {
  const marks: VideoLearningMark[] = [];
  await openWatching(page, context, testInfo, marks);
  const cue = page.getByTestId("watching-cue-text").first();
  await expect(cue).toBeVisible();
  await cue.click({ clickCount: 3 });
  await page.getByTestId("watching-mark-key_point").click();
  await page.getByTestId("watching-tab-marks").click();
  await expect(page.getByText("Gradient descent finds a local minimum.")).toBeVisible();
  await page.getByRole("button", { name: /00:10/ }).click();
});

test("touch fallback creates a current-time bookmark", async ({ page, context }, testInfo) => {
  const marks: VideoLearningMark[] = [];
  await openWatching(page, context, testInfo, marks);
  await page.getByRole("button", { name: "Mark here" }).click();
  await page.getByRole("button", { name: "Review later" }).click();
  await expect(page.getByText("Review later")).toBeVisible();
});

test("extracting key points shows unsaved suggestions", async ({ page, context }, testInfo) => {
  const marks: VideoLearningMark[] = [];
  await openWatching(page, context, testInfo, marks);
  await page.getByRole("button", { name: "Extract key points" }).click();
  await expect(page.getByText("Suggested marks")).toBeVisible();
  await page.locator("section").getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("button", { name: "Key points", exact: true })).toHaveClass(/font-semibold/);
  await expect(page.getByText("Gradient descent finds a local minimum.")).toBeVisible();
});

test("save failure keeps the transcript usable", async ({ page, context }, testInfo) => {
  const marks: VideoLearningMark[] = [];
  await openWatching(page, context, testInfo, marks, { failCreate: true });
  await page.getByRole("button", { name: "Mark here" }).click();
  await page.getByTestId("watching-mark-key_point").click();
  await expect(page.getByText("Mark kind must be key_point, question, or review.")).toBeVisible();
  await expect(page.getByText("Gradient descent finds a local minimum.")).toBeVisible();
});

for (const viewport of [
  { name: "iPad landscape", width: 1180, height: 820 },
  { name: "iPad portrait", width: 820, height: 1180 },
]) {
  test.describe(viewport.name, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height }, hasTouch: true, isMobile: true });
    test("shows transcript selection and key-point tab", async ({ page, context }, testInfo) => {
      const marks: VideoLearningMark[] = [];
      await openWatching(page, context, testInfo, marks);
      await expect(page.getByRole("button", { name: "Mark here" })).toBeVisible();
      await page.getByTestId("watching-tab-marks").click();
      await expect(page.getByText("No key points yet.")).toBeVisible();
      await page.getByTestId("watching-tab-transcript").click();
      await page.getByRole("button", { name: "Mark here" }).click();
      await page.getByTestId("watching-mark-question").click();
      await expect(page.getByTestId("watching-tab-marks")).toHaveClass(/font-semibold/);
      await expect(page.getByTestId("watching-mark-card-question")).toBeVisible();
    });
  });
}

