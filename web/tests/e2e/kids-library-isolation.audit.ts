import { expect, test } from "@playwright/test";

test("parent center and child device pairing end-to-end flow", async ({ page }) => {
  // 1. Visit Parent Center
  await page.goto("/kids/manage");
  await expect(page.getByText("Family Kids Reading Center / 家长中心")).toBeVisible();

  // 2. Verify navigation tabs
  await expect(page.getByRole("button", { name: /Children/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Kids Family Library/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Device Management/ })).toBeVisible();

  // 3. Switch to Kids Family Library tab
  await page.getByRole("button", { name: /Kids Family Library/ }).click();
  await expect(page.getByText("Only approved books in this library can be seen")).toBeVisible();
  await expect(page.getByRole("button", { name: "+ Upload New Kids Book" })).toBeVisible();

  // 4. Switch to Device Management tab
  await page.getByRole("button", { name: /Device Management/ }).click();
  await expect(page.getByText("Pair your child's iPad, phone, or laptop with a single 6-digit code.")).toBeVisible();

  // 5. Test Kids Portal unauthenticated pairing prompt
  await page.goto("/kids");
  await expect(page.getByText("My Reading World")).toBeVisible();
  await expect(page.getByText("Enter the 6-digit code from the Parent Center to pair this device")).toBeVisible();
  await expect(page.getByRole("button", { name: /Start Reading/ })).toBeVisible();

  // No horizontal overflow
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    await page.evaluate(() => document.documentElement.clientWidth),
  );
});

test("mobile viewport responsive check for kids portal and parent center", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });

  // Check Kids Portal on mobile
  await page.goto("/kids");
  await expect(page.getByText("My Reading World")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    await page.evaluate(() => document.documentElement.clientWidth),
  );

  // Check Parent Center on mobile
  await page.goto("/kids/manage");
  await expect(page.getByText("Family Kids Reading Center / 家长中心")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    await page.evaluate(() => document.documentElement.clientWidth),
  );
});
