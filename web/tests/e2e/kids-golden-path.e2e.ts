import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const epubBody = readFileSync(
  path.resolve(process.cwd(), "tests/fixtures/kids-golden.epub"),
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
    if (suffix === "/books/golden/epub") {
      return route.fulfill({
        status: 200,
        contentType: "application/epub+zip",
        body: epubBody,
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
  await page.getByRole("button", { name: "Book 2 - Little Bug" }).click();
  await expect(page.getByRole("heading", { name: "Look and Think" })).toBeVisible();
  await expect(page.getByText("Question 1")).toBeVisible();
  await expect(page.getByText("Question 2")).toBeVisible();
  await expect(page.getByText("Question 3")).toBeVisible();
  await expect(page.getByRole("button", { name: "Read question" })).toHaveCount(3);

  await page.getByRole("button", { name: "a small sweet fruit", exact: true }).first().click();
  await page.getByRole("button", { name: "nice, not bad", exact: true }).click();
  await page.getByRole("button", { name: "take or receive", exact: true }).click();
  await page.getByRole("button", { name: "Check My Thinking" }).click();
  await expect(page.getByText("3 / 3 correct!")).toBeVisible();
  await expect(page.getByText("Stars: 3")).toBeVisible();
  await expect(page.getByRole("button", { name: "Read answer" })).toHaveCount(3);
});
