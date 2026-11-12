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
        ? [
            { name: "figure.svg", locator: 1, mime: "image/svg+xml", bytes: 512 },
            { name: "figure-two.svg", locator: 1, mime: "image/svg+xml", bytes: 512 },
          ]
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
        { name: "figure-two.svg", locator: 1, mime: "image/svg+xml", bytes: 512 },
      ]);
    }
    if (path === `/api/reading/materials/${MATERIAL_B}/media`) return json([]);
    if (path === `/api/reading/materials/${MATERIAL_A}/media/figure-two.svg`) {
      return route.fulfill({
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200"><rect width="300" height="200" fill="#06c"/><text x="150" y="105" font-size="24" text-anchor="middle" fill="#fff">second</text></svg>',
      });
    }
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
  await page.screenshot({
    path: test.info().outputPath("20-lightbox-open.png"),
  });

  // Zoom in twice with the toolbar; the toolbar must not dismiss the view.
  await dialog.getByRole("button", { name: "Zoom in" }).click();
  await dialog.getByRole("button", { name: "Zoom in" }).click();
  await expect(dialog).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("21-lightbox-zoomed.png"),
  });

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

  // The bottom toolbar band spans the whole window, so its empty strip either
  // side of the toolbar must fall through to the stage and dismiss. It used to
  // swallow that click: the band was hit-testable but had no handler.
  await picture.click();
  await expect(dialog).toBeVisible();
  // bottom-4 is 16px and the band is ~36px tall, so this is the middle of its
  // empty left strip, far from the centred toolbar.
  await page.mouse.click(100, 900 - 16 - 18);
  await expect(dialog).toHaveCount(0);

  // Tab must stay inside the modal instead of walking into the reader behind
  // it: from the last control it wraps to the first, and back with Shift+Tab.
  await picture.click();
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Close" }).focus();
  await page.keyboard.press("Tab");
  // The trap wraps to the first FOCUSABLE control. "Previous image" is first in
  // the DOM but disabled on the opening picture, and a disabled button is not
  // focusable — so the wrap lands on the first enabled one. Asserting a fixed
  // button here would encode the fixture's picture count, not the trap.
  const firstEnabled = dialog.getByRole("button").and(
    page.locator(":not([disabled])"),
  ).first();
  await expect(firstEnabled).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("button", { name: "Close" })).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
});

/**
 * The focus trap, checked against a real browser's tab order.
 *
 * `aria-modal` tells assistive technology the rest of the page is inert, but the
 * browser still tabs through it. jsdom has no tab order at all, so this is one
 * of the things only a real browser can answer — and a trap that leaks is worse
 * than none, because the reader lands in the reader behind an opaque overlay.
 */
test("Tab never escapes the picture viewer", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/learning/reading/${WORKSPACE_ID}/sessions/${SESSION_ONE}`, {
    waitUntil: "domcontentloaded",
  });
  await expect(page.locator("figure img").first()).toBeVisible({
    timeout: 20_000,
  });
  await page.locator("figure img").first().click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible({ timeout: 10_000 });

  // Forward through more stops than the dialog has, then back.
  for (const key of [...Array(12).fill("Tab"), ...Array(12).fill("Shift+Tab")]) {
    await page.keyboard.press(key);
    // `dialog` is the locator for THIS overlay, not "any role=dialog on the
    // page" — the reader also renders an annotation popover with that role.
    const inside = await dialog.evaluate((root) => {
      const active = document.activeElement as HTMLElement | null;
      return Boolean(active && root.contains(active));
    });
    expect(inside).toBe(true);
  }
});

/**
 * Stepping through the pictures of one unit, in a real browser.
 *
 * The list comes from the reader's own DOM, so this also proves that the
 * enumeration finds both pictures the fixture renders — a unit test can pass a
 * list in, but only the browser shows whether the reader builds it.
 */
test("the arrow keys step through the unit's pictures", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/learning/reading/${WORKSPACE_ID}/sessions/${SESSION_ONE}`, {
    waitUntil: "domcontentloaded",
  });

  const pictures = page.locator("figure img");
  await expect(pictures.first()).toBeVisible({ timeout: 20_000 });
  const count = await pictures.count();
  expect(count).toBeGreaterThan(1);

  await pictures.first().click();
  const dialog = page.getByRole("dialog", { name: "Image" });
  await expect(dialog).toBeVisible({ timeout: 10_000 });
  await expect(dialog).toContainText(`1 / ${count}`);

  // Right moves forward and the counter follows.
  await page.keyboard.press("ArrowRight");
  await expect(dialog).toContainText(`2 / ${count}`);

  // Left comes back.
  await page.keyboard.press("ArrowLeft");
  await expect(dialog).toContainText(`1 / ${count}`);

  // At the first picture, Left is spent — it must not wrap to the end.
  await page.keyboard.press("ArrowLeft");
  await expect(dialog).toContainText(`1 / ${count}`);
  await expect(dialog.getByRole("button", { name: "Previous image" })).toBeDisabled();

  // The step also drops the zoom: zoom in, step, and the toolbar reads 100%.
  await dialog.getByRole("button", { name: "Zoom in" }).click();
  await expect(dialog).not.toContainText("100%");
  await page.keyboard.press("ArrowRight");
  await expect(dialog).toContainText("100%");
  await page.screenshot({
    path: test.info().outputPath("22-lightbox-second-picture.png"),
  });
});
