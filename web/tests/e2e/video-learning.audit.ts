import { expect, test } from "@playwright/test";

const MATERIAL_ID = "0123456789abcdef0123456789abcdef";

test("YouTube learning survives reload and switches to Invidious without silent fallback", async ({
  page,
}) => {
  let provider: "youtube" | "invidious" = "youtube";
  let invidiousOffline = false;
  let transcriptReady = true;
  let transcriptRefreshCount = 0;
  let savedPosition = 0;
  let nativeResolveCount = 0;
  let nextNoteId = 1;
  const notes: Array<{
    notebook_id: string;
    note_id: string;
    material_id: string;
    body: string;
    time_seconds: number;
    locator: number;
    quote: string;
    created_at: number;
    updated_at: number;
  }> = [];

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
    transcript: transcriptReady
      ? {
          status: "ready",
          reason: "",
          language: "en",
          source: selected,
          cues: [
            { start: 7, end: 12, text: "The first grounded concept." },
            { start: 70, end: 75, text: "The second grounded concept." },
          ],
        }
      : {
          status: "unavailable",
          reason: "temporary Invidious error",
          language: "",
          source: "unavailable",
          cues: [],
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
            stream_url: `/api/video-learning/materials/${MATERIAL_ID}/stream/18`,
            subtitles_url: `/api/video-learning/materials/${MATERIAL_ID}/subtitles.vtt`,
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

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (payload: unknown, status = 200) =>
      route.fulfill({ status, json: payload });

    if (path === "/api/auth/status") {
      return json({
        enabled: false,
        authenticated: true,
        role: "admin",
        is_admin: true,
      });
    }
    if (path === "/api/settings/ui") return json({ language: "en" });
    if (path === "/api/capabilities/registered") {
      return json({
        capabilities: [
          { id: "chat", kind: "turn", available: true },
          { id: "immersive_watching", kind: "turn", available: true },
        ],
      });
    }
    if (path === "/api/settings") return json({ catalog: {} });
    if (path === "/api/settings/llm-options") {
      return json({ active: { profile_id: "p", model_id: "m" }, options: [] });
    }
    if (path === "/api/dashboard/suggestions")
      return json({ suggestions: [], stale: false });
    if (path === "/api/video-learning/materials/resolve") {
      const body = request.postDataJSON() as { provider_override?: "youtube" };
      if (body.provider_override === "youtube") nativeResolveCount += 1;
      return json(material(body.provider_override || provider));
    }
    if (path === `/api/video-learning/materials/${MATERIAL_ID}`) {
      if (provider === "invidious" && invidiousOffline) {
        return json({ detail: "Invidious is offline" }, 400);
      }
      return json(material(provider));
    }
    if (
      path === `/api/video-learning/materials/${MATERIAL_ID}/transcript/refresh`
    ) {
      transcriptRefreshCount += 1;
      transcriptReady = true;
      return json(material("invidious"));
    }
    if (path.endsWith("/progress")) {
      const body = request.postDataJSON() as { time_seconds: number };
      savedPosition = body.time_seconds;
      return json({ time_seconds: savedPosition, duration_seconds: 120 });
    }
    if (path.endsWith("/notes") && request.method() === "GET") {
      return json(notes);
    }
    if (path.endsWith("/notes") && request.method() === "POST") {
      const body = request.postDataJSON() as {
        body: string;
        time_seconds: number;
      };
      const note = {
        notebook_id: "video-notes",
        note_id: `note-${nextNoteId++}`,
        material_id: MATERIAL_ID,
        body: body.body,
        time_seconds: body.time_seconds,
        locator: 1,
        quote: "The first grounded concept.",
        created_at: Date.now() / 1000,
        updated_at: Date.now() / 1000,
      };
      notes.push(note);
      return json(note);
    }
    const noteMatch = /\/materials\/[^/]+\/notes\/([^/]+)$/.exec(path);
    if (noteMatch) {
      const noteId = noteMatch[1];
      const index = notes.findIndex((note) => note.note_id === noteId);
      if (index === -1) return json({ detail: "Note not found" }, 404);
      if (request.method() === "PUT") {
        const body = request.postDataJSON() as { body: string };
        notes[index] = {
          ...notes[index],
          body: body.body,
          updated_at: Date.now() / 1000,
        };
        return json(notes[index]);
      }
      if (request.method() === "DELETE") {
        notes.splice(index, 1);
        return json({ status: "deleted" });
      }
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

  await page.goto("/chat?capability=immersive_watching");
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

  await page.getByRole("tab", { name: "Video notes" }).click();
  await expect(page.getByText("No notes yet.")).toBeVisible();
  await page.getByPlaceholder("Note at 0:08").fill("First timestamped note");
  await page.getByRole("button", { name: "Add video note" }).click();
  await expect(page.getByText("First timestamped note")).toBeVisible();
  await expect(page.getByText("The first grounded concept.")).toBeVisible();

  await page.reload();
  await expect(page.getByText("Timestamped lesson")).toBeVisible();
  await page.getByRole("tab", { name: "Video notes" }).click();
  await expect(page.getByText("First timestamped note")).toBeVisible();

  await page.evaluate(() => {
    const player = (
      window as typeof window & { __fakePlayers: Array<{ current: number }> }
    ).__fakePlayers.at(-1);
    if (player) player.current = 70;
  });
  await page.getByRole("button", { name: "0:08", exact: true }).click();
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
    .toBe(8);

  await page.getByRole("button", { name: "Edit note at 0:08" }).click();
  await page
    .getByLabel("Edit note at 0:08")
    .locator("..")
    .locator("textarea")
    .fill("Updated timestamped note");
  await page.getByRole("button", { name: "Save video note" }).click();
  await expect(page.getByText("Updated timestamped note")).toBeVisible();

  await page.getByRole("button", { name: "Delete note at 0:08" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByText("No notes yet.")).toBeVisible();
  await page.getByRole("tab", { name: "Transcript" }).click();

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
  transcriptReady = false;
  await page.getByRole("button", { name: "Refresh provider" }).click();
  await expect(page.locator("video")).toBeVisible();
  await expect(page.getByText("Invidious", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Retry captions" }),
  ).toBeVisible();
  const player = page.locator("video");
  await player.evaluate((video) =>
    video.setAttribute("data-transcript-retry-probe", "before"),
  );
  await page.getByRole("button", { name: "Retry captions" }).click();
  await expect.poll(() => transcriptRefreshCount).toBe(1);
  await expect(
    page.getByRole("button", { name: "Explain here" }),
  ).toBeVisible();
  await expect(player).toHaveAttribute("data-transcript-retry-probe", "before");

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
