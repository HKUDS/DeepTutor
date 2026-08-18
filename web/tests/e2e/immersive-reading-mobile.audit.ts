import { test, expect, type TestInfo, type Page, type Route } from "@playwright/test";

const BASE_URL =
  process.env.WEB_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://localhost:3000";

const PAIRING_ID = "pairing-mobile-ux";

function onlyMobileProject(testInfo: TestInfo) {
  test.skip(
    testInfo.project.name !== "ios-reader-webkit",
    "This case targets the iPhone/WebKit reading experience",
  );
}

type SectionFixture = {
  en_title: string;
  pairs?: number;
  groups: Array<{ en: string[]; zh: string[]; shape: string; cost: number; forced: boolean; low_confidence: boolean }>;
  chapter: string;
  passed: boolean;
  skipped: boolean;
  locked: boolean;
};

interface BilingualPositionUpdatePayload {
  chapter_index: number;
  group_index?: number;
  epub_cfi?: string;
  section_href?: string;
  scroll_percent?: number;
  text_fingerprint?: string;
}

const pairing = {
  pairing_id: PAIRING_ID,
  en_document_id: "en-doc",
  zh_document_id: "zh-doc",
  en_title: "Bilingual Experience Book",
  zh_title: "双语测试书",
  target_lang: "zh",
  translator: "gpt",
  chapter_count: 2,
  aligned: true,
  review_count: 1,
  chapter_map: [
    {
      id: "chapter-one",
      english: "chapter://one",
      translation: "chapter://one-zh",
      en_title: "Chapter One",
      zh_title: "第一章",
    },
    {
      id: "chapter-two",
      english: "chapter://two",
      translation: "chapter://two-zh",
      en_title: "Chapter Two",
      zh_title: "第二章",
    },
  ],
};

const sectionById: Record<string, SectionFixture> = {
  "chapter-one": {
    en_title: "Chapter One",
    pairs: 2,
    chapter: "chapter-one",
    passed: false,
    skipped: false,
    locked: false,
    groups: [
      {
        en: ["Short line for dictionary."],
        zh: ["一句简短释义行。"],
        shape: "1:1",
        cost: 0.32,
        forced: false,
        low_confidence: false,
      },
      {
        en: ["Long explanation sentence keeps the card content busy for scroll checks."],
        zh: ["这是一段长说明，用来验证字典卡片内容可滚动。"],
        shape: "1:1",
        cost: 0.47,
        forced: false,
        low_confidence: true,
      },
    ],
  },
  "chapter-two": {
    en_title: "Chapter Two",
    pairs: 2,
    chapter: "chapter-two",
    passed: false,
    skipped: false,
    locked: false,
    groups: [
      {
        en: ["Another short entry for next chapter."],
        zh: ["另一章短句。"],
        shape: "1:1",
        cost: 0.13,
        forced: false,
        low_confidence: false,
      },
      {
        en: ["Chinese-first readers often check line height and spacing under mobile widths."],
        zh: ["移动端宽度下应关注行高和间距。"],
        shape: "1:1",
        cost: 0.13,
        forced: false,
        low_confidence: false,
      },
    ],
  },
};

function jsonBody(route: Route, payload: unknown) {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });
}

