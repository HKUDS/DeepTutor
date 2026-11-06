import { sourceModuleInventory } from "./fixtures/modules";
import { emptyLearningIndex } from "./fixtures/learning-index";
import { expect, test } from "@playwright/test";
import { emptyTaskBoard } from "./fixtures/task-board";

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
    media:
      title === "History material A"
        ? [{ name: "figure.svg", locator: 1, mime: "image/svg+xml", bytes: 512 }]
        : [],
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
    if (path === "/api/modules") return route.fulfill({ json: sourceModuleInventory });
    const json = (payload: unknown, status = 200) =>
      route.fulfill({ status, json: payload });

    if (path === "/api/dashboard/learning-index") return json(emptyLearningIndex);
    if (path === "/api/partners" || path === "/api/partner-groups") return json([]);
    if (path === "/api/task-board") return json(emptyTaskBoard);
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
    if (path === `/api/reading/materials/${MATERIAL_A}/media`) {
      return json([
        { name: "figure.svg", locator: 1, mime: "image/svg+xml", bytes: 512 },
      ]);
    }
    if (path === `/api/reading/materials/${MATERIAL_B}/media`) return json([]);
    if (path === `/api/reading/materials/${MATERIAL_A}/media/figure.svg`) {
      return route.fulfill({
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200"><rect width="300" height="200" fill="#c00"/><text x="150" y="105" font-size="24" text-anchor="middle" fill="#fff">figure</text></svg>',
      });
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


const SHOTS = "/Users/laiyongqiang/code/DeepTutor/.visual";

test("a picture opens full-screen, and tapping it does not dismiss the view", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/learning/reading/${WORKSPACE_ID}/sessions/${SESSION_ONE}`, {
    waitUntil: "domcontentloaded",
  });

  const picture = page.locator("figure img").first();
  await expect(picture).toBeVisible({ timeout: 20_000 });

  await picture.click();
  const dialog = page.getByRole("dialog", { name: "Image" });
  await expect(dialog).toBeVisible({ timeout: 10_000 });
  await page.screenshot({ path: `${SHOTS}/20-lightbox-open.png` });

  // Zoom in twice with the toolbar; the toolbar must not dismiss the view.
  await dialog.getByRole("button", { name: "Zoom in" }).click();
  await dialog.getByRole("button", { name: "Zoom in" }).click();
  await expect(dialog).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/21-lightbox-zoomed.png` });

  // The regression: a plain click on the zoomed picture closed the viewer,
  // because pointer capture retargeted the click to the stage.
  const box = await dialog.locator("img").first().boundingBox();
  if (!box) throw new Error("the picture has no box");
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(dialog).toBeVisible();

  // Double-click toggles back to fit instead of closing on the first click.
  await page.mouse.dblclick(box.x + box.width / 2, box.y + box.height / 2);
  await expect(dialog).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);

  // A click on genuinely empty space still dismisses.
  await picture.click();
  await expect(dialog).toBeVisible();
  await page.mouse.click(20, 20);
  await expect(dialog).toHaveCount(0);
});
