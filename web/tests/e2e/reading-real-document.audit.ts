import { sourceModuleInventory } from "./fixtures/modules";
import { emptyLearningIndex } from "./fixtures/learning-index";
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { emptyTaskBoard } from "./fixtures/task-board";

const MATERIAL_ID = "eeeeeeeeeeeeeee4";
const WORKSPACE_ID = "real-doc-workspace";
const SESSION_ID = "real-doc-session";
const PAGE_COUNT = 1;

// The repository's own fixture, not a generated one: it has a heading, a
// paragraph, an inline formula, a table and an image on one page, which is the
// layout a reader actually meets.
const pdfBytes = readFileSync(
  join(__dirname, "../../../tests/fixtures/lightrag_bridge/original.pdf"),
);
const material = {
  material_id: MATERIAL_ID,
  content_id: MATERIAL_ID,
  filename: "original.pdf",
  title: "Real document fixture",
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

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/modules") return route.fulfill({ json: sourceModuleInventory });
    const json = (payload: unknown) => route.fulfill({ json: payload });
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
    if (path === "/api/dashboard/learning-index") return json(emptyLearningIndex);
    if (path === "/api/partners" || path === "/api/partner-groups")
      return json([]);
    if (path === "/api/sessions") return json({ sessions: [] });
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
            {
              material,
              tab_order: 0,
              pinned: false,
              opened: true,
              added_at: 1,
            },
          ],
        },
        sessions: [],
      });
    }
    if (path === `/api/reading/workspaces/${WORKSPACE_ID}/sessions`) {
      return json({ sessions: [] });
    }
    if (path === "/api/reading/supported-formats") {
      return json({
        extensions: [".pdf"],
        max_bytes: 1024 * 1024,
        raw_view_extensions: [".pdf"],
      });
    }
    if (path === "/api/reading/extensions") return json([]);
    if (path.endsWith("/annotations")) {
      if (route.request().method() === "PUT") {
        const body = JSON.parse(route.request().postData() ?? "{}");
        return json({
          ...body,
          annotation_id: body.annotation_id ?? "mark-1",
          material_revision: 1,
          color: body.color ?? "yellow",
          rects: body.rects ?? [],
          selectors: body.selectors ?? [],
          resolution: "resolved",
          author: "user",
          created_at: 1,
          updated_at: 2,
        });
      }
      return json([]);
    }
    if (path === "/api/reading/materials") return json([material]);
    if (path === `/api/reading/materials/${MATERIAL_ID}`) return json(material);
    if (path === `/api/reading/materials/${MATERIAL_ID}/raw`) {
      return route.fulfill({ contentType: "application/pdf", body: pdfBytes });
    }
    if (path.endsWith("/position"))
      return json({ locator: 1, source_anchor: "" });
    const unit = /\/units\/(\d+)$/.exec(path);
    if (unit) {
      return json({
        locator: Number(unit[1]),
        unit: "page",
        text: `Resize regression page ${unit[1]}`,
      });
    }
    return json({});
  });
});

/**
 * The whole page's box, not the strip the reader happens to show.
 *
 * A page can be drawn wider than the strip it fills and shifted left, so its
 * own margins are trimmed ("fit the text"). Measurements against the strip
 * would then change with the mode; against the page they do not, because the
 * glyphs and the ink they label are the same words at every size.
 */
function fullPageBox(element: HTMLElement) {
  const box = element.getBoundingClientRect();
  const width = Number(element.dataset.pageWidth ?? box.width);
  const offsetX = Number(element.dataset.pageOffsetX ?? 0);
  return {
    left: box.left - offsetX,
    top: box.top,
    width,
    height: box.height,
  };
}

/**
 * Where a run of text actually sits inside the page, as a fraction of the page
 * box, next to where pdf.js's own text layer puts it.
 *
 * Comparing the canvas box with the text-layer box proves nothing: both are
 * pinned to the same container (`h-full w-full` and `inset: 0`), so they agree
 * at every zoom even if every glyph is in the wrong place. What has to line up
 * is a span's position against the page — that is what makes a selection
 * cover the words it looks like it covers.
 */
