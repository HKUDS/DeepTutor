import { expect, test } from "@playwright/test";

const markdown = [
  "# Web Snapshot",
  "",
  "Structured **Markdown** renders safely.",
  "",
  "```html",
  "<img src=\"https://images.example.com/remote.png\" alt=\"remote\">",
  "```",
  "",
  "![remote](https://images.example.com/remote.png)",
].join("\n");

const material = {
  material_id: "web-markdown-material",
  filename: "Web Snapshot.md",
  unit: "section",
  unit_count: 1,
  mime: "text/markdown",
  title: "Web Snapshot",
  byte_size: markdown.length,
  char_count: markdown.length,
  created_at: 1,
  has_raw_view: false,
  content_format: "web_markdown",
  source_type: "url_snapshot",
  source_url: "https://docs.example.com/snapshot",
  annotation_count: 1,
  outline: [{ locator: 1, title: "Web Snapshot", id: "dt-reader-heading-1-1" }],
  outline_text: "Web Snapshot",
};

const annotation = {
  annotation_id: "annotation-1",
  locator: 1,
  kind: "highlight",
  color: "yellow",
  quote: "Structured Markdown renders safely.",
  note: "Rich snapshot",
  rects: [],
  selectors: [
    {
      type: "TextQuoteSelector",
      exact: "Structured Markdown renders safely.",
    },
    { type: "TextPositionSelector", start: 14, end: 46 },
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
      return json({ extensions: [".md"], max_bytes: 1024, raw_view_extensions: [] });
    }
    if (path === "/api/v1/reading/extensions") return json([]);
    if (path === "/api/v1/reading/materials") return json([material]);
    if (path === "/api/v1/reading/materials/web-markdown-material") {
      return json(material);
    }
    if (path === "/api/v1/reading/materials/web-markdown-material/annotations") {
      return json([annotation]);
    }
    if (path === "/api/v1/reading/materials/web-markdown-material/units/1") {
      return json({ locator: 1, unit: "section", text: markdown });
    }
    return json({});
  });
});

test("captured web snapshots render safe structured Markdown with annotations", async ({
  page,
}) => {
  await page.goto("/home");

  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await page.getByRole("button", { name: /Immersive Reading/ }).last().click();
  await page.getByRole("button", { name: "Open a document to read" }).click();
  await page.getByText("Web Snapshot.md").click();

  const article = page.locator("article.r6o-annotatable");
  await expect(article).toBeVisible();
  await expect(
    page.locator('[data-reader-heading-id="dt-reader-heading-1-1"]'),
  ).toHaveText("Web Snapshot");
  await expect(page.locator(".r6o-annotation").first()).toBeVisible();
  await expect(article).toContainText("Structured Markdown renders safely.");
  await expect(article.locator("img")).toHaveCount(0);
  await expect(article.locator("script")).toHaveCount(0);
  await expect(article.locator("code").last()).toContainText("<img src=");
});
