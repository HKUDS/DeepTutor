import { expect, test } from "@playwright/test";

const PAIRING_ID = "be0038de1f88";
const READER_URL = `/immersive-reading?pairing=${PAIRING_ID}`;
test.setTimeout(30_000);

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/auth/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        enabled: false,
        authenticated: true,
        user_id: "audit",
        username: "audit",
        role: "admin",
        is_admin: true,
      }),
    }),
  );
  await page.addInitScript(() => {
    window.localStorage.setItem("deeptutor.bilingual-reader.mode", "dual");
    window.sessionStorage.removeItem("deeptutor.bilingual-reader.shortcut-hint-shown");
  });
});

test("iPad-width dual pane follows the reader container and supports temporary independent scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 1200, height: 900 });
  await page.goto(READER_URL);
  const surface = page.locator("[data-reader-surface]");
  await expect(surface).toBeVisible({ timeout: 20_000 });
  console.log("reader width", await surface.evaluate((node) => node.clientWidth));
  const english = page.getByLabel("English pane");
  const chinese = page.getByLabel("Chinese pane");
  await expect(english).toBeVisible({ timeout: 20_000 });
  await expect(chinese).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("button", { name: /Linked scrolling|联动滚动/i })).toBeVisible();

  const englishBefore = await english.evaluate((node) => node.scrollTop);
  const drag = await chinese.boundingBox();
  if (!drag) throw new Error("Chinese pane was not measurable");
  await page.mouse.move(drag.x + drag.width / 2, drag.y + 180);
  await page.mouse.down();
  await page.mouse.move(drag.x + drag.width / 2 + 18, drag.y + 210, { steps: 4 });
  await page.mouse.up();
  await expect
    .poll(() => english.evaluate((node) => node.scrollTop))
    .toBe(englishBefore);
  await expect(page.getByRole("button", { name: /Independent scrolling|独立滚动/i })).toBeVisible();

  await chinese.locator('[data-group-index="2"]').click();
  await expect(page.getByRole("button", { name: /Linked scrolling|联动滚动/i })).toBeVisible();
  await expect
    .poll(async () => {
      const positions = await page.evaluate(() => {
        const englishPane = document.querySelector('[aria-label="English pane"]');
        const chinesePane = document.querySelector('[aria-label="Chinese pane"]');
        const englishGroup = englishPane?.querySelector('[data-group-index="2"]');
        const chineseGroup = chinesePane?.querySelector('[data-group-index="2"]');
        if (!(englishPane instanceof HTMLElement) || !(chinesePane instanceof HTMLElement)) return null;
        if (!(englishGroup instanceof HTMLElement) || !(chineseGroup instanceof HTMLElement)) return null;
        return {
          english: englishGroup.offsetTop - englishPane.scrollTop,
          chinese: chineseGroup.offsetTop - chinesePane.scrollTop,
        };
      });
      return positions ? Math.abs(positions.english - positions.chinese) : Number.NaN;
    })
    .toBeLessThan(2);

  await page.setViewportSize({ width: 959, height: 900 });
  await expect(english).toBeHidden();
  await expect(chinese).toBeHidden();
  await expect(page.getByRole("button", { name: "Dual pane" })).toBeDisabled();
});

test("first reader shortcut shows a transient action hint", async ({ page }) => {
  page.on("response", (response) => {
    if (response.url().includes("/api/")) {
      console.log(`${response.status()} ${response.url()}`);
    }
  });
  page.on("pageerror", (error) => console.error(error));
  await page.setViewportSize({ width: 1200, height: 900 });
  await page.goto(READER_URL);
  await expect(page.getByLabel("English pane")).toBeVisible({ timeout: 20_000 });

  await page.keyboard.press("j");
  const hint = page.getByRole("status");
  await expect(hint).toContainText(/Next paragraph|下一段落/);
  await expect(hint).toBeHidden({ timeout: 4000 });
});
