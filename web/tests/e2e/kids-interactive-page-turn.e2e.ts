import { expect, test } from "@playwright/test";

const pages = [
  {
    id: "pg_01",
    title: "第一页",
    chapter_title: "第一章",
    blocks: [
      {
        id: "blk_text_1",
        type: "text",
        title: "认识数字",
        payload: { text: "一页一页翻书，像小船慢慢向前。" },
      },
      {
        id: "blk_quiz_1",
        type: "quiz",
        title: "小问题",
        payload: {
          questions: [{ id: "q1", question: "一加一等于几？", choices: ["1", "2"] }],
        },
      },
    ],
  },
  {
    id: "pg_02",
    title: "第二页",
    chapter_title: "第一章",
    blocks: [
      { id: "blk_text_2", type: "text", payload: { text: "第二页：热区和滑动都能翻页。" } },
    ],
  },
  {
    id: "pg_03",
    title: "第三页",
    chapter_title: "第一章",
    blocks: [
      { id: "blk_text_3", type: "text", payload: { text: "第三页：快速连翻也保持一致。" } },
    ],
  },
];

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("dt_kids_token", "e2e-token");
    window.localStorage.setItem("dt_kids_profile_id", "child001");
  });

  await page.route("**/api/v1/kids/interactive-books/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const suffix = url.pathname.replace("/api/v1/kids/interactive-books/math", "");
    const json = (payload: unknown, status = 200) =>
      route.fulfill({ status, json: payload });

    if (suffix === "" && request.method() === "GET") {
      return json({
        book: { id: "math", title: "翻页小书", page_count: 3, chapter_count: 1 },
        spine: {
          book_id: "math",
          chapters: [{ id: "ch1", title: "第一章", order: 0, page_ids: pages.map((p) => p.id) }],
        },
        progress: {
          profile_id: "child001",
          book_id: "math",
          current_page_id: "pg_01",
          current_page_order: 0,
          completed_page_ids: [],
          total_stars: 0,
          last_read_at: 0,
        },
      });
    }
    const pageMatch = suffix.match(/^\/pages\/(.+)$/);
    if (pageMatch && request.method() === "GET") {
      const target = pages.find((item) => item.id === pageMatch[1]);
      if (!target) return json({ detail: "Not found" }, 404);
      if (target.id === "pg_02") {
        await new Promise((resolve) => setTimeout(resolve, 150));
      }
      return json({
        page: target,
        progress: {
          profile_id: "child001",
          book_id: "math",
          current_page_id: target.id,
          current_page_order: pages.findIndex((item) => item.id === target.id),
          completed_page_ids: [],
          total_stars: 0,
          last_read_at: 0,
        },
      });
    }
    if (suffix === "/progress" && request.method() === "PUT") {
      const body = request.postDataJSON();
      return json({
        progress: {
          profile_id: "child001",
          book_id: "math",
          current_page_id: body.page_id,
          current_page_order: body.page_order || 0,
          completed_page_ids: [],
          total_stars: 0,
          last_read_at: 0,
        },
      });
    }
    return json({ detail: "Not found" }, 404);
  });
});

