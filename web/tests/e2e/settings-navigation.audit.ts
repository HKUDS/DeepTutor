import { expect, test } from "@playwright/test";

test.describe("Settings navigation", () => {
  test("keeps scrolling inside the settings pane", async ({ page }) => {
    await page.goto("/settings");

    const settingsScroll = page.locator("[data-settings-scroll]");
    await expect(settingsScroll).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);

    const aboutLink = page.locator('a[data-tour="tour-nav-about"]');
    await aboutLink.click();
    await expect(page).toHaveURL(/\/settings#about$/);
    await expect
      .poll(() => settingsScroll.evaluate((element) => element.scrollTop))
      .toBeGreaterThan(0);

    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  });

  test("keeps deep-link scrolling inside the settings pane", async ({
    page,
  }) => {
    await page.goto("/settings#about");

    const settingsScroll = page.locator("[data-settings-scroll]");
    await expect(settingsScroll).toBeVisible();
    await expect(page).toHaveURL(/\/settings#about$/);
    await expect
      .poll(() => settingsScroll.evaluate((element) => element.scrollTop))
      .toBeGreaterThan(0);

    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  });
});
