import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const epubBody = readFileSync(
  path.resolve(process.cwd(), "tests/fixtures/kids-golden.epub"),
);
const chineseEpubBody = readFileSync(
  path.resolve(process.cwd(), "tests/fixtures/kids-chinese.epub"),
);

const progress = {
  profile_id: "child001",
  document_id: "golden",
  current_section_id: "section_0001",
  current_section_index: 0,
  scroll_percent: 0,
  epub_cfi: "",
  section_href: "",
  completed_section_ids: [],
  total_stars: 0,
  quiz_attempts: 0,
  quiz_best_score: 0,
  quiz_scores: {},
  quiz_stars_awarded: {},
  time_spent_seconds: 0,
  last_read_at: 0,
};

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("dt_kids_token", "e2e-token");
    window.localStorage.setItem("dt_kids_profile_id", "child001");
  });

  await page.route("**/api/v1/kids/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const suffix = url.pathname.replace("/api/v1/kids", "");
    const json = (payload: unknown, status = 200) =>
      route.fulfill({ status, json: payload });

    if (suffix === "/bootstrap") return json({ profiles: [] });
    if (suffix === "/books/golden" && request.method() === "GET") {
      return json({
        document: {
          id: "golden",
          title: "Kids Golden Path",
          sections: [
            { id: "section_0001", title: "Book 1 - Plums", index: 0, checkpoint_kind: "chapter" },
            { id: "section_0002", title: "Book 2 - Little Bug", index: 1, checkpoint_kind: "chapter" },
          ],
        },
        progress,
      });
    }
    if (suffix === "/books/chinese" && request.method() === "GET") {
      return json({
        document: {
          id: "chinese",
          title: "孩子的量子世界",
          content_language: "zh",
          sections: [
            { id: "section_0001", title: "第1讲 量子世界", index: 0, checkpoint_kind: "chapter" },
          ],
        },
        progress: { ...progress, document_id: "chinese" },
      });
    }
    if (suffix === "/books/golden/epub" || suffix === "/books/chinese/epub") {
      return route.fulfill({
        status: 200,
        contentType: "application/epub+zip",
        body: suffix === "/books/chinese/epub" ? chineseEpubBody : epubBody,
      });
    }
    if (suffix === "/books/golden/progress" && request.method() === "PUT") {
      return json({ progress });
    }
    if (suffix === "/books/golden/word-hint") {
      return json({
        available: true,
        hint_id: "hint-001",
        word: "plum",
        phonetic: "plʌm",
        english_hint: "Picture a small, juicy fruit growing on a sunny tree. What is it?",
      });
    }
    if (suffix === "/books/golden/word-hint/choices") {
      return json({
        choices: ["a small sweet fruit", "a machine that moves", "a winter storm"],
      });
    }
    if (suffix === "/books/golden/word-hint/check") {
      const attempt = request.postDataJSON().attempt;
      if (attempt < 2) return json({ correct: false, feedback: "Think again." });
      return json({
        correct: false,
        feedback: "Let us look together.",
        correct_choice: "a small sweet fruit",
        chinese: "李子",
        explanation: "A plum is a small sweet fruit.",
      });
    }
    if (suffix === "/books/golden/word-hint/reveal") {
      return json({
        correct_choice: "a small sweet fruit",
        chinese: "李子",
        explanation: "A plum is a small sweet fruit.",
      });
    }
    if (suffix === "/books/golden/learn") {
      return json({ detail: "English books use word hints" }, 404);
    }
    if (suffix === "/books/chinese/learn") {
      return json({
        document_id: "chinese",
        section_id: "section_0001",
        language: "zh",
        source: "generated",
        overview: "这一页介绍量子世界和量子力学。",
        concepts: [
          {
            term: "量子世界",
            explanation: "量子世界是很小粒子遵循特殊规律的世界。",
            analogy: "就像一个藏在放大镜里的小球场。",
          },
          {
            term: "量子力学",
            explanation: "科学家用它研究很小粒子的运动。",
            analogy: "像一把专门测量小球的尺子。",
          },
        ],
        reflection: {
          prompt: "用自己的话说说，这一页讲了什么？",
          hint: "先想想我们每天看见的世界和很小粒子的世界有什么不同。",
          answer: "这一页介绍量子世界和量子力学。",
        },
      });
    }
    if (suffix === "/books/golden/quiz") {
      return json({
        section_id: "section_0001",
        questions: [
          { id: "q1", kind: "sight_word", question: 'What does "plum" mean?', choices: ["a small sweet fruit", "a machine that moves", "a winter storm"] },
          { id: "q2", kind: "sight_word", question: 'What does "good" mean?', choices: ["nice, not bad", "very cold", "very fast"] },
          { id: "q3", kind: "sight_word", question: 'What does "get" mean?', choices: ["take or receive", "sleep", "jump"] },
        ],
      });
    }
    if (suffix === "/books/chinese/quiz") {
      return json({
        section_id: "section_0001",
        language: "zh",
        questions: [
          {
            id: "q1",
            kind: "comprehension",
            question: "这一页主要讲什么？",
            choices: ["量子世界", "三只小猪", "外星汽车", "白雪公主"],
          },
          {
            id: "q2",
            kind: "comprehension",
            question: "科学家用量子力学研究什么？",
            choices: ["很小的粒子", "很大的太阳", "很远的历史", "很深的海水"],
          },
          {
            id: "q3",
            kind: "comprehension",
            question: "量子世界和日常世界有什么不同？",
            choices: ["规律不一样", "颜色不一样", "味道不一样", "温度不一样"],
          },
        ],
      });
    }
    if (suffix === "/books/golden/quiz/submit") {
      return json({
        score: 3,
        total: 3,
        stars: 3,
        new_stars_awarded: 3,
        total_stars: 3,
        completed_section_ids: ["section_0001"],
        per_question: [
          { id: "q1", correct: true, explanation: "" },
          { id: "q2", correct: true, explanation: "" },
          { id: "q3", correct: true, explanation: "" },
        ],
        encouragements: ["Great job!"],
      });
    }
    if (suffix === "/books/chinese/quiz/submit") {
      return json({
        score: 3,
        total: 3,
        stars: 3,
        new_stars_awarded: 3,
        total_stars: 3,
        language: "zh",
        completed_section_ids: ["section_0001"],
        per_question: [
          { id: "q1", correct: true, explanation: "这一页讲量子世界。" },
          { id: "q2", correct: true, explanation: "科学家研究很小的粒子。" },
          { id: "q3", correct: true, explanation: "两个世界的规律不一样。" },
        ],
        encouragements: ["全部答对，太棒了！"],
      });
    }
    return json({ detail: "Not found" }, 404);
  });
});

