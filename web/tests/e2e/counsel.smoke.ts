import { test, expect } from "@playwright/test";

/**
 * Live smoke for /counsel — requires psych-academy serve + Next dev.
 * Skip when SKIP_LIVE_SMOKE=1 or the page never connects.
 */
const CRISIS_PHRASE = "我想自杀";

test.describe("Counsel :: live smoke", () => {
  test.skip(
    !!process.env.SKIP_LIVE_SMOKE,
    "SKIP_LIVE_SMOKE set — skipping live counsel browser test",
  );

  test("crisis message shows banner and locks composer", async ({ page }) => {
    test.setTimeout(120_000);

    await page.goto("/counsel", { waitUntil: "domcontentloaded" });

    await page.waitForFunction(
      () => {
        const text = document.body.innerText;
        return (
          !text.includes("Connecting…") &&
          !text.includes("Reconnecting…") &&
          text.includes("Visitor counsel")
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

test.describe("Counsel :: static", () => {
  test("page loads counsel shell", async ({ page }) => {
    await page.goto("/counsel", { waitUntil: "domcontentloaded" });
    await expect(page.getByText("Counsel", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Visitor counsel")).toBeVisible();
  });
});