async function mockMobileApis(page: Page) {
  const pairPrefix = "/api/v1/immersive-reading/bilingual/";
  const translationBoard = {
    tasks: [],
    summary: {
      total: 0,
      queued: 0,
      running: 0,
      completed: 0,
      failed: 0,
      cancelled: 0,
      filtered_total: 0,
      filtered_queued: 0,
      filtered_running: 0,
      filtered_completed: 0,
      filtered_failed: 0,
      filtered_cancelled: 0,
      is_running: false,
      last_run_at: 0,
    },
    sources: [],
    chapters: [{ chapter_id: "chapter-one", chapter_index: 0, title: "Chapter One", total_units: 0, translated_units: 0, completed: true }],
  };

  await page.route("**/api/v1/immersive-reading/bilingual/**", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (!url.pathname.startsWith(pairPrefix)) {
      await route.continue();
      return;
    }

    const suffix = decodeURIComponent(url.pathname.slice(pairPrefix.length));
    const [pairId, action, ...rest] = suffix.split("/");
    if (pairId !== PAIRING_ID) {
      await route.continue();
      return;
    }

    if (action === "reading-position" && method === "GET") {
      return jsonBody(route, {
        position: {
          pairing_id: PAIRING_ID,
          chapter_id: "chapter-one",
          chapter_index: 0,
          group_index: 0,
          epub_cfi: "",
          section_href: "chapter://one",
          scroll_percent: 0,
          text_fingerprint: "",
          updated_at: 1,
        },
      });
    }

    if (action === "navigation" && method === "GET") {
      return jsonBody(route, {
        navigation: {
          current: null,
          back_stack: [],
          forward_stack: [],
          can_back: false,
          can_forward: false,
        },
      });
    }

    if (action === "navigation" && method === "POST") {
      return jsonBody(route, {
        navigation: {
          current: {
            pairing_id: PAIRING_ID,
            chapter_id: "chapter-one",
            chapter_index: 1,
            group_index: 0,
            epub_cfi: "",
            section_href: "chapter://two",
            scroll_percent: 0,
            text_fingerprint: "",
            updated_at: 2,
          },
          back_stack: [],
          forward_stack: [],
          can_back: true,
          can_forward: false,
        },
        position: {
          pairing_id: PAIRING_ID,
          chapter_id: "chapter-one",
          chapter_index: 0,
          group_index: 0,
          epub_cfi: "",
          section_href: "chapter://one",
          scroll_percent: 0,
          text_fingerprint: "",
          updated_at: 2,
        },
      });
    }

    if (action === "navigation" && rest[0] === "back") {
      return jsonBody(route, {
        position: {
          pairing_id: PAIRING_ID,
          chapter_id: "chapter-one",
          chapter_index: 0,
          group_index: 0,
          epub_cfi: "",
          section_href: "chapter://one",
          scroll_percent: 0,
          text_fingerprint: "",
          updated_at: 3,
        },
        navigation: {
          current: null,
          back_stack: [],
          forward_stack: [],
          can_back: false,
          can_forward: true,
        },
      });
    }

    if (action === "navigation" && rest[0] === "forward") {
      return jsonBody(route, {
        position: {
          pairing_id: PAIRING_ID,
          chapter_id: "chapter-two",
          chapter_index: 1,
          group_index: 0,
          epub_cfi: "",
          section_href: "chapter://two",
          scroll_percent: 0,
          text_fingerprint: "",
          updated_at: 3,
        },
        navigation: {
          current: null,
          back_stack: [],
          forward_stack: [],
          can_back: true,
          can_forward: false,
        },
      });
    }

    if (action === "bookmarks" && method === "GET") {
      return jsonBody(route, {
        bookmarks: [
          {
            id: "bookmark-one",
            pairing_id: PAIRING_ID,
            chapter_id: "chapter-one",
            chapter_index: 0,
            chapter_title: "Chapter One",
            group_index: 0,
            scroll_percent: 5,
            epub_cfi: "",
            section_href: "chapter://one",
            text_fingerprint: "short line for dictionary.",
            updated_at: Date.now(),
            title: "Start",
            preview: "Short line for dictionary.",
          },
        ],
      });
    }

    if (action === "bookmarks" && method === "POST") {
      return jsonBody(route, {
        id: "bookmark-one",
        pairing_id: PAIRING_ID,
        chapter_id: "chapter-one",
        chapter_index: 0,
        chapter_title: "Chapter One",
        group_index: 0,
        scroll_percent: 0,
        epub_cfi: "",
        section_href: "chapter://one",
        text_fingerprint: "",
        updated_at: Date.now(),
        title: "",
        preview: "",
      });
    }

    if (action === "section" && method === "GET") {
      const chapterId = rest[0];
      const section = sectionById[chapterId];
      return jsonBody(route, {
        section,
        ...{ content: "", passed: false, skipped: false, locked: false },
      });
    }

    if (action === "reading-position" && method === "PUT") {
      const body = (await route.request().postDataJSON()) as BilingualPositionUpdatePayload;
      return jsonBody(route, {
        position: {
          pairing_id: PAIRING_ID,
          chapter_id: `chapter-${body.chapter_index === 0 ? "one" : "two"}`,
          chapter_index: body.chapter_index,
          group_index: body.group_index ?? 0,
          epub_cfi: body.epub_cfi || "",
          section_href: body.section_href || "",
          scroll_percent: body.scroll_percent || 0,
          text_fingerprint: body.text_fingerprint || "",
          updated_at: Date.now(),
        },
      });
    }

    if (action === "update-reading-position") {
      return jsonBody(route, {
        position: {
          pairing_id: PAIRING_ID,
          chapter_id: "chapter-one",
          chapter_index: 0,
          group_index: 0,
          epub_cfi: "",
          section_href: "chapter://one",
          scroll_percent: 0,
          text_fingerprint: "",
          updated_at: Date.now(),
        },
      });
    }

    if (action === "annotations") {
      return jsonBody(route, {
        annotations: [
          {
            id: "ann-1",
            pairing_id: PAIRING_ID,
            chapter_id: "chapter-one",
            chapter_title: "Chapter One",
            group_index: 0,
            issue_type: "missing_translation",
            note: "test note",
            en_text: "Short line for dictionary.",
            zh_text: "一句简短释义行。",
            shape: "1:1",
            cost: 0.3,
            status: "open",
            created_at: 1,
          },
        ],
      });
    }

    if (action === "export") {
      return route.fulfill({
        status: 200,
        headers: { "Content-Type": "application/epub+zip" },
        body: "mock-epub-bytes",
      });
    }

    if (action === "pair") {
      return jsonBody(route, pairing);
    }

    if (!action && method === "GET") {
      return jsonBody(route, {
        pairing_id: PAIRING_ID,
      });
    }

    await route.continue();
  });

  await page.route("**/api/v1/immersive-reading/(dictionary|translate)", async (route) => {
    const body = await route.request().postDataJSON().catch(() => null);
    if (route.request().url().includes("/dictionary")) {
      const word = (body as { word?: string })?.word || "";
      if (word.includes("Short") || word.includes("short")) {
        return jsonBody(route, {
          word,
          phonetic: "",
          definitions: [
            {
              part_of_speech: "noun",
              definition: "Compact definition for short result.",
              chinese: "简短释义。",
              example: "",
              synonyms: ["brief"],
              context_match: true,
            },
          ],
          chinese: "",
          context_note: "",
        });
      }

      return jsonBody(route, {
        word,
        phonetic: "",
        definitions: [
          {
            part_of_speech: "noun",
            definition:
              "Very long definition line one. Very long definition line two. Very long definition line three.\n" +
              "line four line five line six. This test payload is intentionally long to force the sheet height behavior.\n" +
              "line seven line eight line nine and ten to keep it scrollable for visual checks.",
            chinese: "" +
              "这是一段很长的中文解释文本，用于验证移动端字典面板在内容较长时不会把外层阅读区顶到不可接受的高度。\n" +
              "当内容超过收起阈值时，字典面板应支持滚动，并且向上展开时应接近屏幕高度。",
            example: "",
            synonyms: ["verbose", "detailed", "extended", "full"],
            context_match: true,
          },
        ],
        chinese: "",
        context_note: "",
      });
    }

    if (route.request().url().includes("/translate")) {
      return jsonBody(route, {
        word: (body as { text?: string })?.text || "",
        translation: "Translated text",
        phonetic: "",
        definitions: [],
        context_note: "Translation result appears here.",
      });
    }

    await route.continue();
  });

  await page.route("**/api/v1/translation/tasks*", async (route) => {
    const method = route.request().method();
    if (method !== "GET") {
      return jsonBody(route, translationBoard);
    }
    return jsonBody(route, translationBoard);
  });
}