test("kids golden path guides words, auto-checks chapters, and narrates", async ({ page }) => {
  await page.goto("/kids/golden");

  await expect(page.getByText("Kids Golden Path")).toBeVisible();
  const reader = page.frameLocator("iframe").last();
  await expect(reader.getByText("The good plum is in the tree.")).toBeVisible();

  await reader.getByText("plum", { exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "plum" })).toBeVisible();
  await expect(page.getByText("Picture a small, juicy fruit growing on a sunny tree. What is it?")).toBeVisible();
  const clueSpeechButton = page.getByRole("button", { name: "Read thinking clue" });
  await expect(clueSpeechButton).toBeVisible();
  await clueSpeechButton.click();
  await expect(page.getByRole("button", { name: "Stop thinking clue" })).toBeVisible();
  await page.getByRole("button", { name: "Stop thinking clue" }).click();
  const hintCard = page.locator("div[role], section, body").filter({ hasText: "plum" }).last();
  await expect(hintCard).not.toContainText("李子");

  await page.getByRole("button", { name: "I need choices" }).click();
  await expect(page.getByRole("button", { name: "a machine that moves", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "a small sweet fruit", exact: true })).toHaveCount(1);
  await page.getByRole("button", { name: "a winter storm", exact: true }).click();
  await expect(page.getByText("Think again.")).toBeVisible();
  await expect(page.locator("div[role], section, body").filter({ hasText: "plum" }).last()).not.toContainText("李子");
  await page.getByRole("button", { name: "a winter storm", exact: true }).click();
  await expect(page.getByText("李子")).toBeVisible();
  await page.getByRole("button", { name: "Got it" }).click();

  await page.locator("button:has(span)").first().click();
  const tocEntry = page.getByRole("button", { name: "Book 2 - Little Bug" });
  await expect(tocEntry).toBeVisible();
  await expect(tocEntry).toHaveCSS("color", "rgb(55, 48, 163)");
  await tocEntry.click();
  await expect(page.getByRole("heading", { name: "Look and Think" })).toBeVisible();
  await expect(page.getByText("Question 1")).toBeVisible();
  await expect(page.getByText("Question 2")).toBeVisible();
  await expect(page.getByText("Question 3")).toBeVisible();
  await expect(page.getByRole("button", { name: "Read question" })).toHaveCount(3);

  await page.getByRole("button", { name: "a small sweet fruit", exact: true }).first().click();
  await page.getByRole("button", { name: "nice, not bad", exact: true }).click();
  await page.getByRole("button", { name: "take or receive", exact: true }).click();
  await page.getByRole("button", { name: "Submit" }).click();
  await expect(page.getByText("3 / 3 correct!")).toBeVisible();
  await expect(page.getByText("Stars: 3")).toBeVisible();
  await expect(page.getByRole("button", { name: "Read answer" })).toHaveCount(3);
});

