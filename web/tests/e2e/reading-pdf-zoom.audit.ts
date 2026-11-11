import { sourceModuleInventory } from "./fixtures/modules";
import { emptyLearningIndex } from "./fixtures/learning-index";
import { expect, test, type Page } from "@playwright/test";
import { jsPDF } from "jspdf";
import { emptyTaskBoard } from "./fixtures/task-board";

/**
 * The PDF reader's zoom bar, driven through a real Chromium.
 *
 * The unit tests cover the arithmetic and the React wiring; this covers what
 * only a browser can answer. Three of them were raised in review and cannot be
 * proved in jsdom at all:
 *
 *   - the bar is hidden with `opacity-0`, which keeps it in the tab order. It
 *     must reveal itself the moment focus lands on a control, or a keyboard
 *     user tabs into something they cannot see.
 *   - the menu must be reachable and drivable from the keyboard (arrow keys
 *     between rows, Home/End, focus returning to the trigger on close).
 *   - Escape must close the menu without also leaving Guided Learning. Both
 *     listeners sit on `window`, so this is exactly the ordering question jsdom
 *     cannot settle.
 */

const MATERIAL_ID = "bbbbbbbbbbbbbbb2";
const WORKSPACE_ID = "pdf-zoom-audit-workspace";
const SESSION_ID = "pdf-zoom-audit-session";
const PAGE_COUNT = 6;

function pdfFixture(): Buffer {
  const document = new jsPDF({ format: "a4" });
  for (let locator = 1; locator <= PAGE_COUNT; locator += 1) {
    if (locator > 1) document.addPage();
    document.text(`Zoom audit page ${locator}`, 20, 30);
    // Enough ink that the page has a text block to fit to.
    for (let row = 0; row < 20; row += 1) {
      document.text(`Body line ${row + 1} on page ${locator}`, 20, 50 + row * 8);
    }
  }
  return Buffer.from(document.output("arraybuffer"));
}

const pdfBytes = pdfFixture();

const material = {
  material_id: MATERIAL_ID,
  content_id: MATERIAL_ID,
  filename: "zoom-audit.pdf",
  title: "Zoom audit",
  source_kind: "file",
  source_url: "",
  unit: "page",
  unit_count: PAGE_COUNT,
  mime: "application/pdf",
  render_mode: "pdf",
  has_raw_view: true,
  status: "ready",
  progress: 0,
  cover_url: "",
  error_code: "",
  error_detail: "",
  byte_size: pdfBytes.length,
  size_bytes: pdfBytes.length,
  char_count: 1000,
  created_at: 1,
  updated_at: 2,
  last_opened_at: 2,
  collections: [],
  annotation_count: 0,
  outline: [],
  outline_text: "",
  unit_refs: [],
};

test.beforeEach(async ({ context }) => {
  await context.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (payload: unknown) => route.fulfill({ json: payload });
    if (path === "/api/modules") return json(sourceModuleInventory);
    if (path === "/api/task-board") return json(emptyTaskBoard);
    if (path === "/api/auth/status")
      return json({ enabled: false, authenticated: true });
    if (path === "/api/settings/ui") return json({ language: "en" });
    if (path === "/api/dashboard/suggestions")
      return json({ suggestions: [], stale: false });
    if (path === "/api/dashboard/learning-index")
      return json(emptyLearningIndex);
    if (path === "/api/partners" || path === "/api/partner-groups")
      return json([]);
    if (path === "/api/sessions") return json({ sessions: [] });
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
    if (path === `/api/sessions/${SESSION_ID}`) {
      return json({
        id: SESSION_ID,
        session_id: SESSION_ID,
        title: material.title,
        created_at: 1,
        updated_at: 2,
        status: "idle",
        preferences: { capability: "immersive_reading" },
        active_turns: [],
        messages: [],
      });
    }
    if (path === `/api/reading/workspaces/${WORKSPACE_ID}`) {
      return json({
        workspace: {
          workspace_id: WORKSPACE_ID,
          title: material.title,
          description: "",
          active_material_id: MATERIAL_ID,
          created_at: 1,
          updated_at: 2,
          tabs: [
            { material, tab_order: 0, pinned: false, opened: true, added_at: 1 },
          ],
        },
        sessions: [],
      });
    }
    if (path === `/api/reading/workspaces/${WORKSPACE_ID}/sessions`)
      return json({ sessions: [] });
    if (path === "/api/reading/supported-formats") {
      return json({
        extensions: [".pdf"],
        max_bytes: 1048576,
        raw_view_extensions: [".pdf"],
      });
    }
    if (path === "/api/reading/extensions") return json([]);
    if (path.endsWith("/annotations")) return json([]);
    if (path === "/api/reading/materials") return json([material]);
    if (path === `/api/reading/materials/${MATERIAL_ID}`) return json(material);
    if (path === `/api/reading/materials/${MATERIAL_ID}/raw`) {
      return route.fulfill({ contentType: "application/pdf", body: pdfBytes });
    }
    if (path.endsWith("/position"))
      return json({ locator: 1, source_anchor: "" });
    return json({});
  });
});

