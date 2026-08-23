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
  render_mode: "text",
  content_format: "markdown",
};

const annotation = {
  annotation_id: "annotation-1",
  locator: 1,
  kind: "highlight",
  color: "yellow",
  quote: "behave like a wave",
  note: "Wave behavior",
  rects: [],
  source_anchor: "",
  selectors: [
    { type: "TextPositionSelector", start: 10, end: 28 },
    { type: "TextQuoteSelector", exact: "behave like a wave" },
  ],
  author: "user",
  created_at: 1,
  updated_at: 1,
};

test.beforeEach(async ({ page }, testInfo) => {
  const includeAnnotation = testInfo.title.includes("rich text annotation");
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
      return json(includeAnnotation ? [annotation] : []);
    }
    if (path === "/api/v1/reading/materials/learning-material/units/1") {
      return json({ locator: 1, unit: "page", text: "Light can behave like a wave." });
    }
    if (path === "/api/v1/reading/materials/learning-material/units/2") {
      return json({ locator: 2, unit: "page", text: "Light can also behave like particles." });
    }
    if (path === "/api/v1/reading/extensions") {
      return json([
        { id: "read_aloud", version: "1", name: "Read aloud", protocol_version: "1", result_types: ["browser_speech"], actions: [{ id: "read", label: "Read aloud", trigger: "toolbar", requires: ["visible_text"] }] },
        { id: "guided_learn", version: "1", name: "Learn", protocol_version: "1", result_types: ["card"], actions: [{ id: "explain", label: "Learn", trigger: "toolbar", requires: ["visible_text"] }] },
        { id: "quiz", version: "1", name: "Test", protocol_version: "1", result_types: ["quiz"], actions: [{ id: "start", label: "Test", trigger: "toolbar", requires: ["visible_text"] }] },
      ]);
    }
    if (path.endsWith("/extensions/read_aloud/actions/read")) {
      return json({ type: "browser_speech", interaction_id: "", title: "Read aloud", message: "", payload: { text: "Light can behave like a wave.", locale: "en" } });
    }
    if (path.endsWith("/extensions/guided_learn/actions/explain")) {
      return json({ type: "card", interaction_id: "", title: "Guided learning", message: "", payload: { overview: "Light has wave and particle behavior.", concepts: ["Wave behavior", "Particle behavior"], reflection: "What evidence supports both?" } });
    }
    if (path.endsWith("/extensions/quiz/actions/start")) {
      return json({ type: "quiz", interaction_id: "quiz-1", title: "Three-question check", message: "", payload: { questions: [{ id: "q1", prompt: "Which statement appears?", choices: ["Wave behavior", "Sound only"] }, { id: "q2", prompt: "Which statement appears?", choices: ["Particle behavior", "Neither"] }, { id: "q3", prompt: "Which statement appears?", choices: ["Light", "Darkness only"] }] } });
    }
    return json({ detail: "Not found in learning-reader fixture" }, 404);
  });
});

test("learning account uses schema-driven reading actions", async ({ page, context }, testInfo) => {
  // Auth-enabled production builds gate /home in middleware before browser
  // route fixtures can answer /api/v1/auth/status. The middleware only checks
  // JWT shape and expiry; backend authorization remains mocked below.
  await context.addCookies([{
    name: "dt_token",
    value: "e30.eyJleHAiOjQxMDI0NDQ4MDB9.fixture",
    url: String(testInfo.project.use.baseURL || "http://localhost:3782"),
  }]);
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

    await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.getByRole("button", { name: "Read aloud" })).toBeVisible();
    await expect(page.getByText("Page 2 of 3")).toBeVisible();

    await page.getByRole("button", { name: "Learn" }).click();
    await expect(page.getByText("Light has wave and particle behavior.")).toBeVisible();

    await page.getByRole("button", { name: "Test" }).click();
    await expect(page.getByText("Three-question check")).toBeVisible();
    await expect(page.getByText("Which statement appears?").first()).toBeVisible();
});

test("clicking a rich text annotation activates its sidebar entry", async ({ page, context }, testInfo) => {
  await context.addCookies([{
    name: "dt_token",
    value: "e30.eyJleHAiOjQxMDI0NDQ4MDB9.fixture",
    url: String(testInfo.project.use.baseURL || "http://localhost:3782"),
  }]);
  await page.goto("/home");

  await page.getByRole("button", { name: "Immersive Reading", exact: true }).click();
  await page.getByRole("button", { name: "Open a document to read" }).click();
  await page.getByText("Learning Sample.epub").click();

  const highlight = page.locator(".r6o-annotation").first();
  await expect(highlight).toBeVisible();
  const activeEntry = page.getByRole("button").filter({ hasText: "Wave behavior" });
  await expect(activeEntry).not.toHaveClass(/border-\[var\(--ring\)\]/);
  await highlight.click();
  await expect(activeEntry).toHaveClass(/border-\[var\(--ring\)\]/);
});
