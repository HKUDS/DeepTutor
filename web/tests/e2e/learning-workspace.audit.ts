import { test, expect, type ConsoleMessage, type Page } from "@playwright/test";
import { mockLearningApis, ATTEMPT } from "./learning-workspace-fixtures";

/**
 * Feynman learning workspace audit (UI-01).
 *
 * Deterministic fixtures drive the LRN-03 / MOD-03 read APIs and the global
 * app-shell (auth status, session list, LLM options, tools, KB list, subagent
 * settings) so the approved r9 hierarchy renders without a live backend — and
 * no Next dev error overlay can ever be captured. Verifies:
 *   - 1440px three-column workbench and 390px 知识地图/对话/证据 tabs
 *   - no horizontal overflow and no toolbar/content/composer overlap
 *   - text send / confirmed transcript / help request store a handoff and
 *     navigate to the same session at /home/{pathId}, prefilling the real chat
 *     composer (mastery_path capability) without auto-sending
 *   - keyboard/touch primary flows change state (select, source detail,
 *     challenge, conflict, stale recovery)
 *   - no pageerror and no console.error during any audited page
 * Screenshots are written under tests/e2e/screenshots/.
 */

const BASE_URL =
  process.env.WEB_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://localhost:3199";

/**
 * Fails the test on any uncaught page error or console.error — the check that
 * keeps the screenshots free of the Next dev error overlay and of silent
 * network failures. Call once per test after the page is available and assert
 * `check()` before finishing. `allow` optionally ignores a console error the
 * scenario intentionally produces (e.g. the 409 in the stale-version test).
 */
function watchConsole(
  page: Page,
  allow?: (message: string) => boolean,
): () => void {
  const messages: string[] = [];
  page.on("pageerror", (error) => {
    messages.push(`pageerror: ${error.message}`);
  });
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() === "error") {
      const text = msg.text();
      if (!allow?.(text)) messages.push(`console.error: ${text}`);
    }
  });
  return () => {
    expect(messages, `unexpected page/console errors:\n${messages.join("\n")}`).toEqual([]);
  };
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, `horizontal overflow = ${overflow}px`).toBeLessThanOrEqual(0);
}

async function expectNoVerticalOverlap(page: Page) {
  // Composer must never cover the conversation stream; poll until fonts/layout
  // settle so a transient FOUC frame can't fail a correct layout.
  await expect
    .poll(
      async () => {
        const chat = await page.getByTestId("conversation-stream").boundingBox();
        const composer = await page.getByTestId("composer").boundingBox();
        if (!chat || !composer) return Infinity;
        return chat.y + chat.height - composer.y;
      },
      { timeout: 10000, message: "composer covers conversation" },
    )
    .toBeLessThanOrEqual(1);
}

async function openWorkspace(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockLearningApis(page);
  await page.goto(`${BASE_URL}/space/learning/path-001`);
  await expect(page.getByTestId("feynman-workspace")).toBeVisible({ timeout: 20000 });
}

/** The main chat composer textarea (fresh /home page has exactly one). */
function chatComposer(page: Page) {
  return page.locator("textarea").first();
}

test.describe("Learning workspace :: desktop 1440px", () => {
  test("renders three color-separated columns without overflow", async ({ page }) => {
    const check = watchConsole(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockLearningApis(page);
    await page.goto(`${BASE_URL}/space/learning/path-001`);
    const ws = page.getByTestId("feynman-workspace");
    await expect(ws).toBeVisible({ timeout: 20000 });
    await expect(page.getByTestId("map-panel")).toBeVisible();
    await expect(page.getByTestId("chat-panel")).toBeVisible();
    await expect(page.getByTestId("evidence-panel")).toBeVisible();
    await expect(page.getByTestId("mobile-tabs")).toBeHidden();
    // Long identifiers stay inside their panel.
    await expect(page.getByTestId("long-id").first()).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await expectNoVerticalOverlap(page);
    await page.screenshot({ path: "tests/e2e/screenshots/learning-workspace-1440.png", fullPage: true });
    check();
  });

  test("recoverable stale-version error offers refresh and recovers", async ({ page }) => {
    // The 409 conflict is the scenario under test, so its console error is
    // expected and allowlisted; everything else still fails the check.
    const check = watchConsole(page, (message) => message.includes("409 (Conflict)"));
    await page.setViewportSize({ width: 1440, height: 900 });
    let attemptFails = true;
    await mockLearningApis(page);
    await page.route("**/api/v1/learning/progress/*/attempts/*", (route) => {
      if (attemptFails) {
        route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: "expected attempt version 1, current is 2" }),
        });
      } else {
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ATTEMPT) });
      }
    });
    await page.goto(`${BASE_URL}/space/learning/path-001`);
    const banner = page.getByTestId("feynman-recoverable-error");
    await expect(banner).toBeVisible({ timeout: 20000 });
    attemptFails = false;
    await page.getByTestId("feynman-recover-refresh").click();
    await expect(banner).toBeHidden({ timeout: 20000 });
    await expect(page.getByTestId("conversation-stream").locator(".fw-message").first()).toBeVisible();
    check();
  });
});

