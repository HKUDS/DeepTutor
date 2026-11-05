import { sourceModuleInventory } from "./fixtures/modules";
import { emptyLearningIndex } from "./fixtures/learning-index";
import { expect, test, type Page } from "@playwright/test";
import { jsPDF } from "jspdf";
import { emptyTaskBoard } from "./fixtures/task-board";

/**
 * The reader's annotation experience, driven through a real Chromium.
 *
 * The unit tests cover the components' logic; this covers what only a browser
 * can answer — that the zoom bar, the note editor, the palette, the batch bar
 * and the mobile sheet actually appear, respond to pointer events, and stay
 * laid out at a real viewport size. jsdom has no layout, so none of that is
 * provable there.
 */

const MATERIAL_ID = "aaaaaaaaaaaaaaa1";
const WORKSPACE_ID = "annotation-audit-workspace";
const SESSION_ID = "annotation-audit-session";
const PAGE_COUNT = 12;

function pdfFixture(): Buffer {
  const document = new jsPDF({ format: "a4" });
  for (let locator = 1; locator <= PAGE_COUNT; locator += 1) {
    if (locator > 1) document.addPage();
    document.text(`Annotation audit page ${locator}`, 20, 30);
  }
  return Buffer.from(document.output("arraybuffer"));
}

const pdfBytes = pdfFixture();

const material = {
  material_id: MATERIAL_ID,
  content_id: MATERIAL_ID,
  filename: "annotation-audit.pdf",
  title: "Annotation audit",
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

/** Two marks already on the document: one yellow highlight, one green note. */
const SEED_MARKS = [
  {
    annotation_id: "m-yellow",
    locator: 2,
    material_revision: 1,
    kind: "highlight",
    color: "yellow",
    quote: "Annotation audit page 2",
    note: "first thought",
    rects: [[0.05, 0.05, 0.6, 0.07]],
    source_anchor: "",
    selectors: [],
    resolution: "resolved",
    author: "user",
    created_at: 10,
    updated_at: 10,
  },
  {
    annotation_id: "m-green",
    locator: 5,
    material_revision: 1,
    kind: "highlight",
    color: "green",
    quote: "Annotation audit page 5",
    note: "second thought",
    rects: [[0.05, 0.05, 0.6, 0.07]],
    source_anchor: "",
    selectors: [],
    resolution: "resolved",
    author: "user",
    created_at: 20,
    updated_at: 20,
  },
];

let currentMarks = SEED_MARKS;

test.beforeEach(async ({ context }) => {
  currentMarks = SEED_MARKS;
  await context.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (payload: unknown) => route.fulfill({ json: payload });
    if (path === "/api/modules") return json(sourceModuleInventory);
    if (path === "/api/task-board") return json(emptyTaskBoard);
    if (path === "/api/auth/status") return json({ enabled: false, authenticated: true });
    if (path === "/api/settings/ui") return json({ language: "en" });
    if (path === "/api/dashboard/suggestions") return json({ suggestions: [], stale: false });
    if (path === "/api/dashboard/learning-index") return json(emptyLearningIndex);
    if (path === "/api/partners" || path === "/api/partner-groups") return json([]);
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
          tabs: [{ material, tab_order: 0, pinned: false, opened: true, added_at: 1 }],
        },
        sessions: [],
      });
    }
    if (path === `/api/reading/workspaces/${WORKSPACE_ID}/sessions`) {
      return json({ sessions: [] });
    }
    if (path === "/api/reading/supported-formats") {
      return json({ extensions: [".pdf"], max_bytes: 1048576, raw_view_extensions: [".pdf"] });
    }
    if (path === "/api/reading/extensions") return json([]);
    if (path.endsWith("/annotations")) {
      if (route.request().method() === "PUT") {
        const body = JSON.parse(route.request().postData() ?? "{}");
        const updated = {
          ...(currentMarks.find((row) => row.annotation_id === body.annotation_id) ??
            currentMarks[0]),
          ...body,
        };
        currentMarks = currentMarks.map((row) =>
          row.annotation_id === updated.annotation_id ? updated : row,
        );
        return json(updated);
      }
      return json(currentMarks);
    }
    if (path === "/api/reading/materials") return json([material]);
    if (path === `/api/reading/materials/${MATERIAL_ID}`) return json(material);
    if (path === `/api/reading/materials/${MATERIAL_ID}/raw`) {
      return route.fulfill({ contentType: "application/pdf", body: pdfBytes });
    }
    if (path.endsWith("/position")) return json({ locator: 1, source_anchor: "" });
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
    .filter({ has: page.locator('[data-reader-unit="2"]') });
  await expect(root).toBeVisible({ timeout: 20_000 });
  await expect(root.locator('[data-reader-unit="1"] .textLayer')).toContainText(
    "Annotation audit page 1",
    { timeout: 20_000 },
  );
  return root;
}

