import { test, expect } from "@playwright/test";

/**
 * Static shell smoke for all Psych Academy workspace pages.
 * No backend required — verifies routes render expected chrome.
 */
const ACADEMY_SHELLS: Array<{
  path: string;
  title: string;
  subtitle: RegExp;
}> = [
  {
    path: "/whisper",
    title: "Whisper",
    subtitle: /Dual-seat supervision/i,
  },
  {
    path: "/sim",
    title: "Sim",
    subtitle: /Trainee as counselor/i,
  },
  {
    path: "/dual",
    title: "Dual",
    subtitle: /Watch AI counselor/i,
  },
  {
    path: "/observe",
    title: "Observe",
    subtitle: /One-shot debrief/i,
  },
  {
    path: "/distill",
    title: "Distill",
    subtitle: /Turn methodology excerpts/i,
  },
  {
    path: "/train",
    title: "Train",
    subtitle: /Start Guided Learning/i,
  },
];

test.describe("Academy pages :: static shells", () => {
  for (const { path, title, subtitle } of ACADEMY_SHELLS) {
    test(`${path} loads ${title} shell`, async ({ page }) => {
      await page.goto(path, { waitUntil: "domcontentloaded" });
      await expect(page.getByText(title, { exact: true }).first()).toBeVisible();
      await expect(page.getByText(subtitle)).toBeVisible();
    });
  }

  test("/observe?counsel_id= prefills session id field", async ({ page }) => {
    const counselId = "test-counsel-session-abc123";
    await page.goto(`/observe?counsel_id=${counselId}`, {
      waitUntil: "domcontentloaded",
    });
    await expect(page.getByLabel("Counsel session id")).toHaveValue(counselId);
  });

  test("/whisper exposes visitor and trainee seats", async ({ page }) => {
    await page.goto("/whisper", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("tablist", { name: "Seat" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByRole("tab", { name: "visitor" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "trainee" })).toBeVisible();
  });

  test("/sim exposes trainee counselor composer", async ({ page }) => {
    await page.goto("/sim", { waitUntil: "domcontentloaded" });
    await expect(
      page.getByRole("textbox", { name: "Trainee counselor message" }),
    ).toBeVisible({ timeout: 15_000 });
  });

  test("/distill exposes source excerpt composer", async ({ page }) => {
    await page.goto("/distill", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("textbox", { name: "Source excerpt" })).toBeVisible({
      timeout: 15_000,
    });
  });
});