test.describe("Learning workspace :: mobile 390px", () => {
  test("switches 知识地图/对话/证据 tabs and keeps the composer fixed", async ({ page }) => {
    const check = watchConsole(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await mockLearningApis(page);
    await page.goto(`${BASE_URL}/space/learning/path-001`);
    const tabs = page.getByTestId("mobile-tabs");
    await expect(tabs).toBeVisible({ timeout: 20000 });

    // Default: chat visible, map hidden.
    await expect(page.getByTestId("chat-panel")).toBeVisible();
    await expect(page.getByTestId("map-panel")).toBeHidden();

    // Switch to map.
    await page.getByTestId("mobile-tab-map").click();
    await expect(page.getByTestId("map-panel")).toBeVisible();
    await expect(page.getByTestId("chat-panel")).toBeHidden();

    // Switch to evidence.
    await page.getByTestId("mobile-tab-evidence").click();
    await expect(page.getByTestId("evidence-panel")).toBeVisible();

    // Composer stays within the viewport and fixed at the bottom of the chat view.
    await page.getByTestId("mobile-tab-chat").click();
    await expect(page.getByTestId("composer")).toBeVisible();
    const composerBox = await page.getByTestId("composer").boundingBox();
    expect(composerBox).not.toBeNull();
    if (composerBox) {
      expect(composerBox.y + composerBox.height, "composer below safe area").toBeLessThanOrEqual(844);
    }
    await expectNoHorizontalOverflow(page);
    await expectNoVerticalOverlap(page);
    await page.screenshot({ path: "tests/e2e/screenshots/learning-workspace-390.png", fullPage: true });
    check();
  });
});

test.describe("Learning workspace :: primary flows", () => {
  test("keyboard/touch primary flows change state without navigating", async ({ page }) => {
    const check = watchConsole(page);
    await openWorkspace(page);

    // Select a knowledge point.
    await page.getByTestId("map-node").first().click();
    await expect(page.getByTestId("map-node").first()).toHaveAttribute("aria-current", "true");

    // Progressive help controls are reachable (they hand off to chat).
    await expect(page.locator('[data-help-level="hint"]')).toBeVisible();

    // Start voice → edit the transcript (editing stays local; only confirm navigates).
    await page.getByTestId("voice-input").click();
    await expect(page.getByTestId("transcript-review")).toBeVisible();
    await page
      .getByTestId("transcript-review")
      .locator("textarea")
      .fill("灵敏度是在真有病的人里检测能找出的比例，阳性预测值是在阳性者里真有病者的比例。");
    await expect(page.getByTestId("transcript-review")).toBeVisible();
    await page.getByTestId("transcript-review").getByRole("button", { name: /取消|Cancel/ }).click();
    await expect(page.getByTestId("transcript-review")).toBeHidden();

    // Open source detail → switches to the evidence panel.
    await page.getByTestId("open-source-detail").click();
    await expect(page.getByTestId("evidence-panel")).toBeVisible();
    await expect(page.getByTestId("model-identity")).toBeVisible();

    // Challenge action is reachable.
    await expect(page.getByTestId("challenge-reassess")).toBeVisible();
    await expectNoHorizontalOverflow(page);
    check();
  });
});

test.describe("Learning workspace :: chat handoff", () => {
  test("text send stores a handoff and prefills the real chat composer", async ({ page }) => {
    const check = watchConsole(page);
    await openWorkspace(page);

    const learnerMessage = "新的迁移例子：A/B 实验里，先验影响我们对效应的相信程度。";
    await page.getByTestId("composer").locator("textarea").fill(learnerMessage);
    await page.getByTestId("send-message").click();

    // Same session in the existing chat, composer prefilled — never auto-sent.
    await page.waitForURL(`**/home/path-001`, { timeout: 20000 });
    await expect(page.getByRole("button", { name: /Mastery Path/i })).toBeVisible();
    await expect(chatComposer(page)).toHaveValue(learnerMessage);
    // Nothing was sent: the empty session still has no messages.
    await expect(page.locator("[data-turn-key]")).toHaveCount(0);
    check();
  });

  test("confirmed voice transcript hands off to the chat composer", async ({ page }) => {
    const check = watchConsole(page);
    await openWorkspace(page);

    const transcript = "灵敏度是在真有病的人里检测能找出的比例，阳性预测值是在阳性者里真有病者的比例。";
    await page.getByTestId("voice-input").click();
    await expect(page.getByTestId("transcript-review")).toBeVisible();
    await page.getByTestId("transcript-review").locator("textarea").fill(transcript);
    await page.getByTestId("confirm-transcript").click();

    await page.waitForURL(`**/home/path-001`, { timeout: 20000 });
    await expect(page.getByRole("button", { name: /Mastery Path/i })).toBeVisible();
    await expect(chatComposer(page)).toHaveValue(transcript);
    check();
  });

  test("progressive help request hands off to the chat composer", async ({ page }) => {
    const check = watchConsole(page);
    await openWorkspace(page);

    await page.locator('[data-help-level="hint"]').click();

    await page.waitForURL(`**/home/path-001`, { timeout: 20000 });
    await expect(page.getByRole("button", { name: /Mastery Path/i })).toBeVisible();
    // The draft is the learner-confirmable help request, not a sent message.
    await expect(chatComposer(page)).toHaveValue(/hint/i);
    await expect(page.locator("[data-turn-key]")).toHaveCount(0);
    check();
  });

  test("a stale handoff is consumed exactly once and never replays", async ({ page }) => {
    const check = watchConsole(page);
    await openWorkspace(page);

    await page.getByTestId("composer").locator("textarea").fill("第一次草稿");
    await page.getByTestId("send-message").click();
    await page.waitForURL(`**/home/path-001`, { timeout: 20000 });
    await expect(chatComposer(page)).toHaveValue("第一次草稿");

    // Reload the same chat page: the handoff slot was consumed, so the composer
    // must be empty again rather than replaying the draft.
    await page.reload();
    await expect(page.getByRole("button", { name: /Mastery Path/i })).toBeVisible({ timeout: 20000 });
    await expect(chatComposer(page)).toHaveValue("");
    check();
  });
});