test("the zoom bar resizes a page in a real browser", async ({ page }) => {
  const root = await openReader(page);
  const firstPage = root.locator('[data-reader-unit="1"]');
  const before = await firstPage.evaluate(
    (element) => element.getBoundingClientRect().width,
  );

  // The bar reveals on hover near the bottom edge, as designed.
  await root.hover({ position: { x: 200, y: 400 } });
  await page.mouse.move(700, 860);
  const zoomIn = page.getByRole("button", { name: "Zoom in", exact: true });
  await expect(zoomIn).toBeVisible();

  await zoomIn.click();
  await expect
    .poll(() =>
      firstPage.evaluate((element) => element.getBoundingClientRect().width),
    )
    .toBeGreaterThan(before);

  // Reset returns to fit.
  await page.getByRole("button", { name: "Reset zoom", exact: true }).click();
  await expect
    .poll(() =>
      firstPage.evaluate((element) => element.getBoundingClientRect().width),
    )
    .toBe(before);
});

/**
 * Open the docked annotation panel.
 *
 * The panel lives in the contents navigator's "Annotations" tab, so the
 * navigator has to be expanded first — the same sequence the W3C annotation
 * audit uses.
 */
async function openAnnotationPanel(page: Page) {
  await page.getByRole("button", { name: "Expand contents", exact: true }).click();
  await page.getByRole("tab", { name: /Annotations/ }).click();
}

test("a mark's note can be edited in place", async ({ page }) => {
  await openReader(page);
  await openAnnotationPanel(page);

  const panel = page
    .locator("aside")
    .filter({ has: page.getByTestId("annotation-sort") });
  await expect(panel).toBeVisible();
  // The per-row actions sit in a hover-revealed wrapper, so the DOM click is
  // what a pointer on the hovered row produces.
  await panel.locator('button[aria-label="Edit note"]').first().click({ force: true });
  // The row re-renders with the editor in place of the note text; wait for the
  // commit rather than sampling the DOM immediately.
  const field = panel.getByTestId("annotation-note-input");
  await expect(field).toBeVisible();
  await expect(field).toHaveValue("first thought");
  await field.fill("revised in a real browser");
  await panel.getByTestId("annotation-note-save").click();

  // The editor closes and the list shows the new text.
  await expect(field).toHaveCount(0);
  await expect(panel.getByText("revised in a real browser")).toBeVisible();
});

test("the palette recolours a mark, and the filter narrows to it", async ({
  page,
}) => {
  await openReader(page);
  await openAnnotationPanel(page);
  const panel = page
    .locator("aside")
    .filter({ has: page.getByTestId("annotation-sort") });

  // Two colours are in play, so the filter row is offered.
  const filter = page.getByRole("group", { name: "Filter by colour" });
  await expect(filter).toBeVisible();
  await filter.getByRole("button", { name: "Green" }).click();
  await expect(panel.getByText("second thought")).toBeVisible();
  await expect(panel.getByText("first thought")).toHaveCount(0);

  // Recolour for real: the first mark is yellow, press Green on its own row
  // and the PUT must carry the new colour. The filter above is cleared first
  // so the row is on screen.
  await filter.getByRole("button", { name: "All colours" }).click();
  const row = panel.getByRole("listitem").filter({ hasText: "first thought" });
  await expect(row).toBeVisible();
  const put = page.waitForRequest(
    (request) =>
      request.method() === "PUT" &&
      request.url().includes("/annotations") &&
      (request.postData() ?? "").includes("green"),
  );
  await row.getByLabel("Green").click();
  await put;
  // The swatch reports the new colour as pressed, so the change landed in UI.
  await expect(row.getByLabel("Green")).toHaveAttribute("aria-pressed", "true");
});

