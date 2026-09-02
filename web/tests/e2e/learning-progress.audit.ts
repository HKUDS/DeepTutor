import { expect, test } from "@playwright/test";

type RecordsMode = "delayed" | "populated" | "empty" | "error";

const populatedRecords = {
  progress: [
    {
      material_id: "rm_lesson",
      latest_locator: 3,
      latest_percentage: 0.3,
      furthest_locator: 5,
      furthest_percentage: 0.5,
      updated_at: 1,
    },
  ],
  activities: [
    {
      activity_id: "racc_lesson",
      material_id: "rm_lesson",
      extension_id: "guided_learning",
      action: "guide",
      locator: 4,
      result_type: "card",
      created_at: 2,
    },
  ],
};

for (const scenario of ["delayed", "populated", "empty", "error"] as const) {
  test(`learning progress covers the ${scenario} state`, async ({ page }) => {
    const mode: RecordsMode = scenario;
    const requestedPaths: string[] = [];

    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      requestedPaths.push(path);
      const json = (payload: unknown, status = 200) => route.fulfill({ status, json: payload });

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
        return json({ capabilities: [] });
      }
      if (path === "/api/settings") {
        return json({
          ui: {
            theme: "snow",
            language: "en",
            response_language: "en",
            code_block_theme: "oneDark",
            code_block_show_line_numbers: false,
            code_block_wrap_long_lines: false,
          },
        });
      }
      if (path === "/api/settings/document-parsing") {
        return json({
          engine: "text_only",
          engines: {},
          available_engines: [],
          readiness: {},
          installable: [],
          mineru: { api_token_set: false },
        });
      }
      if (path === "/api/settings/video-learning") {
        return json({
          version: 1,
          default_provider: "youtube",
          youtube: { transcript_provider: "youtube_transcript_api" },
          invidious: { api_base_url: "", public_base_url: "" },
        });
      }
      if (path === "/api/settings/chat-starters") {
        return json({
          settings: { trace_count: 3 },
          bounds: { trace_count: [1, 10] },
        });
      }
      if (path === "/api/system/status") {
        return json({
          backend: { status: "online", timestamp: "2026-01-01T00:00:00Z" },
          llm: { status: "online" },
          embeddings: { status: "online" },
          search: { status: "online" },
        });
      }
      if (path === "/api/memory/settings") {
        return json({
          update: { l2_budget: 24, l3_budget: 12 },
          audit: { l2_budget: 24, l3_budget: 12 },
          dedup: { iterations: 1, auto_after_update: false },
          merge: {
            auto_after_update: false,
            auto_after_audit: false,
            auto_after_dedup: false,
          },
          chunking: {
            overlap_ratio: 0.15,
            boundary: "paragraph",
            min_chunk_chars: 200,
            max_chunk_chars: 1200,
          },
          reference: { enforce_required: true, drop_invalid_refs: false },
        });
      }
      if (path === "/api/system/update") {
        return json({
          current_version: "1.0.0",
          check_enabled: false,
          checked_at: "2026-01-01T00:00:00Z",
          cached: true,
          check_error: "",
          update_available: false,
          release: null,
          installation: {
            mode: "source",
            automatic_update: false,
            command: "",
            reason: "Local test fixture",
          },
          launcher_managed: false,
          is_admin: true,
          job: null,
        });
      }
      if (path !== "/api/mastery-paths/reading/records") return json({});

      if (mode === "error") {
        return json({ detail: "Records unavailable" }, 500);
      }
      if (mode === "empty") return json({ progress: [], activities: [] });
      if (mode === "delayed") {
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
      return json(populatedRecords);
    });

    await page.goto("/settings#learning-progress", {
      waitUntil: "domcontentloaded",
    });

    await expect(page.getByRole("heading", { name: "Learning progress" })).toBeVisible();

    if (mode === "error") {
      await expect(page.getByText("Unable to load learning progress")).toBeVisible();
      return;
    }

    if (mode === "empty") {
      await expect(page.getByText("No learning activity yet")).toBeVisible();
      return;
    }

    if (mode === "delayed") {
      await expect(page.getByText("Loading progress")).toBeVisible();
    }

    await expect(page.getByText("rm_lesson").first()).toBeVisible();
    await expect(page.getByRole("progressbar").first()).toHaveAttribute("aria-valuenow", "50");
    await expect(page.getByText(/guide - guided_learning - Locator 4/)).toBeVisible();

    if (mode !== "populated") return;
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.screenshot({
      path: test.info().outputPath("desktop.png"),
      fullPage: true,
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth
        )
      )
      .toBeLessThanOrEqual(1);
    await page.screenshot({
      path: test.info().outputPath("mobile.png"),
      fullPage: true,
    });

    expect(requestedPaths).toContain("/api/mastery-paths/reading/records");
    expect(requestedPaths).not.toContain("/api/v1/learning/reading/records");
  });
}
