import { expect, test } from "@playwright/test";

const BASE_URL =
  process.env.WEB_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://localhost:3000";

function json(data: unknown) {
  return {
    status: 200,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(data),
  };
}

test("book arrows read the current chapter before turning chapters", async ({
  page,
}) => {
  const paragraph = (chapter: number, section: number) =>
    Array.from(
      { length: 12 },
      (_, row) =>
        `Chapter ${chapter}, section ${section}, row ${row + 1}: ${"deterministic browser reading content. ".repeat(16)}`,
    ).join("\n\n");

  const block = (pageId: string, section: number) => ({
    id: `${pageId}-block-${section}`,
    type: "text",
    status: "ready",
    title: `Section ${section}`,
    params: {},
    payload: { body: paragraph(Number(pageId.slice(-1)), section) },
    source_anchors: [],
    metadata: {},
    error: "",
    created_at: 1,
    updated_at: 1,
  });

  const summary = (id: string, title: string, order: number) => ({
    id,
    book_id: "sequential-fixture",
    chapter_id: `${id}-chapter`,
    title,
    learning_objectives: [],
    content_type: "theory",
    status: "ready",
    order,
    blocks: [],
    block_count: 3,
    links: [],
    parent_page_id: "",
    error: "",
    created_at: 1,
    updated_at: 1,
  });

  const summaries = [
    summary("page-1", "Previous chapter", 1),
    summary("page-2", "Current long chapter", 2),
    summary("page-3", "Next chapter", 3),
  ];
  const fullPage = (base: (typeof summaries)[number]) => ({
    ...base,
    blocks: [1, 2, 3].map((section) => block(base.id, section)),
  });
  const book = {
    id: "sequential-fixture",
    title: "Sequential reading fixture",
    description: "",
    status: "ready",
    proposal: null,
    knowledge_bases: [],
    language: "en",
    page_count: 3,
    chapter_count: 3,
    created_at: 1,
    updated_at: 1,
    metadata: {},
  };
  const progress = {
    book_id: "sequential-fixture",
    current_page_id: "page-2",
    visited_page_ids: ["page-2"],
    bookmarked_page_ids: [],
    quiz_attempts: [],
    weak_chapters: [],
    score: 0,
    updated_at: 1,
  };

  await page.route("**/api/**", async (route) => {
    const requestUrl = new URL(route.request().url());
    // Middleware proxies same-origin API calls to the backend. Point the
    // browser fixture directly at that destination so Next's proxy cannot
    // rewrite it away from Playwright's mock.
    const url =
      requestUrl.origin === "http://127.0.0.1:8001"
        ? new URL(requestUrl.pathname + requestUrl.search, BASE_URL)
        : requestUrl;
    const { pathname } = url;
    if (pathname === "/api/books/sequential-fixture/pages/page-1") {
      return route.fulfill(json({ page: fullPage(summaries[0]) }));
    }
    if (pathname === "/api/books/sequential-fixture/pages/page-2") {
      return route.fulfill(json({ page: fullPage(summaries[1]) }));
    }
    if (pathname === "/api/books/sequential-fixture/pages/page-3") {
      return route.fulfill(json({ page: fullPage(summaries[2]) }));
    }
    if (pathname === "/api/books/sequential-fixture") {
      return route.fulfill(
        json({ book, spine: null, pages: summaries, progress }),
      );
    }
    if (pathname === "/api/books") {
      return route.fulfill(json({ books: [{ ...book, reading: null }] }));
    }
    if (pathname === "/api/settings") {
      return route.fulfill(json({ catalog: [] }));
    }
    if (pathname.endsWith("/learning-captures")) {
      return route.fulfill(json({ captures: [] }));
    }
    if (pathname.endsWith("/progress/visit")) {
      return route.fulfill(json({ progress }));
    }
    return route.fulfill(json({}));
  });

  await page.goto(`${BASE_URL}/books/sequential-fixture/pages/page-2`, {
    waitUntil: "domcontentloaded",
  });
  // A hidden reader (for example when the mobile chapter sidebar is expanded)
  // must not turn the page and skip unread content.
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/page=page-2/);

  await page.getByRole("button", { name: "Collapse chapters" }).click();
  await expect(
    page.getByRole("heading", { name: "Current long chapter" }),
  ).toBeVisible();
  await expect(page.getByText("Chapter 2, section 3, row 12:")).toBeVisible();

  const reader = page.getByTestId("chapter-scroll-container");
  await expect(reader).toBeVisible();
  const firstScreen = await reader.evaluate((element) => ({
    clientHeight: element.clientHeight,
    maxScrollTop: element.scrollHeight - element.clientHeight,
    scrollTop: element.scrollTop,
  }));
  expect(firstScreen.maxScrollTop).toBeGreaterThan(firstScreen.clientHeight);

  await page.keyboard.press("ArrowRight");
  const afterRight = await reader.evaluate((element) => ({
    maxScrollTop: element.scrollHeight - element.clientHeight,
    scrollTop: element.scrollTop,
  }));
  expect(afterRight.scrollTop).toBeGreaterThan(0);
  expect(afterRight.scrollTop).toBeLessThan(afterRight.maxScrollTop);
  await expect(
    page.getByRole("heading", { name: "Current long chapter" }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page
        .getByTestId("chapter-progress")
        .evaluate((element) => (element as HTMLProgressElement).value),
    )
    .toBe(Math.round((afterRight.scrollTop / afterRight.maxScrollTop) * 100));

  await reader.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await expect
    .poll(() =>
      page
        .getByTestId("chapter-progress")
        .evaluate((element) => (element as HTMLProgressElement).value),
    )
    .toBe(100);
  await page.keyboard.press("ArrowRight");
  await expect(
    page.getByRole("heading", { name: "Next chapter" }),
  ).toBeVisible();
  await expect(await reader.evaluate((element) => element.scrollTop)).toBe(0);

  await page.keyboard.press("ArrowLeft");
  await expect(
    page.getByRole("heading", { name: "Current long chapter" }),
  ).toBeVisible();
  await expect
    .poll(() =>
      reader.evaluate(
        (element) =>
          element.scrollTop === element.scrollHeight - element.clientHeight,
      ),
    )
    .toBe(true);

  await page.keyboard.press("ArrowLeft");
  const afterLeft = await reader.evaluate((element) => ({
    maxScrollTop: element.scrollHeight - element.clientHeight,
    scrollTop: element.scrollTop,
  }));
  expect(afterLeft.scrollTop).toBeGreaterThan(0);
  expect(afterLeft.scrollTop).toBeLessThan(afterLeft.maxScrollTop);
  await expect(
    page.getByRole("heading", { name: "Current long chapter" }),
  ).toBeVisible();
});
