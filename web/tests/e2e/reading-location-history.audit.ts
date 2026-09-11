import { expect, test } from "@playwright/test";

const MATERIAL_A = "aaaaaaaaaaaaaaaa";
const MATERIAL_B = "bbbbbbbbbbbbbbbb";
const MATERIAL_MISSING = "cccccccccccccccc";
const SESSION_ONE = "reading-history-one";
const SESSION_TWO = "reading-history-two";
const SESSION_MISSING = "reading-history-missing";
const WORKSPACE_ID = "reading-history-workspace";

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
    outline: [
      { title: `${title} first`, locator: 1, level: 1 },
      { title: `${title} second`, locator: 2, level: 1 },
    ],
    outline_text: "",
    unit_refs: [],
  };
}

const materialA = material(MATERIAL_A, "History material A");
const materialB = material(MATERIAL_B, "History material B");

function libraryMaterial(materialId: string, title: string) {
  return {
    material_id: materialId,
    content_id: materialId,
    filename: `${title}.md`,
    title,
    source_kind: "file",
    source_url: "",
    mime: "text/markdown",
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
    size_bytes: 256,
    unit_count: 2,
    collections: [],
  };
}

function workspace(activeMaterialId: string) {
  return {
    workspace_id: WORKSPACE_ID,
    title: "Reading history regression",
    description: "",
    active_material_id: activeMaterialId,
    created_at: 1,
    updated_at: 2,
    tabs: [
      {
        material: libraryMaterial(MATERIAL_A, "History material A"),
        tab_order: 0,
        pinned: false,
        opened: true,
        added_at: 1,
      },
      {
        material: libraryMaterial(MATERIAL_B, "History material B"),
        tab_order: 1,
        pinned: false,
        opened: true,
        added_at: 2,
      },
    ],
  };
}

function session(sessionId: string) {
  return {
    id: sessionId,
    session_id: sessionId,
    title: "Reading history regression",
    created_at: 1,
    updated_at: 2,
    status: "idle",
    preferences: { capability: "immersive_reading" },
    active_turns: [],
    messages: [],
  };
}

test.beforeEach(async ({ page }) => {
  let activeMaterialId = MATERIAL_A;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (payload: unknown, status = 200) =>
      route.fulfill({ status, json: payload });

    if (path === "/api/auth/status") {
      return json({ enabled: false, authenticated: true });
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
    if (
      path === `/api/sessions/${SESSION_ONE}` ||
      path === `/api/sessions/${SESSION_TWO}` ||
      path === `/api/sessions/${SESSION_MISSING}`
    ) {
      return json(session(path.split("/").at(-1) || ""));
    }
    if (path === "/api/sessions") return json({ sessions: [] });
    if (path === "/api/reading/supported-formats") {
      return json({
        extensions: [".md"],
        max_bytes: 1024,
        raw_view_extensions: [],
      });
    }
    if (path === "/api/reading/extensions") return json([]);
    if (path === `/api/reading/workspaces/${WORKSPACE_ID}`) {
      return json({
        workspace: workspace(activeMaterialId),
        sessions: [],
      });
    }
    if (path === `/api/reading/workspaces/${WORKSPACE_ID}/sessions`) {
      return json({ sessions: [] });
    }
    const activate =
      /\/api\/reading\/workspaces\/[^/]+\/materials\/([^/]+)\/active$/.exec(
        path,
      );
    // The workspace API activates an existing tab with PUT.
    if (activate && route.request().method() === "PUT") {
      activeMaterialId = activate[1] || MATERIAL_A;
      return json({ workspace: workspace(activeMaterialId) });
    }
    if (path === "/api/reading/materials") {
      return json([materialA, materialB]);
    }
    if (path === `/api/reading/materials/${MATERIAL_A}`) {
      return json(materialA);
    }
    if (path === `/api/reading/materials/${MATERIAL_B}`) {
      return json(materialB);
    }
    if (path === `/api/reading/materials/${MATERIAL_MISSING}`) {
      return json({ detail: "Material is no longer available" }, 404);
    }
    if (path.endsWith("/annotations")) return json([]);
    const unit = /\/api\/reading\/materials\/([^/]+)\/units\/(\d+)/.exec(path);
    if (unit) {
      const [, materialId, locator] = unit;
      const title = materialId === MATERIAL_A ? "A" : "B";
      return json({
        locator: Number(locator),
        unit: "section",
        text: `# ${title} section ${locator}\n\nHistory ${title}${locator} text.`,
      });
    }
    return json({});
  });
});

test("back and forward cross materials, survive reload, and stay session-scoped", async ({
  page,
}) => {
  await page.goto(`/reading/${WORKSPACE_ID}/sessions/${SESSION_ONE}`);
  await expect(page.getByText("History A1 text.")).toBeVisible();

  await page.getByRole("button", { name: "History material A second" }).click();
  await expect(page.getByText("History A2 text.")).toBeVisible();

  await page.getByRole("button", { name: "History material B" }).click();
  await expect(page.getByText("History B1 text.")).toBeVisible();

  await page.getByRole("button", { name: "Back", exact: true }).click();
  await expect(page.getByText("History A2 text.")).toBeVisible();
  await page.getByRole("button", { name: "Forward", exact: true }).click();
  await expect(page.getByText("History B1 text.")).toBeVisible();

  await page.reload();
  await expect(page.getByText("History B1 text.")).toBeVisible();

  await page.goto(`/reading/${WORKSPACE_ID}/sessions/${SESSION_TWO}`);
  await page.getByRole("button", { name: "History material B" }).click();
  await expect(
    page.getByRole("button", { name: "Back", exact: true }),
  ).toBeDisabled();
});

test("a deleted material remains identifiable and does not block older history", async ({
  page,
}) => {
  await page.addInitScript(
    ({ key, value }) => window.localStorage.setItem(key, value),
    {
      key: `dt.reader.history.${encodeURIComponent(SESSION_MISSING)}`,
      value: JSON.stringify({
        entries: [
          {
            materialId: MATERIAL_A,
            locator: 1,
            title: "History material A",
          },
          {
            materialId: MATERIAL_MISSING,
            locator: 2,
            title: "Deleted reading material",
          },
        ],
        index: 1,
      }),
    },
  );

  await page.goto(`/reading/${WORKSPACE_ID}/sessions/${SESSION_MISSING}`);
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Material is no longer available" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "History", exact: true }).click();
  await expect(page.getByText("Deleted reading material")).toBeVisible();
  await expect(page.getByText("Section 2 · Unavailable")).toBeVisible();

  await page.getByRole("button", { name: "Back", exact: true }).click();
  await expect(page.getByText("History A1 text.")).toBeVisible();
});