async function selectParagraph(page: import("@playwright/test").Page, index: number) {
  const paragraph = page.locator("[data-testid='reader-content'] [data-group-index] p").nth(index);
  await paragraph.waitFor();

  await paragraph.evaluate((element) => {
    const text = element.textContent || "";
    const textNode = element.firstChild;
    const end = Math.min(10, text.length);
    const range = document.createRange();
    if (!textNode) return;
    range.setStart(textNode, 0);
    range.setEnd(textNode, end);

    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    const rect = range.getBoundingClientRect();
    const x = rect.left + Math.max(3, Math.min(12, rect.width - 1));
    const y = rect.top + Math.max(3, Math.min(12, rect.height - 1));

    const up = new PointerEvent("pointerup", {
      bubbles: true,
      cancelable: true,
      clientX: x,
      clientY: y,
      button: 0,
      pointerType: "touch",
      pointerId: 1,
    });
    element.dispatchEvent(up);
    window.dispatchEvent(new Event("selectionchange"));
  });
  await page.waitForTimeout(140);
}

async function readNoOverflow(page: import("@playwright/test").Page, selector: string) {
  return page.locator(selector).evaluate((root) => {
    const container = root as HTMLElement;
    const nodes = Array.from(root.querySelectorAll("p, h1, h2, h3, span, div, summary")) as HTMLElement[];
    for (const node of nodes) {
      if (node.scrollWidth > container.clientWidth + 1) {
        return {
          hasOverflow: true,
          snippet: node.textContent?.slice(0, 80),
          width: node.scrollWidth,
          container: container.clientWidth,
        };
      }
    }
    return { hasOverflow: false, snippet: "", width: container.clientWidth, container: container.clientWidth };
  });
}


