import { expect, test } from "@playwright/test";

const MATERIAL_A = "aaaaaaaaaaaaaaaa";
const MATERIAL_B = "bbbbbbbbbbbbbbbb";
const SESSION_ID = "citation-material-regression";

function material(materialId: string, title: string) {
  return {
    material_id: materialId,
    filename: `${title}.md`,
    unit: "section",
    unit_count: 2,
    mime: "text/markdown",
    title,
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
}

const materialA = material(MATERIAL_A, "Source material A");
const materialB = material(MATERIAL_B, "Current material B");

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (payload: unknown, status = 200) =>
      route.fulfill({ status, json: payload });

    if (path === "/api/v1/auth/status") {
      return json({ enabled: false, authenticated: true });
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
    if (path === `/api/v1/sessions/${SESSION_ID}`) {
      return json({
        id: SESSION_ID,
        session_id: SESSION_ID,
        title: "Citation material regression",
        created_at: 1,
        updated_at: 2,
        status: "idle",
        preferences: { capability: "immersive_reading" },
        active_turns: [],
        messages: [
          {
            id: 1,
            session_id: SESSION_ID,
            role: "user",
            content: "Where is the source passage?",
            capability: "immersive_reading",
            events: [],
            attachments: [],
            metadata: {
              request_snapshot: {
                content: "Where is the source passage?",
                capability: "immersive_reading",
                enabledTools: [],
                knowledgeBases: [],
                language: "en",
                readingMaterialId: MATERIAL_A,
              },
            },
            created_at: 1,
            parent_message_id: null,
          },
          {
            id: 2,
            session_id: SESSION_ID,
            role: "assistant",
            content: "The grounded passage is here [p.2]. A guess is [p.1].",
            capability: "immersive_reading",
            attachments: [],
            created_at: 2,
            parent_message_id: 1,
            events: [
              {
                type: "tool_result",
                source: "chat",
                stage: "responding",
                content: "Read section 2",
                timestamp: 1,
                metadata: {
                  tool: "read_material",
                  tool_metadata: {
                    material_id: MATERIAL_A,
                    locators: [2],
                  },
                },
              },
            ],
          },
        ],
      });
    }
    if (path === "/api/v1/sessions") return json({ sessions: [] });
    if (path === "/api/v1/reading/supported-formats") {
      return json({
        extensions: [".md"],
        max_bytes: 1024,
        raw_view_extensions: [],
      });
    }
    if (path === "/api/v1/reading/extensions") return json([]);
    if (path === "/api/v1/reading/materials") {
      return json([materialB, materialA]);
    }
    if (path === `/api/v1/reading/materials/${MATERIAL_A}`)
      return json(materialA);
    if (path === `/api/v1/reading/materials/${MATERIAL_B}`)
      return json(materialB);
    if (path.endsWith("/annotations")) return json([]);
    const unit = /\/api\/v1\/reading\/materials\/([^/]+)\/units\/(\d+)/.exec(
      path,
    );
    if (unit) {
      const [, materialId, locator] = unit;
      return json({
        locator: Number(locator),
        unit: "section",
        text:
          materialId === MATERIAL_A
            ? `# Source A section ${locator}\n\nVerified source material text.`
            : `# Current B section ${locator}\n\nWrong material text.`,
      });
    }
    return json({});
  });
});

test("historical citation reopens its turn material and unsupported locator stays plain", async ({
  page,
}) => {
  await page.goto(`/home/${SESSION_ID}`);

  await expect(page.getByRole("link", { name: "p.2" })).toHaveAttribute(
    "href",
    `#dt-material-${MATERIAL_A}-locator-2`,
  );
  await expect(page.getByRole("link", { name: "p.1" })).toHaveCount(0);

  await page
    .getByRole("button", { name: /Immersive Reading/ })
    .last()
    .click();
  await page.getByRole("button", { name: "Open a document to read" }).click();
  await page.getByText("Current material B.md").click();
  await expect(page.getByText("Wrong material text.")).toBeVisible();

  await page.getByRole("link", { name: "p.2" }).click();
  await expect(page.getByText("Verified source material text.")).toBeVisible();
  await expect(page.getByText("Wrong material text.")).toHaveCount(0);
});
