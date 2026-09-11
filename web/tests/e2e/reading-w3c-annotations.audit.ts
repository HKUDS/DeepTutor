import { expect, test } from "@playwright/test";

const WORKSPACE_ID = "w3c-workspace";

const material = {
  material_id: "w3c-material",
  filename: "W3C Annotation Sample.txt",
  unit: "section",
  unit_count: 1,
  mime: "text/plain",
  title: "W3C Annotation Sample",
  byte_size: 256,
  char_count: 128,
  created_at: 1,
  has_raw_view: false,
  annotation_count: 1,
  outline: [],
  outline_text: "",
};

const libraryMaterial = {
  material_id: material.material_id,
  content_id: material.material_id,
  filename: material.filename,
  title: material.title,
  source_kind: "file",
  source_url: "",
  mime: material.mime,
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
  size_bytes: material.byte_size,
  unit_count: material.unit_count,
  collections: [],
};

const workspace = {
  workspace_id: WORKSPACE_ID,
  title: "W3C annotation regression",
  description: "",
  active_material_id: material.material_id,
  created_at: 1,
  updated_at: 2,
  tabs: [
    {
      material: libraryMaterial,
      tab_order: 0,
      pinned: false,
      opened: true,
      added_at: 1,
    },
  ],
};

const annotation = {
  annotation_id: "annotation-1",
  locator: 1,
  kind: "highlight",
  color: "yellow",
  quote: "behave like a wave",
  note: "Wave behavior",
  rects: [],
  selectors: [
    { type: "TextPositionSelector", start: 12, end: 30 },
    { type: "TextQuoteSelector", exact: "behave like a wave" },
  ],
  author: "user",
  created_at: 1,
  updated_at: 1,
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (payload: unknown, status = 200) =>
      route.fulfill({ status, json: payload });

    if (path === "/api/auth/status") {
      return json({
        enabled: false,
        authenticated: true,
        user_id: "reader",
        username: "reader",
        role: "user",
        is_admin: false,
      });
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
    if (path === "/api/reading/supported-formats") {
      return json({
        extensions: [".txt"],
        max_bytes: 1024,
        raw_view_extensions: [],
      });
    }
    if (path === "/api/reading/extensions") return json([]);
    if (path === `/api/reading/workspaces/${WORKSPACE_ID}`) {
      return json({ workspace, sessions: [] });
    }
    if (path === `/api/reading/workspaces/${WORKSPACE_ID}/sessions`) {
      return json({ sessions: [] });
    }
    if (path === "/api/reading/materials") return json([material]);
    if (path === "/api/reading/materials/w3c-material") {
      return json(material);
    }
    if (path === "/api/reading/materials/w3c-material/annotations") {
      return json([annotation]);
    }
    if (path === "/api/reading/materials/w3c-material/units/1") {
      return json({
        locator: 1,
        unit: "section",
        text: "# Light can behave like a wave\n\nand sometimes like a particle.",
      });
    }
    return json({});
  });
});

test("a rich text annotation reflows and activates its sidebar entry", async ({
  page,
}) => {
  await page.goto(`/reading/${WORKSPACE_ID}`);

  const highlight = page.locator(".r6o-annotation").first();
  await expect(highlight).toBeVisible();
  const heading = page.locator(
    '[data-reader-heading-id="dt-reader-heading-1-1"]',
  );
  await expect(heading).toBeVisible();
  await expect(heading).toContainText("# Light can behave like a wave");
  await expect(page.locator("article.r6o-annotatable")).toHaveText(
    "# Light can behave like a wave\n\nand sometimes like a particle.",
  );

  await page.setViewportSize({ width: 1100, height: 700 });
  await expect(highlight).toBeVisible();
  await expect(highlight).toHaveAttribute("data-annotation", "annotation-1");

  const sidebarEntry = page
    .getByRole("button")
    .filter({ hasText: "Wave behavior" });
  await expect(sidebarEntry).toBeVisible();
  await page.getByRole("button", { name: "Close reading companion" }).click();
  await page.getByRole("button", { name: "Collapse contents" }).first().click();
  await expect(page.getByRole("button", { name: "Close panels" })).toBeHidden();
  const article = page.locator("article.r6o-annotatable");
  const articleBox = await article.boundingBox();
  const highlightBox = await highlight.boundingBox();
  if (!articleBox || !highlightBox) {
    throw new Error("Reader annotation boxes were not measurable");
  }
  await article.click({
    position: {
      x: Math.max(
        1,
        Math.round(highlightBox.x - articleBox.x + highlightBox.width / 2),
      ),
      y: Math.max(
        1,
        Math.round(highlightBox.y - articleBox.y + highlightBox.height / 2),
      ),
    },
  });
  await expect(sidebarEntry).toHaveClass(/border-\[var\(--ring\)\]/);
});