async function glyphGeometry(page: Page) {
  return page.locator('[data-reader-unit="1"]').evaluate((pageRoot) => {
    // Inlined rather than calling the helper above: this callback runs in the
    // page, where a Node-side function reference does not exist.
    const strip = pageRoot.getBoundingClientRect();
    const pageBox = {
      left: strip.left - Number(pageRoot.dataset.pageOffsetX ?? 0),
      top: strip.top,
      width: Number(pageRoot.dataset.pageWidth ?? strip.width),
      height: strip.height,
    };
    const spans = [...pageRoot.querySelectorAll<HTMLElement>(".textLayer span")];
    if (spans.length === 0) throw new Error("text layer has no spans");
    // The first span is the start of the fixture's heading, which sits in the
    // top-left area of the page.
    const span = spans[0].getBoundingClientRect();
    return {
      pageWidth: pageBox.width,
      pageHeight: pageBox.height,
      left: (span.left - pageBox.left) / pageBox.width,
      top: (span.top - pageBox.top) / pageBox.height,
      width: span.width / pageBox.width,
      height: span.height / pageBox.height,
    };
  });
}

test("a real document keeps its canvas and text layer registered at every zoom", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/learning/reading/${WORKSPACE_ID}/sessions/${SESSION_ID}`, {
    waitUntil: "domcontentloaded",
  });
  const root = page
    .locator(".dt-reader-scroll")
    .filter({ has: page.locator('[data-reader-unit="1"]') });
  await expect(root).toBeVisible({ timeout: 20_000 });
  await expect(root.locator('[data-reader-unit="1"] .textLayer')).toContainText(
    "DeepTutor LightRAG Bridge Fixture",
    { timeout: 20_000 },
  );

  // The heading's first span sits near the page's top-left. Its position, as a
  // fraction of the page, must not move when the page is zoomed: the glyph and
  // the ink it labels are the same words at every scale.
  const atFit = await glyphGeometry(page);
  const check = async (label: string) => {
    const geometry = await glyphGeometry(page);
    // The span's *position* as a fraction of the page must not move: the words
    // it covers are the same words at every scale.
    expect(geometry.left, `${label}: span left`).toBeCloseTo(atFit.left, 2);
    expect(geometry.top, `${label}: span top`).toBeCloseTo(atFit.top, 2);
  };

  await check("at fit");

  const firstPage = root.locator('[data-reader-unit="1"]');
  const fitWidth = await firstPage.evaluate(
    (element) => element.getBoundingClientRect().width,
  );

  await root.hover({ position: { x: 200, y: 400 } });
  await page.mouse.move(700, 860);
  const zoomIn = page.getByRole("button", { name: "Zoom in", exact: true });
  await expect(zoomIn).toBeVisible();
  await zoomIn.click();
  await expect
    .poll(() =>
      firstPage.evaluate((element) => element.getBoundingClientRect().width),
    )
    .toBeGreaterThan(fitWidth);
  await check("zoomed in");

  await page.getByRole("button", { name: "Zoom out", exact: true }).click();
  await check("zoomed out");

  await page.getByRole("button", { name: "Reset zoom", exact: true }).click();
  await expect
    .poll(() =>
      firstPage.evaluate((element) => element.getBoundingClientRect().width),
    )
    .toBe(fitWidth);
  await check("reset");

  // The proof that the text layer sits on the ink is behavioural, not
  // geometric: dragging across a span must select that span's own words. A
  // layer that drifted would select the neighbouring text instead.
  const span = root.locator('[data-reader-unit="1"] .textLayer span').first();
  const box = await span.boundingBox();
  if (!box) throw new Error("first span has no box");
  await page.mouse.move(box.x + 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width - 2, box.y + box.height / 2, { steps: 6 });
  await page.mouse.up();
  const selected = await page.evaluate(() => window.getSelection()?.toString() ?? "");
  expect(selected.trim().length).toBeGreaterThan(0);
  // The selection must be text the document actually contains.
  expect(selected).toMatch(/DeepTutor|LightRAG|Fixture/i);
});

/**
 * A selection made through the real text layer has to produce a mark that
 * lands on the words it was drawn over. The text layer and the annotation
 * overlay are positioned independently — one by pdf.js's own transforms, the
 * other by stored percentages of the page box — so "the mark is on the page"
 * is not the same claim as "the mark is on the words".
 */
test("a real selection produces a mark on the words it covered", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/learning/reading/${WORKSPACE_ID}/sessions/${SESSION_ID}`, {
    waitUntil: "domcontentloaded",
  });
  const root = page
    .locator(".dt-reader-scroll")
    .filter({ has: page.locator('[data-reader-unit="1"]') });
  await expect(root).toBeVisible({ timeout: 20_000 });
  const firstPage = root.locator('[data-reader-unit="1"]');
  const textLayer = firstPage.locator(".textLayer");
  await expect(textLayer).toContainText("DeepTutor LightRAG Bridge Fixture", {
    timeout: 20_000,
  });

  // Select the heading through the real text layer, the way a reader would.
  const heading = textLayer.getByText("DeepTutor LightRAG Bridge Fixture", {
    exact: false,
  });
  await expect(heading.first()).toBeVisible();
  const box = await heading.first().boundingBox();
  if (!box) throw new Error("heading has no box");
  await page.mouse.move(box.x + 3, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width - 3, box.y + box.height / 2, {
    steps: 10,
  });
  await page.mouse.up();

  // The toolbar appears over the selection; save the mark from it.
  const highlightButton = page.getByRole("button", {
    name: "Highlight",
    exact: true,
  });
  await expect(highlightButton).toBeVisible({ timeout: 10_000 });
  await highlightButton.click();

  // A mark is drawn and labelled with the text it covers, which is what
  // assistive tech reads.
  const mark = firstPage
    .getByLabel("DeepTutor LightRAG Bridge Fixture", { exact: false })
    .first();
  await expect(mark).toBeVisible({ timeout: 10_000 });
  // A mark is positioned as percentages of the page box, so until the page has
  // been laid out that box is zero-sized and the mark has no measurable
  // rectangle — which happens when the suite runs in parallel.
  let markBox = await mark.boundingBox();
  await expect
    .poll(
      async () => {
        markBox = await mark.boundingBox();
        return markBox !== null && markBox.width > 0 && markBox.height > 0;
      },
      { timeout: 10_000, message: "mark never gained a measurable box" },
    )
    .toBe(true);
  if (!markBox) throw new Error("mark has no box");

  // It sits on the heading: same row band, overlapping horizontally, and
  // inside the page rather than off its edge.
  expect(markBox.width).toBeGreaterThan(40);
  const pageRect = await firstPage.evaluate(fullPageBox);
  expect(markBox.x).toBeGreaterThanOrEqual(pageRect.left - 2);
  expect(markBox.x + markBox.width).toBeLessThanOrEqual(
    pageRect.left + pageRect.width + 2,
  );
  expect(markBox.y).toBeGreaterThanOrEqual(pageRect.top - 2);
  expect(markBox.y + markBox.height).toBeLessThanOrEqual(
    pageRect.top + pageRect.height + 2,
  );
  // The heading is in the top fifth of the page, so a mark on it must be too.
  const relativeTop = (markBox.y - pageRect.top) / pageRect.height;
  expect(relativeTop).toBeLessThan(0.25);

  // And it has to cover the words it was made from, not merely sit somewhere
  // on the page: the mark's band must contain the heading span's centre, and
  // the two must overlap horizontally.
  const headingBox = await firstPage
    .locator(".textLayer span")
    .first()
    .boundingBox();
  if (!headingBox) throw new Error("heading span has no box");
  const overlapX =
    Math.min(markBox.x + markBox.width, headingBox.x + headingBox.width) -
    Math.max(markBox.x, headingBox.x);
  expect(overlapX).toBeGreaterThan(0);
  const headingCentreY = headingBox.y + headingBox.height / 2;
  expect(headingCentreY).toBeGreaterThanOrEqual(markBox.y - 2);
  expect(headingCentreY).toBeLessThanOrEqual(markBox.y + markBox.height + 2);
});
