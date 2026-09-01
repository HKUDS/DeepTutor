import { expect, test } from "@playwright/test";

const MATERIAL_ID = "0123456789abcdef0123456789abcdef";

test("YouTube learning survives reload and switches to Invidious without silent fallback", async ({
  page,
}) => {
  let provider: "youtube" | "invidious" = "youtube";
  let invidiousOffline = false;
  let savedPosition = 0;
  let nativeResolveCount = 0;

  const material = (selected: "youtube" | "invidious") => ({
    version: 1,
    type: "timed_media",
    material_id: MATERIAL_ID,
    source: {
      provider: "youtube",
      video_id: "dQw4w9WgXcQ",
      url: "https://youtu.be/dQw4w9WgXcQ",
      entry_time_seconds: 0,
    },
    metadata: {
      title: "Timestamped lesson",
      author: "Teacher",
      duration_seconds: 120,
    },
    transcript: {
      status: "ready",
      reason: "",
      language: "en",
      source: selected,
      cues: [
        { start: 7, end: 12, text: "The first grounded concept." },
        { start: 70, end: 75, text: "The second grounded concept." },
      ],
    },
    segments: [],
    learning: { last_position: savedPosition },
    playback:
      selected === "youtube"
        ? {
            provider: "youtube",
            kind: "youtube_iframe",
            video_id: "dQw4w9WgXcQ",
            start_seconds: savedPosition,
          }
        : {
            provider: "invidious",
            kind: "html5",
            format_id: "18",
            mime_type: "video/mp4",
            stream_url: `/api/v1/video-learning/materials/${MATERIAL_ID}/stream/18`,
            subtitles_url: `/api/v1/video-learning/materials/${MATERIAL_ID}/subtitles.vtt`,
            start_seconds: savedPosition,
          },
  });

  await page.addInitScript(() => {
    class FakePlayer {
      current = 0;
      duration = 120;
      element: HTMLElement;
      options: Record<string, unknown>;

      constructor(element: HTMLElement, options: Record<string, unknown>) {
        this.element = element;
        this.options = options;
        const iframe = document.createElement("iframe");
        const host = String(options.host || "");
        const videoId = String(options.videoId || "");
        iframe.src = `${host}/embed/${videoId}`;
        iframe.title = "Fake YouTube player";
        element.replaceWith(iframe);
        this.element = iframe;
        const players = ((
          window as typeof window & { __fakePlayers?: FakePlayer[] }
        ).__fakePlayers ||= []);
        players.push(this);
        queueMicrotask(() => {
          const events = options.events as {
            onReady?: (event: { target: FakePlayer }) => void;
          };
          events.onReady?.({ target: this });
        });
      }

      getCurrentTime() {
        return this.current;
      }
      getDuration() {
        return this.duration;
      }
      seekTo(seconds: number) {
        this.current = seconds;
      }
      playVideo() {}
      pauseVideo() {}
      destroy() {
        this.element.remove();
      }
    }

    (window as typeof window & { YT?: unknown }).YT = { Player: FakePlayer };
  });

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (payload: unknown, status = 200) =>
      route.fulfill({ status, json: payload });

    if (path === "/api/v1/auth/status") {
      return json({
        enabled: false,
        authenticated: true,
        role: "admin",
        is_admin: true,
      });
    }
    if (path === "/api/v1/settings/ui") return json({ language: "en" });
    if (path === "/api/v1/settings") return json({ catalog: {} });
    if (path === "/api/v1/settings/llm-options") {
      return json({ active: { profile_id: "p", model_id: "m" }, options: [] });
    }
    if (path === "/api/v1/dashboard/suggestions")
      return json({ suggestions: [], stale: false });
    if (path === "/api/v1/video-learning/materials/resolve") {
      const body = request.postDataJSON() as { provider_override?: "youtube" };
      if (body.provider_override === "youtube") nativeResolveCount += 1;
      return json(material(body.provider_override || provider));
    }
    if (path === `/api/v1/video-learning/materials/${MATERIAL_ID}`) {
      if (provider === "invidious" && invidiousOffline) {
        return json({ detail: "Invidious is offline" }, 400);
      }
      return json(material(provider));
    }
    if (path.endsWith("/progress")) {
      const body = request.postDataJSON() as { time_seconds: number };
      savedPosition = body.time_seconds;
      return json({ time_seconds: savedPosition, duration_seconds: 120 });
    }
    if (path.endsWith("/subtitles.vtt")) {
      return route.fulfill({
        status: 200,
        contentType: "text/vtt",
        body: "WEBVTT\n",
      });
    }
    if (path.includes("/stream/")) {
      return route.fulfill({
        status: 206,
        contentType: "video/mp4",
        body: "not-real-media",
      });
    }
    return json({});
  });

  await page.goto("/home");
  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await page
    .getByRole("button", { name: /Immersive Watching/ })
    .last()
    .click();
  await page
    .getByPlaceholder("https://youtu.be/…")
    .fill("https://youtu.be/dQw4w9WgXcQ?t=7");
  await page.getByRole("button", { name: "Open", exact: true }).click();

  await expect(page.getByText("Timestamped lesson")).toBeVisible();
  await expect(
    page.locator('iframe[title="Fake YouTube player"]'),
  ).toHaveAttribute("src", /youtube-nocookie\.com\/embed\/dQw4w9WgXcQ/);

  await page.evaluate(() => {
    const player = (
      window as typeof window & { __fakePlayers: Array<{ current: number }> }
    ).__fakePlayers.at(-1);
    if (player) player.current = 8;
  });
  await expect(
    page.getByText("The first grounded concept.").locator(".."),
  ).toHaveClass(/ring-1/);
  await page.getByRole("button", { name: "Explain here" }).click();
  await expect(page.locator("textarea")).toHaveValue(
    /\[0:08\] The first grounded concept\./,
  );

  await page.evaluate(() => {
    const link = document.createElement("a");
    link.id = "fake-assistant-timestamp";
    link.href = "#dt-video-time-70";
    link.textContent = "[01:10]";
    document.body.appendChild(link);
  });
  await page.locator("#fake-assistant-timestamp").click();
  await expect
    .poll(() =>
      page.evaluate(() => {
        const player = (
          window as typeof window & {
            __fakePlayers: Array<{ current: number }>;
          }
        ).__fakePlayers.at(-1);
        return player?.current || 0;
      }),
    )
    .toBe(70);

  await page
    .getByRole("button", { name: "Close video learning" })
    .evaluate((button) => {
      document.dispatchEvent(new Event("visibilitychange"));
      button.setAttribute("data-persisted", "true");
    });
  await expect.poll(() => savedPosition).toBeGreaterThanOrEqual(70);
  await page.reload();
  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await page
    .getByRole("button", { name: /Immersive Watching/ })
    .last()
    .click();
  await expect(page.getByText("Timestamped lesson")).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => {
        const player = (
          window as typeof window & {
            __fakePlayers: Array<{ current: number }>;
          }
        ).__fakePlayers.at(-1);
        return player?.current || 0;
      }),
    )
    .toBeGreaterThanOrEqual(70);

  provider = "invidious";
  await page.getByRole("button", { name: "Refresh provider" }).click();
  await expect(page.locator("video")).toBeVisible();
  await expect(page.getByText("Invidious", { exact: true })).toBeVisible();

  const beforeFailure = nativeResolveCount;
  invidiousOffline = true;
  await page.getByRole("button", { name: "Refresh provider" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Invidious is offline" }),
  ).toBeVisible();
  expect(nativeResolveCount).toBe(beforeFailure);

  await page.getByRole("button", { name: "Use native YouTube" }).click();
  await expect(
    page.locator('iframe[title="Fake YouTube player"]'),
  ).toBeVisible();
  expect(nativeResolveCount).toBe(beforeFailure + 1);
});
