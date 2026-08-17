import { expect, test, type Locator, type Page } from "@playwright/test";

const PAIRING_ID = "be0038de1f88";
const READER_URL = `/immersive-reading?pairing=${PAIRING_ID}`;

async function paragraphSidePoint(paragraph: Locator) {
  await paragraph.scrollIntoViewIfNeeded();
  return await paragraph.evaluate((node) => {
    const range = document.createRange();
    range.selectNodeContents(node);
    const rect = Array.from(range.getClientRects()).at(-1);
    if (!rect) throw new Error("Paragraph text was not measurable");
    return { x: rect.right + 8, y: rect.top + rect.height / 2 };
  });
}

async function dispatchSwipe(page: Page, direction: "previous" | "next" | "edge") {
  await page.evaluate((dir) => {
    const surface = document.querySelector("[data-reader-surface]");
    if (!(surface instanceof HTMLElement)) throw new Error("Reader surface missing");
    const startX =
      dir === "edge" ? 10 : Math.round(window.innerWidth * 0.55);
    const endX = dir === "previous" || dir === "edge" ? startX + 80 : startX - 80;
    const y = Math.round(window.innerHeight * 0.5);
    const start = new Touch({ identifier: 1, target: surface, clientX: startX, clientY: y });
    const end = new Touch({ identifier: 1, target: surface, clientX: endX, clientY: y + 4 });
    surface.dispatchEvent(
      new TouchEvent("touchstart", {
        bubbles: true,
        cancelable: true,
        touches: [start],
        targetTouches: [start],
        changedTouches: [start],
      }),
    );
    surface.dispatchEvent(
      new TouchEvent("touchend", {
        bubbles: true,
        cancelable: true,
        touches: [],
        targetTouches: [],
        changedTouches: [end],
      }),
    );
  }, direction);
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/auth/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        enabled: false,
        authenticated: true,
        user_id: "audit",
        username: "audit",
        role: "admin",
        is_admin: true,
      }),
    }),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(READER_URL);
  await expect(page.locator("[data-reader-surface]")).toBeVisible({ timeout: 20_000 });
});

test("iPhone reading uses focused paragraphs, side taps, toolbar, and swipes", async ({ page }) => {
  const toolbar = page.getByRole("toolbar", { name: /Reading toolbar|阅读工具栏/i });
  await expect(toolbar).toBeVisible();
  for (const label of [/Translation|译文/i, /Dictionary lookup|词典|查词/i, /Pronounce|发音/i, /Add bookmark|添加书签/i, /More|更多/i]) {
    await expect(toolbar.getByRole("button", { name: label })).toBeVisible();
  }
  const toolbarShell = toolbar.locator("xpath=..");
  await expect(toolbarShell).toHaveCSS("bottom", "10px");

  const groups = page.locator("[data-reader-surface] [data-group-index]");
  await expect(groups.nth(2)).toBeVisible();
  const paragraph = groups.nth(2).locator("p").first();
  const side = await paragraphSidePoint(paragraph);
  await page.mouse.click(side.x, side.y);
  await expect(groups.nth(2).locator("details")).toHaveAttribute("open", "");
  await expect(groups.nth(1)).not.toHaveAttribute("data-active", "");
  await expect(groups.nth(2)).toHaveAttribute("data-active", "true");

  const inlinePane = page.locator("[data-reader-surface] > div");
  await inlinePane.evaluate((node) => {
    node.scrollTop += 90;
  });
  await expect
    .poll(() => toolbarShell.evaluate((node) => node.style.transform))
    .toContain("translateY(calc(100% + 18px))");
  await inlinePane.evaluate((node) => {
    node.scrollTop -= 90;
  });
  await expect
    .poll(() => toolbarShell.evaluate((node) => node.style.transform))
    .toContain("translateY(0px)");

  const before = await groups.evaluateAll((nodes) => nodes.findIndex((node) => node.hasAttribute("data-active")));
  await dispatchSwipe(page, "next");
  await expect
    .poll(() => groups.evaluateAll((nodes) => nodes.findIndex((node) => node.hasAttribute("data-active"))))
    .toBe(before + 1);
  await page.waitForTimeout(600);

  await dispatchSwipe(page, "previous");
  await expect
    .poll(() => groups.evaluateAll((nodes) => nodes.findIndex((node) => node.hasAttribute("data-active"))))
    .toBe(before);
  await page.waitForTimeout(600);

  await dispatchSwipe(page, "edge");
  await expect
    .poll(() => groups.evaluateAll((nodes) => nodes.findIndex((node) => node.hasAttribute("data-active"))))
    .toBe(before);
});

test("iPhone tap-to-lookup opens and expands the dictionary sheet", async ({ page }) => {
  await page.addInitScript(() =>
    window.localStorage.setItem("deeptutor.bilingual-reader.click-lookup", "true"),
  );
  await page.reload();
  await expect(page.locator("[data-reader-surface]")).toBeVisible({ timeout: 20_000 });

  const paragraph = page.locator('[data-reader-surface] [data-group-index="0"] p').first();
  await paragraph.scrollIntoViewIfNeeded();
  await page.getByRole("button", { name: /More|更多/i }).click();
  await expect(page.getByRole("button", { name: /Tap words|点词/i })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.mouse.click(10, 30);
  const wordPoint = await paragraph.evaluate((node) => {
    const text = node.firstChild;
    if (!text) throw new Error("Paragraph text missing");
    const range = document.createRange();
    range.setStart(text, 0);
    const word = text.textContent?.match(/[A-Za-z]+/)?.[0];
    if (!word) throw new Error("Dictionary word missing");
    range.setEnd(text, word.length);
    const rect = range.getBoundingClientRect();
    if (!rect.width && !rect.height) throw new Error("Word text was not measurable");
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  });
  await page.mouse.click(wordPoint.x, wordPoint.y);

  const sheet = page.getByRole("dialog");
  await expect(sheet).toBeVisible();
  await expect(sheet).toContainText(/Save to vocabulary|保存到词汇|Add to vocabulary|添加词汇/i);
  await expect(sheet.getByRole("button", { name: /US|美式/i })).toBeVisible();
  const collapsedHeight = await sheet.evaluate((node) => node.getBoundingClientRect().height);
  expect(collapsedHeight).toBeGreaterThan(330);
  expect(collapsedHeight).toBeLessThan(480);

  const handle = sheet.getByRole("separator", { name: /Drag to expand dictionary|上拖展开词典/i });
  const handleBox = await handle.boundingBox();
  if (!handleBox) throw new Error("Dictionary drag handle was not measurable");
  await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y - 90, { steps: 5 });
  await page.mouse.up();
  await expect
    .poll(() => sheet.evaluate((node) => node.getBoundingClientRect().height))
    .toBeGreaterThan(collapsedHeight + 100);
});
