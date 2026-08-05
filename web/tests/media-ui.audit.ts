import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

// Deterministic UI audit fixture for the MED-03 media cards at the approved
// desktop (1440px) and mobile (390px) viewports (§13.6).  The fixture renders
// every job state plus the generated-media manager with real image bytes, so
// layout (no overlap / no horizontal overflow) and real-image rendering can be
// asserted without a live provider or a running app.

// Playwright resolves the config from the web root, so cwd == web/.
const FIXTURE_PATH = path.resolve(process.cwd(), "tests", "fixtures", "media-cards.html");

const RESULTS_DIR = path.resolve(process.cwd(), "test-results", "media");

interface Rect {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

function overlaps(a: Rect, b: Rect): boolean {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

async function assertNoOverlap(page: Page, selector: string): Promise<void> {
  const rects = await page.$$eval(selector, (els) =>
    els.map((el) => {
      const r = el.getBoundingClientRect();
      return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
    }),
  );
  for (let i = 0; i < rects.length; i += 1) {
    for (let j = i + 1; j < rects.length; j += 1) {
      expect(
        overlaps(rects[i], rects[j]),
        `Overlapping elements at ${selector} index ${i}/${j}`,
      ).toBe(false);
    }
  }
}

async function assertRealImageRenders(page: Page): Promise<void> {
  const broken = await page.$$eval("img.real-image", (imgs) =>
    imgs.filter((img) => {
      const el = img as HTMLImageElement;
      return !(el.complete && el.naturalWidth > 0 && el.naturalHeight > 0);
    }).length,
  );
  expect(broken, `Found ${broken} non-rendering image(s)`).toBe(0);
}

async function runViewportChecks(
  page: Page,
  width: number,
  height: number,
  name: string,
): Promise<void> {
  await page.setViewportSize({ width, height });
  await page.goto(`file://${FIXTURE_PATH}`);
  await page.waitForSelector("[data-media-job-card]");

  // No horizontal overflow / no cards clipped by the viewport.
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth, `${name}: document overflows viewport width`).toBeLessThanOrEqual(width + 1);

  // Job cards must not overlap each other; artifact cards must not overlap.
  await assertNoOverlap(page, "[data-media-job-card]");
  await assertNoOverlap(page, "[data-artifact-id]");

  // Every status is present in the fixture.
  const statuses = await page.$$eval("[data-media-job-card]", (els) =>
    els.map((el) => el.getAttribute("data-status")),
  );
  for (const status of [
    "queued",
    "running",
    "polling",
    "validating",
    "saving",
    "succeeded",
    "failed",
    "cancel_requested",
    "cancelled",
    "cancelled_unconfirmed",
    "timed_out",
    "unknown",
  ]) {
    expect(statuses, `${name}: missing status ${status}`).toContain(status);
  }

  // Real image bytes render (never a blank placeholder).
  await assertRealImageRenders(page);

  // Non-color status labels are present for every card (accessibility).
  const badges = await page.$$eval(".status-badge", (els) =>
    els.filter((el) => (el.textContent ?? "").trim().length === 0).length,
  );
  expect(badges, `${name}: status badges missing text`).toBe(0);

  mkdirSync(RESULTS_DIR, { recursive: true });
  await page.screenshot({
    path: path.join(RESULTS_DIR, `${name}-${width}x${height}.png`),
    fullPage: true,
  });
}

test.describe("MED-03 media cards responsive audit", () => {
  test("desktop 1440px: no overlap/overflow, real image renders", async ({ page }) => {
    await runViewportChecks(page, 1440, 900, "media-desktop");
  });

  test("mobile 390px: no overlap/overflow, real image renders", async ({ page }) => {
    await runViewportChecks(page, 390, 844, "media-mobile");
  });
});
