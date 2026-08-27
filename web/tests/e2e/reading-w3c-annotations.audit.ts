import { expect, test } from "@playwright/test";

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
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (payload: unknown, status = 200) =>
      route.fulfill({ status, json: payload });

    if (path === "/api/v1/auth/status") {
      return json({
        enabled: false,
        authenticated: true,
        user_id: "reader",
        username: "reader",
        role: "user",
        is_admin: false,
      });
    }
    if (path === "/api/v1/settings/ui") return json({ language: "en" });
    if (path === "/api/v1/dashboard/suggestions") {
      return json({ suggestions: [], stale: false });
    }
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
    if (path === "/api/v1/reading/supported-formats") {
      return json({
        extensions: [".txt"],
        max_bytes: 1024,
        raw_view_extensions: [],
      });
    }
    if (path === "/api/v1/reading/extensions") return json([]);
    if (path === "/api/v1/reading/materials") return json([material]);
    if (path === "/api/v1/reading/materials/w3c-material") {
      return json(material);
    }
    if (path === "/api/v1/reading/materials/w3c-material/annotations") {
      return json([annotation]);
    }
    if (path === "/api/v1/reading/materials/w3c-material/units/1") {
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
  await page.goto("/home");

  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await page
    .getByRole("button", { name: /Immersive Reading/ })
    .last()
    .click();
  await page.getByRole("button", { name: "Open a document to read" }).click();
  await page.getByText("W3C Annotation Sample.txt").click();

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