test.beforeEach(async ({ page }, testInfo) => {
  onlyMobileProject(testInfo);
  await mockMobileApis(page);
  await page.goto(`${BASE_URL}/immersive-reading?pairing=${PAIRING_ID}`);
  await page.getByTestId("reader-content").waitFor();
  await page.getByTestId("reader-chapter-select").waitFor();
});

test("mobile bilingual reader does not overflow horizontally", async ({ page }) => {
  const result = await readNoOverflow(page, "[data-testid='reader-content']");
  expect(result.hasOverflow, `Overflow node: ${result.snippet}`).toBe(false);
});

test("mobile tools are reachable in the More menu", async ({ page }) => {
  await page.getByTestId("reader-mobile-more").click();

  const moreMenu = page.getByTestId("reader-mobile-more-menu");
  await expect(moreMenu).toBeVisible();
  await expect(page.getByTestId("reader-more-history-back")).toBeVisible();
  await expect(page.getByTestId("reader-more-history-forward")).toBeVisible();
  await expect(page.getByTestId("reader-more-bookmarks")).toBeVisible();
  await expect(page.getByTestId("reader-more-taskboard")).toBeVisible();
  await expect(page.getByTestId("reader-more-export")).toBeVisible();

  await page.getByTestId("reader-more-bookmarks").click();
  await expect(page.getByRole("heading", { name: /Bookmarks/ })).toBeVisible();
  await page.keyboard.press("Escape");
});

test("chapter navigation can switch and restore layout", async ({ page }) => {
  await expect(page.getByTestId("reader-chapter-select")).toHaveValue("0");

  await page.getByTestId("reader-chapter-select").selectOption("1");
  await expect(page.getByTestId("reader-chapter-select")).toHaveValue("1");
  await expect(page.getByTestId("reader-content")).toContainText("Chapter Two");

  await page.getByTestId("reader-chapter-nav-prev").click();
  await expect(page.getByTestId("reader-chapter-select")).toHaveValue("0");
  await expect(page.getByTestId("reader-content")).toContainText("Chapter One");
});

test("dictionary sheet can open with short result and close", async ({ page }) => {
  await selectParagraph(page, 0);
  await expect(page.getByTestId("dictionary-sheet")).toBeVisible();
  await expect(page.getByTestId("dictionary-content")).toContainText("Compact definition for short result.");
  await expect(page.getByTestId("dictionary-sheet")).toHaveJSProperty("tagName", "DIV");

  const compactHeight = await page.getByTestId("dictionary-sheet").evaluate((el) => el.getBoundingClientRect().height);
  expect(compactHeight).toBeGreaterThan(0);

  await page.getByTestId("dictionary-close").click();
  await expect(page.getByTestId("dictionary-sheet")).toBeHidden();
});

test("dictionary long content supports expand and scroll", async ({ page }) => {
  await selectParagraph(page, 1);
  const sheet = page.getByTestId("dictionary-sheet");
  await expect(sheet).toBeVisible();

  const contentScrollable = await page
    .getByTestId("dictionary-content")
    .evaluate((el) => {
      return el.scrollHeight > el.clientHeight + 2;
    });
  expect(contentScrollable).toBe(true);

  const compactHeight = await sheet.evaluate((el) => el.getBoundingClientRect().height);
  const handle = sheet.locator('button[aria-label="Expand dictionary"]');
  await handle.click();
  const expandedHeight = await sheet.evaluate((el) => el.getBoundingClientRect().height);
  expect(expandedHeight).toBeGreaterThan(compactHeight);
  await page.getByTestId("dictionary-close").click();
});
