import { expect, test } from "@playwright/test";

const profileId = process.env.KIDS_E2E_PROFILE_ID;
const documentId = process.env.KIDS_E2E_DOCUMENT_ID;

test.skip(
  !profileId || !documentId,
  "Set KIDS_E2E_PROFILE_ID and KIDS_E2E_DOCUMENT_ID to run this local Kids Reading smoke test",
);

test("child completes a chapter quiz and sees the book achievement", async ({ page }) => {
  await page.route(`**/api/v1/kids/books/${documentId}/quiz`, async (route) => {
    await route.fulfill({
      json: {
        section_id: "e2e-section",
        questions: [1, 2, 3].map((index) => ({
          id: `q${index}`,
          kind: "comprehension",
          question: `Story question ${index}?`,
          choices: [`Correct answer ${index}`, "Not this one", "Try again"],
        })),
      },
    });
  });
  await page.route(`**/api/v1/kids/books/${documentId}/quiz/submit`, async (route) => {
    await route.fulfill({
      json: {
        score: 3,
        total: 3,
        stars: 3,
        earned_stars: 3,
        per_question: [1, 2, 3].map((index) => ({
          id: `q${index}`,
          correct: true,
          explanation: "Correct.",
        })),
        encouragements: ["Great job!"],
      },
    });
  });

  await page.goto(`/kids/p/${profileId}`);
  await page.getByRole("button", { name: /kids-e2e-book/ }).click();
  await page.getByRole("button", { name: "Quiz" }).click();
  await expect(page.getByText("Story question 1?")).toBeVisible();
  await expect(page.getByText("Story question 2?")).toBeVisible();
  await expect(page.getByText("Story question 3?")).toBeVisible();

  for (const index of [1, 2, 3]) {
    await page.getByRole("button", { name: `Correct answer ${index}` }).click();
  }
  await page.getByRole("button", { name: "Check Answers!" }).click();
  await expect(page.getByText("3 / 3 correct!")).toBeVisible();
  await page.getByRole("button", { name: "Done!" }).click();
  await expect(page.getByText("Book Complete!")).toBeVisible();

  expect(await page.evaluate(() => localStorage.getItem("dt_kids_token"))).toBeNull();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    await page.evaluate(() => document.documentElement.clientWidth),
  );
});
