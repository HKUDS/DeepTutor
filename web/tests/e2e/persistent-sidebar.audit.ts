import { expect, test } from "@playwright/test";
import { sourceModuleInventory } from "./fixtures/modules";

for (const width of [1440, 390]) {
  test(`Chat → Space → Chat preserves the sidebar at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("**/api/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/modules") return route.fulfill({ json: sourceModuleInventory });
      if (path === "/api/auth/status") return route.fulfill({ json: { enabled: false, authenticated: true } });
      if (path === "/api/sessions") return route.fulfill({ json: { sessions: [] } });
      if (path === "/api/settings/ui") return route.fulfill({ json: { ui: { language: "en" } } });
      return route.fulfill({ status: 404, json: {} });
    });
    await page.goto("/chat");
    const sidebar = page.locator("aside.dt-product-sidebar");
    const toggle = page.getByRole("button", { name: "Open navigation" });
    const mobile = width < 768;
    if (mobile) await toggle.click();
    await sidebar.locator("#category-resources").click();
    const original = await sidebar.elementHandle();
    await sidebar.locator('a[href="/space"]').click();
    await expect(page).toHaveURL(url => url.pathname === "/space");
    if (mobile) {
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await toggle.click();
    }
    await expect(sidebar.locator("#category-resources")).toBeVisible();
    expect(await sidebar.evaluate((current, first) => current === first, original)).toBe(true);
    await testInfo.attach("resources-sidebar", { body: await page.screenshot(), contentType: "image/png" });
    await sidebar.locator("a.dt-new-conversation").click();
    await expect(page).toHaveURL(url => url.pathname === "/chat");
    await expect(sidebar).toHaveCount(1);
    expect(await sidebar.evaluate((current, first) => current === first, original)).toBe(true);
    if (mobile) await expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
}