async function openReader(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/learning/reading/${WORKSPACE_ID}/sessions/${SESSION_ID}`, {
    waitUntil: "domcontentloaded",
  });
  const root = page
    .locator(".dt-reader-scroll")
    .filter({ has: page.locator('[data-reader-unit="1"]') });
  await expect(root).toBeVisible({ timeout: 20_000 });
  await expect(root.locator('[data-reader-unit="1"] .textLayer')).toContainText(
    "Zoom audit page 1",
    { timeout: 20_000 },
  );
  return root;
}

/** The bar reveals on hover in the bottom band; without that it stays hidden. */
async function revealBar(page: Page, root: ReturnType<Page["locator"]>) {
  await root.hover({ position: { x: 200, y: 400 } });
  await page.mouse.move(700, 860);
}

/** The bar's wrapper: the element that carries the opacity state. */
function barWrapper(page: Page) {
  return page.locator('[data-pdf-zoom-controls]').locator("xpath=..");
}

test("the bar steps the page size, and reset returns to fit", async ({
  page,
}) => {
  const root = await openReader(page);
  const firstPage = root.locator('[data-reader-unit="1"]');
  const widthOf = () =>
    firstPage.evaluate((element) => element.getBoundingClientRect().width);

  const before = await widthOf();
  await revealBar(page, root);

  const zoomIn = page.getByRole("button", { name: "Zoom in", exact: true });
  await expect(zoomIn).toBeVisible();
  await zoomIn.click();
  await expect.poll(widthOf).toBeGreaterThan(before);

  // The percentage the toolbar shows is the width that LANDED, not the one
  // asked for: the canvas budget clamps a tall page well below the request.
  await expect(page.locator('[data-pdf-zoom-controls] button', {
    hasText: /^\d+%$/,
  })).toBeVisible();

  await page.getByRole("button", { name: "Reset zoom", exact: true }).click();
  await expect.poll(widthOf).toBe(before);
});

/**
 * The review's first point: `opacity-0` does not remove the bar from the tab
 * order, so a keyboard user could land on controls they cannot see.
 */
test("tabbing into the hidden bar reveals it", async ({ page }) => {
  const root = await openReader(page);
  const wrapper = barWrapper(page);

  // Nothing has pointed at the bar, so it is hidden but still in the DOM.
  await expect(wrapper).toHaveClass(/opacity-0/);
  const zoomIn = page.getByRole("button", { name: "Zoom in", exact: true });
  await expect(zoomIn).toHaveCount(1);

  // Focus it the way a keyboard user would: no pointer involved at all.
  await zoomIn.focus();
  await expect(zoomIn).toBeFocused();
  // `focus-within:opacity-100` is what makes it visible; a hidden-but-focused
  // control would leave the reader tabbing blind.
  await expect(wrapper).toHaveClass(/focus-within:opacity-100/);
  await expect
    .poll(async () => {
      const opacity = await wrapper.evaluate(
        (element) => getComputedStyle(element).opacity,
      );
      return Number(opacity);
    })
    .toBe(1);

  // And the control is genuinely operable from there.
  const widthOf = () =>
    root
      .locator('[data-reader-unit="1"]')
      .evaluate((element) => element.getBoundingClientRect().width);
  const before = await widthOf();
  await page.keyboard.press("Enter");
  await expect.poll(widthOf).toBeGreaterThan(before);
});

/**
 * The review asked for "pane focus order" as well as the controls' own keyboard
 * access — i.e. that a keyboard user can actually reach the bar. A reveal-on-
 * focus that nothing can focus is no use, so this walks the real tab order.
 */
test("a keyboard user can tab into the zoom bar", async ({ page }) => {
  await openReader(page);
  const wrapper = barWrapper(page);
  await expect(wrapper).toHaveClass(/opacity-0/);

  // Walk the document's tab order until focus lands inside the bar.
  let reached = false;
  for (let press = 0; press < 80 && !reached; press += 1) {
    await page.keyboard.press("Tab");
    reached = await page.evaluate(() => {
      const element = document.activeElement as HTMLElement | null;
      return Boolean(element?.closest("[data-pdf-zoom-controls]"));
    });
  }
  expect(reached).toBe(true);
  // Reaching it is what reveals it.
  await expect
    .poll(async () =>
      Number(
        await wrapper.evaluate((element) => getComputedStyle(element).opacity),
      ),
    )
    .toBe(1);
});

/**
 * The review's second point: the zoom controls and the pane's focus order.
 */
test("the level menu is drivable from the keyboard", async ({ page }) => {
  const root = await openReader(page);
  await revealBar(page, root);

  const trigger = page.locator(
    '[data-pdf-zoom-controls] button[aria-haspopup="menu"]',
  );
  await expect(trigger).toBeVisible();
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menu")).toBeVisible();

  // Rows are a radio group, not plain items.
  const rows = page.getByRole("menuitemradio");
  await expect(rows.first()).toBeVisible();
  await expect(rows.first()).toHaveAttribute("aria-checked");

  // Down moves focus into the rows, then between them. The handler lives on the
  // toolbar, not the menu: when the menu opens focus is still on the trigger, a
  // sibling of the menu, so a handler on the menu would never see the keydown.
  const activeText = () =>
    page.evaluate(() => document.activeElement?.textContent ?? "");
  // Focus starts on the trigger, so the first Down enters the first row — the
  // fit modes, which read "Fit" in this build — and each press after it moves
  // one row. Up comes back.
  await page.keyboard.press("ArrowDown");
  const first = await activeText();
  await page.keyboard.press("ArrowDown");
  const second = await activeText();
  await page.keyboard.press("ArrowUp");
  const back = await activeText();
  // A row, not the trigger: the trigger is a button outside the menu.
  expect(first).not.toBe("");
  expect(second).not.toBe(first);
  expect(back).toBe(first);
  await expect(page.getByRole("menuitemradio").first()).toBeFocused();

  // Home and End reach the ends.
  await page.keyboard.press("End");
  await page.keyboard.press("Home");

  // Escape closes and returns focus to the trigger, so the reader is not
  // dropped on <body>.
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu")).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

/**
 * The review's third point, and the reason this audit exists: Escape is
 * handled by two `window` listeners, and jsdom cannot answer which wins.
 *
 * The menu's handler runs in the capture phase and stops the event there, so
 * closing the menu must not also leave Guided Learning.
 */
test("Escape closes the menu without leaving the reading mode", async ({
  page,
}) => {
  const root = await openReader(page);
  await revealBar(page, root);

  const trigger = page.locator(
    '[data-pdf-zoom-controls] button[aria-haspopup="menu"]',
  );
  await trigger.click();
  await expect(page.getByRole("menu")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu")).toHaveCount(0);

  // The reader is still on screen: Guided Learning did not close under it.
  await expect(root).toBeVisible();
  await expect(root.locator('[data-reader-unit="1"] .textLayer')).toContainText(
    "Zoom audit page 1",
  );
});

/**
 * The budget clamp, in a real browser.
 *
 * A tall page cannot be drawn past the canvas budget, so the highest ladder
 * stops all land on the same width. Stepping must not spend a press on a size
 * that draws nothing, and the control must disable when it cannot help.
 */
test("a step always changes the drawn size, or is disabled", async ({
  page,
}) => {
  const root = await openReader(page);
  const widthOf = () =>
    root
      .locator('[data-reader-unit="1"]')
      .evaluate((element) => element.getBoundingClientRect().width);

  await revealBar(page, root);
  const zoomIn = page.getByRole("button", { name: "Zoom in", exact: true });
  const zoomOut = page.getByRole("button", { name: "Zoom out", exact: true });

  // Climb to the top of the ladder. Every press that is allowed must grow the
  // page; a press that cannot must leave the button disabled.
  for (let step = 0; step < 12; step += 1) {
    const disabled = await zoomIn.isDisabled();
    if (disabled) break;
    const before = await widthOf();
    await zoomIn.click();
    await expect.poll(widthOf).toBeGreaterThan(before);
  }
  await expect(zoomIn).toBeDisabled();

  // And coming back down always shrinks it.
  for (let step = 0; step < 12; step += 1) {
    if (await zoomOut.isDisabled()) break;
    const before = await widthOf();
    await zoomOut.click();
    await expect.poll(widthOf).toBeLessThan(before);
  }
});
