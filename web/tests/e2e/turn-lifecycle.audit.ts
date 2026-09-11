import { expect, test } from "@playwright/test";

import { assistantActivity, sendPrompt } from "./fixtures/runtime";

const integrationFixtureAvailable =
  process.env.DEEPTUTOR_TURN_E2E_FIXTURE === "1";

test.describe("v2 turn lifecycle", () => {
  test.skip(
    !integrationFixtureAvailable,
    "Requires the deterministic backend turn fixture added with the multi-worker acceptance phase.",
  );

  test("uses the canonical activity and ask-user surfaces", async ({ page }) => {
    await page.goto("/");

    await sendPrompt(page, "Explain replay-safe turns");

    const activity = assistantActivity(page);
    await expect(activity.last()).toContainText(
      /DeepTutor (?:Exploring|Reasoning|Planning|Quizzing|Reflecting)/i,
    );

    await page.getByRole("textbox", { name: /answer/i }).fill("Continue");
    await page.getByRole("button", { name: /answer|submit/i }).click();
    await expect(activity.last()).toContainText(
      /DeepTutor (?:Exploring|Reasoning|Planning|responded)/i,
    );
  });

  test("recovers without replacing the canonical activity surface", async ({
    page,
  }) => {
    await page.goto("/");
    await sendPrompt(page, "Start a long turn");

    const activity = assistantActivity(page);
    await expect(activity.last()).toBeVisible();
    await page.getByRole("button", { name: /drop connection/i }).click();
    await expect(activity.last()).toContainText(/DeepTutor/i);
    await expect(page.getByRole("button", { name: /retry/i })).toHaveCount(0);
  });

  test("stops through the composer's existing turn control", async ({ page }) => {
    await page.goto("/");
    await sendPrompt(page, "Start a cancellable turn");
    await page.getByRole("button", { name: /stop generating|cancel/i }).click();

    await expect(
      page.getByRole("button", { name: /stop generating/i }),
    ).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^send$/i })).toBeVisible();
  });
});
