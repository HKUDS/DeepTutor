import { expect, test } from "@playwright/test";

const material = {
  material_id: "graph-material",
  filename: "Relationship Sample.txt",
  unit: "section",
  unit_count: 2,
  mime: "text/plain",
  title: "Relationship Sample",
  byte_size: 256,
  char_count: 128,
  created_at: 1,
  has_raw_view: false,
  render_mode: "text",
  annotation_count: 0,
  outline: [],
  outline_text: "",
  unit_refs: [],
};

function graphResponse(scope: "current" | "through_current") {
  const priorSection = scope === "through_current" ? 1 : null;
  return {
    graph: {
      nodes: [
        {
          id: "entity_1",
          name: "Ada",
          aliases: ["Countess Lovelace"],
          description: "The analyst in this chapter.",
          confidence: 0.92,
        },
        {
          id: "entity_2",
          name: "Analytical Engine",
          aliases: [],
          description: "The machine discussed by Ada.",
          confidence: 0.88,
        },
      ],
      edges: [
        {
          source: "entity_1",
          target: "entity_2",
          relation: "describes",
          evidence: "Ada describes the Analytical Engine.",
          evidence_locators: priorSection === null ? [2] : [1, 2],
          confidence: 0.9,
        },
      ],
    },
    mermaid: 'graph LR\n  entity_1["Ada"] -- "describes" --> entity_2',
    generated_at: 1,
    scope,
    locator: 2,
    included_locators: priorSection === null ? [2] : [1, 2],
    truncated: false,
  };
}

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
    if (path === "/api/v1/reading/materials/graph-material") {
      return json(material);
    }
    if (path === "/api/v1/reading/materials/graph-material/annotations") {
      return json([]);
    }
    if (path === "/api/v1/reading/materials/graph-material/units/1") {
      return json({
        locator: 1,
        unit: "section",
        text: "Earlier, Charles Babbage introduces the machine.",
      });
    }
    if (path === "/api/v1/reading/materials/graph-material/units/2") {
      return json({
        locator: 2,
        unit: "section",
        text: "Ada describes the Analytical Engine.",
      });
    }
    if (path === "/api/v1/reading/materials/graph-material/character-graph") {
      const payload = route.request().postDataJSON() as {
        scope: "current" | "through_current";
      };
      return json(graphResponse(payload.scope));
    }
    return json({});
  });
});

test("the relationship graph overlays the chapter and preserves reading context", async ({
  page,
}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.goto("/home");

  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await page
    .getByRole("button", { name: /Immersive Reading/ })
    .last()
    .click();
  await page.getByRole("button", { name: "Open a document to read" }).click();
  await page.getByText("Relationship Sample.txt").click();
  await expect(
    page.getByText("Charles Babbage introduces the machine."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(
    page
      .locator("article.r6o-annotatable")
      .filter({ hasText: "Ada describes the Analytical Engine." }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Relationship graph" }).click();
  const panel = page
    .getByRole("complementary")
    .filter({ hasText: "Relationship graph" });
  await expect(panel).toBeVisible();
  await expect(panel.getByText("Ada", { exact: true })).toBeVisible();
  await expect(
    panel.getByText("Analytical Engine", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByText("Section 2", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Through current unit" }),
  ).toBeVisible();

  await page
    .getByRole("button", { name: "Through current unit" })
    .click();
  await expect(
    panel.getByText("Section 1, Section 2").first(),
  ).toBeVisible();
  await expect(
    page
      .locator("article.r6o-annotatable")
      .filter({ hasText: "Ada describes the Analytical Engine." }),
  ).toBeVisible();
  expect(pageErrors).toEqual([]);
});