test("kids Chinese learn uses guided concepts and Chinese quiz feedback", async ({ page }) => {
  await page.goto("/kids/chinese");

  await expect(page.getByText("孩子的量子世界")).toBeVisible();
  const reader = page.frameLocator("iframe").last();
  await expect(reader.getByText("很多小朋友都听说过量子力学。")).toBeVisible();
  await page.getByRole("button", { name: "学习" }).click({ force: true });
  await expect(page.getByRole("heading", { name: "这一页讲了什么" })).toBeVisible();
  await expect(page.getByText("关键概念")).toBeVisible();
  await expect(page.getByText("量子世界", { exact: true })).toBeVisible();
  await expect(page.getByText("像一把专门测量小球的尺子。")).toBeVisible();
  await expect(page.getByText("想一想")).toBeVisible();
  await expect(page.getByText("先想想我们每天看见的世界和很小粒子的世界有什么不同。")).toBeHidden();
  await page.getByRole("button", { name: "看提示" }).click();
  await expect(page.getByText("先想想我们每天看见的世界和很小粒子的世界有什么不同。")).toBeVisible();
  await page.getByRole("button", { name: "看答案" }).click();
  await expect(page.getByText("这一页介绍量子世界和量子力学。")).toHaveCount(2);
  await expect(page.getByRole("button", { name: "朗读本页主旨" })).toBeVisible();
  await expect(page.getByRole("button", { name: "朗读概念" })).toHaveCount(2);
  await expect(page.getByText("Explore Words")).toBeHidden();
  await page.getByRole("button", { name: "关闭" }).click();

  await page.getByRole("button", { name: "测一测" }).click();
  await expect(page.getByText("看一看，想一想")).toBeVisible();
  await expect(page.getByText("题目 1")).toBeVisible();
  await expect(page.getByText("题目 2")).toBeVisible();
  await expect(page.getByText("题目 3")).toBeVisible();
  await page.getByRole("button", { name: "量子世界", exact: true }).click();
  await page.getByRole("button", { name: "很小的粒子", exact: true }).click();
  await page.getByRole("button", { name: "规律不一样", exact: true }).click();
  await page.getByRole("button", { name: "提交" }).click();
  await expect(page.getByText("答对 3 / 3 题")).toBeVisible();
  await expect(page.getByText("星星: 3")).toBeVisible();
  await expect(page.getByText("全部答对，太棒了！")).toBeVisible();
});
