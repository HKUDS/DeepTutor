import { test, expect } from "@playwright/test";

test.describe.configure({ mode: "serial" });

/**
 * Live smoke for /intake — requires psych-academy serve + Next dev.
 * Skip when SKIP_LIVE_SMOKE=1 or the page never connects.
 */
const CRISIS_PHRASE = "我想自杀";
const VISITOR_OPENING = "I have been sleeping poorly lately.";

test.describe("Intake :: live smoke", () => {
  test.skip(
    !!process.env.SKIP_LIVE_SMOKE,
    "SKIP_LIVE_SMOKE set — skipping live intake browser test",
  );

  test("visitor first turn allocates room_id", async ({ page }) => {
    test.setTimeout(120_000);

    await page.goto("/intake", { waitUntil: "domcontentloaded" });

    await page.waitForFunction(
      () => {
        const text = document.body.innerText;
        return (
          !text.includes("Connecting…") &&
          !text.includes("Reconnecting…") &&
          text.includes("Live intake supervision")
        );
      },
      { timeout: 30_000 },
    );

    const textarea = page.getByRole("textbox", { name: "Visitor message" });
    await expect(textarea).toBeEnabled({ timeout: 5_000 });

    await textarea.fill(VISITOR_OPENING);
    await page.getByRole("button", { name: "Send" }).click();

    await expect(page.getByText(/room_id=/i)).toBeVisible({ timeout: 90_000 });
  });

  test("crisis message shows banner and locks composer", async ({ page }) => {
    test.setTimeout(120_000);

    await page.goto("/intake", { waitUntil: "domcontentloaded" });

    await page.waitForFunction(
      () => {
        const text = document.body.innerText;
        return (
          !text.includes("Connecting…") &&
          !text.includes("Reconnecting…") &&
          text.includes("Live intake supervision")
        );
      },
      { timeout: 30_000 },
    );

    const textarea = page.getByRole("textbox", { name: "Visitor message" });
    await expect(textarea).toBeEnabled({ timeout: 5_000 });

    await textarea.fill(CRISIS_PHRASE);
    await page.getByRole("button", { name: "Send" }).click();

    const banner = page.getByRole("status");
    await expect(banner).toContainText(/Crisis redirect detected/i, {
      timeout: 90_000,
    });

    await expect(textarea).toBeDisabled();
    await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();
  });
});

test.describe("Intake :: static", () => {
  test("page loads intake shell with three seats", async ({ page }) => {
    await page.goto("/intake", { waitUntil: "domcontentloaded" });
    await expect(page.getByText("Intake", { exact: true }).first()).toBeVisible();
    await expect(
      page.getByText(/Live intake supervision · visitor, trainee counselor, supervisor/i),
    ).toBeVisible();
    await expect(page.getByRole("tab", { name: /visitor/i })).toBeVisible();
    await expect(page.getByRole("tab", { name: /trainee/i })).toBeVisible();
    await expect(page.getByRole("tab", { name: /supervisor/i })).toBeVisible();
  });

  test("supervisor seat is read-only", async ({ page }) => {
    await page.goto("/intake", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("tablist", { name: "Seat" })).toBeVisible({
      timeout: 15_000,
    });
    const supervisorTab = page.getByRole("tab", { name: /supervisor/i });
    await supervisorTab.click();
    await expect(supervisorTab).toHaveAttribute("aria-selected", "true");
    await expect(
      page.getByText(/Supervisor seat is read-only/i),
    ).toBeVisible();
    await expect(page.getByRole("textbox")).toHaveCount(0);
  });
});
