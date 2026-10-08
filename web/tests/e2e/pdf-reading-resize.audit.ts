import { expect, test, type Locator } from "@playwright/test";
import { jsPDF } from "jspdf";

const MATERIAL_ID = "dddddddddddddddd";
const WORKSPACE_ID = "pdf-resize-workspace";
const SESSION_ID = "pdf-resize-session";
const PAGE_COUNT = 160;

function pdfFixture(): Buffer {
  const document = new jsPDF({ format: "a4" });
  for (let locator = 1; locator <= PAGE_COUNT; locator += 1) {
    if (locator > 1) document.addPage();
    document.text(`Resize regression page ${locator}`, 20, 30);
  }
  return Buffer.from(document.output("arraybuffer"));
}

const pdfBytes = pdfFixture();
const material = {
  material_id: MATERIAL_ID,
  content_id: MATERIAL_ID,
  filename: "resize-regression.pdf",
  title: "PDF resize regression",
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
    const json = (payload: unknown) => route.fulfill({ json: payload });
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
    if (path === "/api/reading/extensions" || path.endsWith("/annotations"))
      return json([]);
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

async function withinPage(root: Locator, locator: number): Promise<number> {
  return root.evaluate((element, pageNumber) => {
    const page = element.querySelector<HTMLElement>(
      `[data-reader-unit="${pageNumber}"]`,
    )!;
    const pageRect = page.getBoundingClientRect();
    return (
      (element.getBoundingClientRect().top - pageRect.top) / pageRect.height
    );
  }, locator);
}

test("keeps the reading point when annotations toggle and the window resizes", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/learning/reading/${WORKSPACE_ID}/sessions/${SESSION_ID}`, {
    waitUntil: "domcontentloaded",
  });
  const root = page
    .locator(".dt-reader-scroll")
    .filter({ has: page.locator('[data-reader-unit="99"]') });
  await expect(root).toBeVisible();
  await expect(root.locator('[data-reader-unit="1"] .textLayer')).toContainText(
    "Resize regression page 1",
  );
  await page
    .getByRole("button", { name: "Expand contents", exact: true })
    .click();
  await page.getByRole("tab", { name: "Annotations", exact: true }).click();

  await root.evaluate((element) => {
    const target = element.querySelector<HTMLElement>(
      '[data-reader-unit="99"]',
    )!;
    const rect = target.getBoundingClientRect();
    element.scrollTop +=
      rect.top - element.getBoundingClientRect().top + rect.height * 0.3;
  });
  await expect(
    root.locator('[data-reader-unit="99"] .textLayer'),
  ).toContainText("Resize regression page 99");
  await expect.poll(() => withinPage(root, 99)).toBeCloseTo(0.3, 2);

  for (const control of ["Close contents", "Expand contents"]) {
    const beforeWidth = await root
      .locator('[data-reader-unit="99"]')
      .evaluate((element) => element.getBoundingClientRect().width);
    await page.getByRole("button", { name: control, exact: true }).click();
    await expect
      .poll(() =>
        root
          .locator('[data-reader-unit="99"]')
          .evaluate((element) => element.getBoundingClientRect().width),
      )
      .not.toBe(beforeWidth);
    await expect.poll(() => withinPage(root, 99)).toBeCloseTo(0.3, 2);
  }

  for (const width of [1200, 1600, 1440]) {
    const beforeWidth = await root
      .locator('[data-reader-unit="99"]')
      .evaluate((element) => element.getBoundingClientRect().width);
    await page.setViewportSize({ width, height: 900 });
    await expect
      .poll(() =>
        root
          .locator('[data-reader-unit="99"]')
          .evaluate((element) => element.getBoundingClientRect().width),
      )
      .not.toBe(beforeWidth);
    await expect.poll(() => withinPage(root, 99)).toBeCloseTo(0.3, 2);
  }
  await expect(
    root.locator('[data-reader-unit="99"] .textLayer'),
  ).toContainText("Resize regression page 99");
});
