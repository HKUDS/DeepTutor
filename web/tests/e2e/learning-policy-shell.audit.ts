import { expect, test } from "@playwright/test";

test("learning policy redacts denied surfaces without losing chat history", async ({
  page,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem("deeptutor-language", "en");
  });

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (payload: unknown, status = 200) =>
      route.fulfill({ status, json: payload });

    if (path === "/api/auth/status") {
      return json({
        enabled: true,
        authenticated: true,
        user_id: "learner-1",
        username: "learner",
        role: "user",
        is_admin: false,
        preset: "standard",
        learning_policy: {
          age_band: "13-15",
          locked_persona: "teacher",
          allowed_capabilities: ["chat", "immersive_reading"],
          default_capability: "immersive_reading",
          allowed_surfaces: ["chat", "reading"],
          reading: {
            allow_upload: false,
            material_ids: [],
            extensions: [],
          },
        },
      });
    }
    if (path === "/api/settings") {
      return json(
        { detail: "This learning account cannot use the requested server surface." },
        403,
      );
    }
    if (path === "/api/settings/ui") {
      return json({
        theme: "snow",
        language: "en",
        response_language: "en",
      });
    }
    if (path.startsWith("/api/settings/llm-options")) {
      return json({
        active: { profile_id: "granted", model_id: "learner-model" },
        options: [
          {
            profile_id: "granted",
            model_id: "learner-model",
            profile_name: "Granted provider",
            model_name: "Learner model",
            label: "Learner model",
            model: "learner-model",
            provider: "openai",
            is_active_default: true,
          },
        ],
      });
    }
    if (path.startsWith("/api/auth/profile/learner-profile")) {
      return json({ learner_profile: null });
    }
    if (path.startsWith("/api/system/status")) {
      return json(
        { detail: "This learning account cannot use the requested server surface." },
        403,
      );
    }
    if (path.startsWith("/api/sessions")) {
      return json({
        sessions: [
          {
            session_id: "allowed-session",
            title: "Allowed chat history",
            created_at: 1,
            updated_at: 2,
            status: "idle",
            preferences: { capability: "chat" },
            active_turns: [],
          },
        ],
      });
    }
    if (
      path.startsWith("/api/courses") ||
      path.startsWith("/api/mastery-paths/topics/index") ||
      path.startsWith("/api/reading/workspaces/index")
    ) {
      return json({ detail: "Denied optional label" }, 403);
    }
    return json(
      { detail: "This learning account cannot use the requested server surface." },
      403,
    );
  });

  await page.goto("/settings", { waitUntil: "domcontentloaded" });

  await expect(page.locator('a[href="/chat"]').first()).toBeVisible();
  await expect(page.locator('a[href="/reading"]').first()).toBeVisible();
  await expect(page.locator('a[href="/settings"]').first()).toBeVisible();
  await expect(page.getByText("Allowed chat history")).toBeVisible();

  for (const href of [
    "/partners",
    "/agents",
    "/co-writer",
    "/books",
    "/mastery",
    "/space",
    "/memory",
    "/knowledge-bases",
  ]) {
    await expect(page.locator(`a[href="${href}"]`)).toHaveCount(0);
  }

  await expect(page.getByRole("link", { name: "Appearance" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Learner profile" })).toBeVisible();
  await page.getByRole("link", { name: "Learner profile" }).click();
  await expect(page.getByRole("heading", { name: "Assigned models" })).toBeVisible();
  await expect(page.getByText("Learner model")).toBeVisible();
  await expect(page.getByText("Active model")).toBeVisible();
  await expect(page.getByRole("link", { name: "About" })).toBeVisible();
  for (const label of ["Network", "Models", "Knowledge Base", "Chat", "Memory", "Guardian"]) {
    await expect(page.getByRole("link", { name: label, exact: true })).toHaveCount(0);
  }
  await expect(page.getByText(/Settings fetch failed/)).toHaveCount(0);

  const desktopLayout = await page.evaluate(() => ({
    viewport: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
  }));
  expect(desktopLayout.documentWidth).toBeLessThanOrEqual(
    desktopLayout.viewport + 1,
  );

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByText("Allowed chat history")).toBeVisible();
  await expect(page.locator('a[href="/knowledge-bases"]')).toHaveCount(0);

  const mobileLayout = await page.evaluate(() => ({
    viewport: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
  }));
  expect(mobileLayout.documentWidth).toBeLessThanOrEqual(
    mobileLayout.viewport + 1,
  );
});
