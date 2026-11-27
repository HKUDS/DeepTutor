import { expect, test } from "@playwright/test";
import { emptyLearningIndex } from "./fixtures/learning-index";
import { sourceModuleInventory } from "./fixtures/modules";

test("return from Browse Invidious to a pending upload by mouse or keyboard", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("deeptutor.ui-layout", "modern");
    localStorage.setItem("deeptutor-language", "en");
  });
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    const fixtures: Record<string, unknown> = {
      "/api/modules": sourceModuleInventory,
      "/api/auth/status": { enabled: false, authenticated: true },
      "/api/settings/ui": { language: "en", ui_layout: "modern" },
      "/api/settings/llm-options": {
        active: { profile_id: "p", model_id: "m" },
        options: [{ profile_id: "p", model_id: "m", model: "model", is_active_default: true }],
      },
      "/api/dashboard/learning-index": emptyLearningIndex,
      "/api/video-learning/invidious/account/status": { connected: false },
      "/api/reading/library/duplicate-check": { matches: [] },
    };
    return route.fulfill({ json: fixtures[path] ?? { items: [] } });
  });

  await page.goto("/learning/reading/materials");
  await page.getByRole("button", { name: "Upload material", exact: true }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name: "pending.pdf", mimeType: "application/pdf", buffer: Buffer.from("pending"),
  });
  const browse = page.getByRole("button", { name: "Browse Invidious" });
  const picker = page.getByRole("dialog", { name: "Browse Invidious" });
  await browse.click();
  await picker.getByRole("button", { name: "Playlists", exact: true }).click();
  await expect(picker.getByText("Connect your Invidious account to see subscriptions and playlists.")).toBeVisible();
  await picker.getByRole("button", { name: "Close", exact: true }).click();
  await expect(picker).toHaveCount(0);
  await expect(browse).toBeFocused();
  await expect(page.getByText("pending.pdf", { exact: true })).toBeVisible();

  await browse.press("Enter");
  await picker.getByRole("textbox").press("Escape");
  await expect(picker).toHaveCount(0);
  await expect(browse).toBeFocused();
  await expect(page.getByText("pending.pdf", { exact: true })).toBeVisible();
});
