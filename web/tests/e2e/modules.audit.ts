import { expect, test } from "@playwright/test";

import { sourceModuleInventory } from "./fixtures/modules";

for (const unavailableInventory of [false, true]) {
  test(`module gate blocks disabled reading${unavailableInventory ? " after inventory retry" : ""}`, async ({ page }) => {
    let failInventory = unavailableInventory;
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/modules") {
        if (failInventory) return route.fulfill({ status: 503, json: {} });
        return route.fulfill({ json: {
          modules: sourceModuleInventory.modules.map(module => module.id === "reading"
            ? { ...module, enabled: false }
            : module),
        } });
      }
      if (path === "/api/auth/status") {
        return route.fulfill({ json: { enabled: false, authenticated: true, is_admin: true } });
      }
      if (path === "/api/settings/ui") return route.fulfill({ json: { language: "en" } });
      return route.fulfill({ status: 404, json: {} });
    });
    await page.goto("/learning/reading", { waitUntil: "domcontentloaded" });
    if (unavailableInventory) {
      await expect(page.getByRole("main").getByRole("button", { name: "Retry", exact: true })).toBeVisible();
      await expect(page.getByText("This module is not installed or is disabled.", { exact: true })).toHaveCount(0);
      failInventory = false;
      await page.getByRole("main").getByRole("button", { name: "Retry", exact: true }).click();
    }
    await expect(page.getByText("This module is not installed or is disabled.", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Immersive Reading", exact: true })).toHaveCount(0);
  });
}
