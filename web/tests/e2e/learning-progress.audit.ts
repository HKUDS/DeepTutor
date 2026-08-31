import { expect, test } from "@playwright/test";

test("learning progress uses the account reading records contract", async ({
  page,
}, testInfo) => {
  const requestedPaths: string[] = [];

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    requestedPaths.push(path);
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
    if (path === "/api/v1/settings") {
      return json({
        ui: { theme: "system", language: "en", response_language: "en" },
        catalog: {
          version: 1,
          connections: [],
          services: {
            llm: { active_profile_id: null, active_model_id: null, profiles: [] },
            task: { active_profile_id: null, active_model_id: null, profiles: [] },
            embedding: {
              active_profile_id: null,
              active_model_id: null,
              profiles: [],
            },
            search: { active_profile_id: null, profiles: [] },
            tts: { active_profile_id: null, active_model_id: null, profiles: [] },
            stt: { active_profile_id: null, active_model_id: null, profiles: [] },
            imagegen: {
              active_profile_id: null,
              active_model_id: null,
              profiles: [],
            },
            videogen: {
              active_profile_id: null,
              active_model_id: null,
              profiles: [],
            },
          },
        },
      });
    }
    if (path === "/api/v1/learning/reading/records") {
      return json({
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
      });
    }
    return json({});
  });

  await page.goto("/settings/progress", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "Learning progress" })).toBeVisible();
  await expect(page.getByText("rm_lesson").first()).toBeVisible();
  await expect(page.getByRole("progressbar").first()).toHaveAttribute(
    "aria-valuenow",
    "50",
  );
  await expect(page.getByText(/guide · guided_learning · Locator 4/)).toBeVisible();

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.screenshot({
    path: testInfo.outputPath("desktop.png"),
    fullPage: true,
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    )
    .toBeLessThanOrEqual(1);
  await page.screenshot({
    path: testInfo.outputPath("mobile.png"),
    fullPage: true,
  });

  expect(requestedPaths).toContain("/api/v1/learning/reading/records");
  expect(requestedPaths).not.toContain("/api/v1/learning/records");
});
