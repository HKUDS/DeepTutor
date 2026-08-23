import { expect, test } from "@playwright/test";

const material = {
  material_id: "learning-material",
  filename: "Learning Sample.epub",
  unit: "page",
  unit_count: 3,
  mime: "application/epub+zip",
  title: "Learning Sample",
  byte_size: 1024,
  char_count: 512,
  created_at: 1,
  has_raw_view: false,
  annotation_count: 0,
  outline: [],
  outline_text: "",
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (payload: unknown, status = 200) =>
      route.fulfill({ status, json: payload });

    if (path === "/api/v1/auth/status") {
      return json({
        enabled: true,
        authenticated: true,
        user_id: "u_child",
        username: "child",
        role: "user",
        is_admin: false,
        learning_policy: {
          age_band: "6-8",
          locked_persona: "teacher",
          allowed_capabilities: ["chat", "immersive_reading"],
          default_capability: "immersive_reading",
        },
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
    if (path === "/api/v1/reading/supported-formats") {
      return json({ extensions: [".epub"], max_bytes: 1024, raw_view_extensions: [] });
    }
    if (path === "/api/v1/reading/materials") return json([material]);
    if (path === "/api/v1/reading/materials/learning-material") {
      return json(material);
    }
    if (path === "/api/v1/reading/materials/learning-material/annotations") {
      return json([]);
    }
    if (path === "/api/v1/reading/materials/learning-material/units/1") {
      return json({ locator: 1, unit: "page", text: "Light can behave like a wave." });
    }
    if (path === "/api/v1/reading/materials/learning-material/units/2") {
      return json({ locator: 2, unit: "page", text: "Light can also behave like particles." });
    }
    return json({ detail: "Not found in learning-reader fixture" }, 404);
  });
});

test("learning account opens reading mode and prefills guided actions", async ({ page }) => {
  await page.goto("/home");

  await expect(page.getByRole("button", { name: "Immersive Reading" })).toBeVisible();
  await page.getByRole("button", { name: "Immersive Reading", exact: true }).click();
  await expect(page.getByRole("button", { name: "Research" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Select persona" })).toHaveCount(0);

  await page.getByRole("button", { name: "Immersive Reading", exact: true }).click();

  await page.getByRole("button", { name: "Open a document to read" }).click();
  await page.getByText("Learning Sample.epub").click();

    await expect(page.getByRole("button", { name: "Read aloud" })).toBeVisible();
    await page.getByRole("button", { name: "Read aloud" }).click();
    await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();

    await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.getByRole("button", { name: "Read aloud" })).toBeVisible();
    await expect(page.getByText("Page 2 of 3")).toBeVisible();

    await page.getByRole("button", { name: "Learn" }).click();
    const composer = page.locator("textarea").last();
    await expect.poll(async () => composer.inputValue()).toContain(
    "Using only Page 2 of the currently open reading material, explain it for ages 6-8",
  );

  await page.getByRole("button", { name: "Test" }).click();
  await expect.poll(async () => composer.inputValue()).toContain(
    "Ask only question 1 first",
  );
});
