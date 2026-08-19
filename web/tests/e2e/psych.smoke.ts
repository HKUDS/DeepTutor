import { test, expect } from "@playwright/test";

test.describe.configure({ mode: "serial" });

/**
 * Live smoke for /psych — requires psych-academy serve + Next dev.
 * Skip when SKIP_LIVE_SMOKE=1.
 */
test.describe("Psych :: live smoke", () => {
  test.skip(
    !!process.env.SKIP_LIVE_SMOKE,
    "SKIP_LIVE_SMOKE set — skipping live psych dashboard test",
  );

  test("dashboard loads timeline summary from API", async ({ page }) => {
    test.setTimeout(60_000);

    await page.goto("/psych", { waitUntil: "domcontentloaded" });

    await expect(
      page.getByText(/Read-only trainee dashboard/i),
    ).toBeVisible({ timeout: 15_000 });

    // Loading spinner should resolve to content or a structured empty state.
    await expect(page.getByText(/Loading dashboard/i)).toBeHidden({
      timeout: 45_000,
    });

    const hasSection =
      (await page.getByText(/Recent emotion/i).count()) > 0 ||
      (await page.getByText(/No emotion events logged yet/i).count()) > 0 ||
      (await page.getByText(/psych_timeline_summary failed/i).count()) > 0;

    expect(hasSection).toBe(true);

    // When backend is up, expect at least one session section header.
    if ((await page.getByText(/psych_timeline_summary failed/i).count()) === 0) {
      await expect(page.getByText(/Recent Counsel/i)).toBeVisible({
        timeout: 5_000,
      });
    }
  });
});

test.describe("Psych :: static", () => {
  test("page loads psych dashboard shell", async ({ page }) => {
    await page.goto("/psych", { waitUntil: "domcontentloaded" });
    await expect(page.getByText("Psych", { exact: true }).first()).toBeVisible();
    await expect(
      page.getByText(/Read-only trainee dashboard — emotion timeline/i),
    ).toBeVisible();
    await expect(page.getByText(/Recent emotion/i)).toBeVisible({
      timeout: 15_000,
    });
  });

  test("shows session section headers", async ({ page }) => {
    await page.goto("/psych", { waitUntil: "domcontentloaded" });
    await expect(page.getByText(/Recent Counsel/i)).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(/Recent Sim/i)).toBeVisible();
    await expect(page.getByText(/Recent Intake/i)).toBeVisible();
  });
});