test("selection mode offers a batch bar and closes again", async ({ page }) => {
  await openReader(page);
  await openAnnotationPanel(page);

  await page.getByTestId("annotation-select-toggle").click();
  await expect(page.getByTestId("annotation-bulk-delete")).toBeVisible();
  await expect(page.getByTestId("annotation-bulk-copy")).toBeVisible();
  // A checkbox per visible row, and the per-row actions step aside.
  await expect(page.locator('input[type="checkbox"]')).toHaveCount(2);

  await page.getByTestId("annotation-select-toggle").click();
  await expect(page.getByTestId("annotation-bulk-delete")).toHaveCount(0);
});

test("the sort control cycles through its three orders", async ({ page }) => {
  await openReader(page);
  await openAnnotationPanel(page);

  const sort = page.getByTestId("annotation-sort");
  await expect(sort).toHaveAttribute("aria-label", "Document order");
  await sort.click();
  await expect(sort).toHaveAttribute("aria-label", "Newest first");
  await sort.click();
  await expect(sort).toHaveAttribute("aria-label", "Oldest first");
});

test("the marks are reachable on a phone viewport", async ({ page }) => {
  // In a workspace the navigator is a 300px drawer below `lg`, and the marks
  // live in its "Annotations" tab — so a phone reaches them through the
  // drawer, not through a docked column.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/learning/reading/${WORKSPACE_ID}/sessions/${SESSION_ID}`, {
    waitUntil: "domcontentloaded",
  });
  await expect(
    page.locator('[data-reader-unit="1"] .textLayer'),
  ).toContainText("Annotation audit page 1", { timeout: 20_000 });

  // Open the drawer, then the marks tab.
  await page.getByRole("button", { name: "Expand contents", exact: true }).click();
  await page.getByRole("tab", { name: /Annotations/ }).click();

  const marks = page
    .locator("aside")
    .filter({ has: page.getByTestId("annotation-sort") });
  await expect(marks.getByText("first thought")).toBeVisible();
  // The reading page is still usable behind the drawer.
  await expect(
    page.locator('[data-reader-unit="1"] .textLayer'),
  ).toContainText("Annotation audit page 1");
});

/**
 * Two real tabs on one document.
 *
 * The unit tests dispatch a synthetic `StorageEvent`, which proves the
 * listener logic but not that a browser actually fires one across tabs. Only
 * two real pages can answer that.
 */
test("a mark saved in one tab reaches the other", async ({ page, context }) => {
  const other = await context.newPage();
  for (const target of [page, other]) {
    await target.setViewportSize({ width: 1440, height: 900 });
    await target.goto(
      `/learning/reading/${WORKSPACE_ID}/sessions/${SESSION_ID}`,
      { waitUntil: "domcontentloaded" },
    );
  }
  // Wait until both tabs have the document and its marks.
  for (const target of [page, other]) {
    await expect(
      target.locator('[data-reader-unit="1"] .textLayer'),
    ).toContainText("Annotation audit page 1", { timeout: 20_000 });
  }

  // The second tab starts with the seeded marks and no extras.
  await openAnnotationPanel(other);
  const otherPanel = other
    .locator("aside")
    .filter({ has: other.getByTestId("annotation-sort") });
  await expect(otherPanel.getByText("first thought")).toBeVisible();

  // Editing in the first tab must reach the second through the browser's own
  // storage event, not a mocked one.
  await openAnnotationPanel(page);
  const panel = page
    .locator("aside")
    .filter({ has: page.getByTestId("annotation-sort") });
  await panel
    .locator('button[aria-label="Edit note"]')
    .first()
    .click({ force: true });
  const field = panel.getByTestId("annotation-note-input");
  await expect(field).toBeVisible();
  await field.fill("saved in the first tab");
  await panel.getByTestId("annotation-note-save").click();
  await expect(panel.getByText("saved in the first tab")).toBeVisible();


  // The other tab picks it up without being reloaded.
  await expect(otherPanel.getByText("saved in the first tab")).toBeVisible({
    timeout: 10_000,
  });
  await other.close();
});