test("kids interactive book supports safe page turns and controls", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/kids/p/child001/book/math");

  await expect(page.getByRole("heading", { name: "第一页" })).toBeVisible();
  await expect(page.locator("footer").getByRole("button", { name: "上一页", exact: true })).toBeDisabled();
  await expect(page.locator("footer").getByRole("button", { name: "下一页", exact: true })).toBeEnabled();

  const quizChoice = page.getByRole("button", { name: "B. 2", exact: true });
  await quizChoice.click();
  await page.mouse.move(200, 600);
  await page.mouse.down();
  await page.mouse.move(100, 600, { steps: 8 });
  await page.mouse.up();
  await expect(page.getByRole("heading", { name: "第一页" })).toBeVisible();

  await page.locator("footer").getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.getByRole("heading", { name: "第二页" })).toBeVisible();
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByRole("heading", { name: "第一页" })).toBeVisible();

  const bodyText = page.getByText("一页一页翻书，像小船慢慢向前。");
  const bodyTextBounds = await bodyText.boundingBox();
  if (!bodyTextBounds) throw new Error("Body text should have a bounding box");
  await page.mouse.move(
    bodyTextBounds.x + bodyTextBounds.width / 2,
    bodyTextBounds.y + bodyTextBounds.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(
    bodyTextBounds.x + bodyTextBounds.width / 2 - 110,
    bodyTextBounds.y + bodyTextBounds.height / 2,
    { steps: 8 },
  );
  await page.mouse.up();
  await expect(page.getByRole("heading", { name: "第二页" })).toBeVisible();
  await page.locator("footer").getByRole("button", { name: "上一页", exact: true }).click();
  await expect(page.getByRole("heading", { name: "第一页" })).toBeVisible();
});

test("kids interactive book applies only the last rapid page request", async ({ page }) => {
  await page.goto("/kids/p/child001/book/math");
  await expect(page.getByRole("heading", { name: "第一页" })).toBeVisible();

  const nextHotzone = page.locator("footer").getByRole("button", { name: "下一页", exact: true });
  await nextHotzone.click();
  await nextHotzone.click();

  await expect(page.getByRole("heading", { name: "第三页" })).toBeVisible({ timeout: 5000 });
  await expect(page.getByText("第 3 / 3 页")).toBeVisible();
  await expect(page.locator("footer").getByRole("button", { name: "下一页", exact: true })).toBeDisabled();
});

test("kids interactive book keeps the iPad dynamic viewport stable", async ({ page }) => {
  await page.setViewportSize({ width: 820, height: 1180 });
  await page.goto("/kids/p/child001/book/math");
  await expect(page.getByRole("heading", { name: "第一页" })).toBeVisible();

  const header = await page.locator("header").boundingBox();
  const main = await page.locator("main").boundingBox();
  const footer = await page.locator("footer").boundingBox();
  const pageCard = await page.locator("main > div").boundingBox();
  const previousHotzone = await page.locator("main").getByRole("button", { name: "上一页" }).boundingBox();
  const nextHotzone = await page.locator("main").getByRole("button", { name: "下一页" }).boundingBox();
  const previousButton = await page.locator("footer").getByRole("button", { name: "上一页", exact: true }).boundingBox();
  const nextButton = await page.locator("footer").getByRole("button", { name: "下一页", exact: true }).boundingBox();
  if (
    !header || !main || !footer || !pageCard ||
    !previousHotzone || !nextHotzone || !previousButton || !nextButton
  ) {
    throw new Error("Interactive book layout boxes should be measurable");
  }

  expect(main.y).toBeGreaterThanOrEqual(header.y + header.height - 0.5);
  expect(footer.y).toBeGreaterThanOrEqual(main.y + main.height - 0.5);
  expect(footer.y + footer.height).toBeLessThanOrEqual(1180.5);
  expect(previousHotzone.height).toBeGreaterThanOrEqual(main.height - 0.5);
  expect(nextHotzone.height).toBeGreaterThanOrEqual(main.height - 0.5);
  expect(previousHotzone.width).toBeLessThanOrEqual(96.5);
  expect(nextHotzone.width).toBeLessThanOrEqual(96.5);
  expect(pageCard.x).toBeGreaterThanOrEqual(previousHotzone.x + previousHotzone.width - 0.5);
  expect(pageCard.x + pageCard.width).toBeLessThanOrEqual(nextHotzone.x + 0.5);
  expect(previousButton.height).toBeGreaterThanOrEqual(48);
  expect(nextButton.height).toBeGreaterThanOrEqual(48);
  expect(previousButton.width).toBeGreaterThanOrEqual(108);
  expect(nextButton.width).toBeGreaterThanOrEqual(108);
  await expect(page.locator("footer")).toHaveCSS("padding-bottom", "12px");
});
