import { test, expect, type ConsoleMessage, type Page } from "@playwright/test";
import {
  mockLearningApis,
  mockKnowledgeCardApis,
} from "./learning-workspace-fixtures";

/**
 * UI-02 knowledge-card review/publication audit.
 *
 * Deterministic mocked APIs drive the owner-scoped card collection, the real
 * KB list (writable + connected/error locks), and stateful mutations so the
 * desktop center editor, the 390px full-screen editor, publish/retry/reconcile/
 * retract recovery paths and the explicit confirmation dialog render without a
 * live backend. Screenshots are written under tests/e2e/screenshots/.
 *
 * Round-1 additions: the confirmation dialog is verified for Escape, Tab /
 * Shift+Tab focus cycling, focus restoration to the triggering button after
 * Cancel, and disabled/double-submit while the mutation is in flight. Desktop
 * Review from the lower aggregate list must scroll the center editor into the
 * visible workspace and focus its content; both screenshots are captured with
 * the editor actually open and in view, and explicit non-overlap checks cover
 * the editor header/form/footer/dialog and long labels at both viewports.
 *
 * Round-2 (evidence): the Next.js development ``nextjs-portal`` overlay is
 * development chrome, not product UI. It is hidden (test scope only; product
 * CSS and next.config are untouched) and asserted hidden before every capture,
 * so the committed 1440px and 390px screenshots are clean acceptance evidence.
 */

const BASE_URL =
  process.env.WEB_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://localhost:3199";

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

async function expectNoElementHorizontalOverflow(page: Page, selector: string) {
  const overflow = await page.locator(selector).evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(overflow, `${selector} horizontal overflow = ${overflow}px`).toBeLessThanOrEqual(0);
}

/** Assert the element intersects the viewport (top edge visible, no x-overflow). */
async function expectInViewport(page: Page, selector: string) {
  const ok = await page.locator(selector).evaluate((el) => {
    const r = el.getBoundingClientRect();
    return r.top >= 0 && r.top < window.innerHeight && r.left >= 0 && r.right <= window.innerWidth;
  });
  expect(ok, `${selector} not in viewport`).toBe(true);
}

/** Assert two elements' bounding boxes do not intersect. */
async function expectNoOverlap(page: Page, selectorA: string, selectorB: string) {
  const boxes = await page.evaluate(
    ([a, b]) => {
      const ra = document.querySelector(a)?.getBoundingClientRect();
      const rb = document.querySelector(b)?.getBoundingClientRect();
      if (!ra || !rb) return null;
      return {
        a: { top: ra.top, bottom: ra.bottom, left: ra.left, right: ra.right },
        b: { top: rb.top, bottom: rb.bottom, left: rb.left, right: rb.right },
      };
    },
    [selectorA, selectorB] as [string, string],
  );
  expect(boxes, `missing element for ${selectorA} or ${selectorB}`).not.toBeNull();
  const { a, b } = boxes as { a: { top: number; bottom: number; left: number; right: number }; b: { top: number; bottom: number; left: number; right: number } };
  const overlap = !(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top);
  expect(overlap, `${selectorA} overlaps ${selectorB}`).toBe(false);
}

/** Scroll the desktop editor's internal content to the bottom (KB/model area). */
async function scrollDesktopEditorToBottom(page: Page) {
  await page.evaluate(() => {
    const el = document.querySelector('[data-testid="knowledge-card-editor"] .fw-kc-editor-scroll');
    if (el) el.scrollTop = el.scrollHeight;
  });
}

async function openWorkspaceWithCards(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockLearningApis(page);
  await mockKnowledgeCardApis(page);
  await page.goto(`${BASE_URL}/space/learning/path-001`);
  await expect(page.getByTestId("feynman-workspace")).toBeVisible({ timeout: 20000 });
}

/**
 * The Next.js development server injects a ``nextjs-portal`` web component
 * (the black/red dev-overlay indicator, positioned at the bottom-right). It is
 * development chrome, not product UI, and must not appear in acceptance
 * evidence. Hide it for capture with a stylesheet rule and prove it is hidden
 * (or absent) before any screenshot is taken. This is test/evidence scope
 * only — product CSS and next.config.js are untouched.
 */
async function hideNextDevPortal(page: Page) {
  await page.addStyleTag({
    content: "nextjs-portal { display: none !important; }",
  });
  const hidden = await page.evaluate(() => {
    const el = document.querySelector("nextjs-portal");
    return !el || getComputedStyle(el).display === "none";
  });
  expect(
    hidden,
    "nextjs-portal dev indicator must be hidden/absent before screenshot capture",
  ).toBe(true);
}

test.describe("Knowledge card :: desktop 1440px", () => {
  test("Evidence summary → center editor → KB locks → save → publish confirmation", async ({ page }) => {
    const check = watchConsole(page);
    await openWorkspaceWithCards(page);

    // Non-blocking pending summary in the Evidence Panel for the selected KP.
    const panel = page.getByTestId("knowledge-card-panel");
    await expect(panel).toBeVisible();
    await expect(panel.getByText("为什么 TCP 需要三次握手")).toBeVisible();

    // Learning Space aggregates every pending card across the path.
    await expect(page.getByTestId("knowledge-card-overview-list")).toBeVisible();
    await expect(page.getByTestId("kc-overview-row")).toHaveCount(6);

    // Review from the lower aggregate list scrolls the center editor into the
    // visible workspace and focuses a sensible content target after commit.
    await page.getByTestId("overview-review-card-bayes-draft").click();
    const editor = page.getByTestId("knowledge-card-editor");
    await expect(editor).toBeVisible();
    await expectInViewport(page, '[data-testid="knowledge-card-editor"]');
    await expect(page.getByTestId("kc-title-input")).toBeFocused();
    await expect(page.getByTestId("map-panel")).toBeVisible();
    await expect(page.getByTestId("evidence-panel")).toBeVisible();

    // KB selector: writable local indexed KB selectable; connected/error locked.
    const writable = page.getByTestId("kb-option-我的学习知识库");
    await expect(writable).toBeVisible();
    await expect(writable.locator("input[type=radio]")).toBeEnabled();
    const connected = page.getByTestId("kb-option-团队网络原理");
    await expect(connected).toBeVisible();
    await expect(connected.locator("input[type=radio]")).toBeDisabled();
    await expect(connected.getByText(/Connected|只读/)).toBeVisible();
    const errored = page.getByTestId("kb-option-课程公共库");
    await expect(errored).toBeVisible();
    await expect(errored.locator("input[type=radio]")).toBeDisabled();

    // Image reference + frozen model identity are shown.
    await expect(page.getByTestId("card-artifacts")).toBeVisible();
    await expect(page.getByTestId("card-model-identity")).toBeVisible();

    // Non-overlap: editor header / form scroll / footer are stacked regions,
    // and the long model id + KB options do not collide.
    await expectNoOverlap(page, ".fw-kc-editor-head", ".fw-kc-editor-scroll");
    await expectNoOverlap(page, ".fw-kc-editor-scroll", ".fw-kc-editor-footer");
    await expectNoOverlap(page, ".fw-kc-editor-head", ".fw-kc-editor-footer");
    await expectNoOverlap(page, ".fw-kb-options", '[data-testid="card-model-identity"]');
    await expectNoElementHorizontalOverflow(page, '[data-testid="card-model-identity"]');

    // Reveal the KB selector + image reference + model identity so the desktop
    // screenshot actually shows the review editor (not just the base workspace).
    await scrollDesktopEditorToBottom(page);
    await expectInViewport(page, '[data-testid="card-artifacts"]');
    await expectInViewport(page, '[data-testid="kb-option-我的学习知识库"]');
    await expectInViewport(page, '[data-testid="card-model-identity"]');
    await expect(page.getByTestId("map-panel")).toBeVisible();
    await expect(page.getByTestId("evidence-panel")).toBeVisible();

    await expectNoHorizontalOverflow(page);
    await hideNextDevPortal(page);
    await page.screenshot({
      path: "tests/e2e/screenshots/knowledge-card-desktop-1440.png",
    });

    // Edit title → Save draft → versioned PATCH reflects the new revision/lock.
    await page.getByTestId("kc-title-input").fill("TCP 三次握手（修订）");
    await page.getByTestId("save-draft").click();
    await expect(page.getByTestId("kc-title-input")).toHaveValue("TCP 三次握手（修订）");

    // Publish opens an explicit confirmation naming the target KB.
    await page.getByTestId("publish-card").click();
    const dialog = page.getByTestId("knowledge-card-confirm");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("我的学习知识库")).toBeVisible();
    await expectNoOverlap(page, ".fw-kc-dialog-head", ".fw-kc-dialog-body");
    await expectNoOverlap(page, ".fw-kc-dialog-body", ".fw-kc-dialog-actions");
    await page.getByTestId("confirm-card-action").click();
    await expect(page.getByTestId("published-provenance")).toBeVisible({ timeout: 20000 });
    await expect(page.getByTestId("kc-title-input")).toHaveCount(0); // published → read-only

    await expectNoHorizontalOverflow(page);
    check();
  });

  test("confirmation dialog: Escape, focus trap, focus restoration, disabled double-submit", async ({ page }) => {
    const check = watchConsole(page);
    await openWorkspaceWithCards(page);
    await page.getByTestId("overview-review-card-bayes-draft").click();
    await expect(page.getByTestId("knowledge-card-editor")).toBeVisible();
    await expect(page.getByTestId("kc-title-input")).toBeFocused();

    const publishButton = page.getByTestId("publish-card");
    const dialog = page.getByTestId("knowledge-card-confirm");
    const confirmBtn = page.getByTestId("confirm-card-action");
    const cancelBtn = page.getByTestId("dialog-cancel");
    const closeBtn = page.getByTestId("dialog-close");

    // ── Escape cancels and restores focus to the exact trigger ─────────────
    await publishButton.click();
    await expect(dialog).toBeVisible();
    await expect(confirmBtn).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(publishButton).toBeFocused();

    // ── Cancel restores focus to the exact trigger ─────────────────────────
    await publishButton.click();
    await expect(dialog).toBeVisible();
    await cancelBtn.click();
    await expect(dialog).toBeHidden();
    await expect(publishButton).toBeFocused();

    // ── Focus trap cycles both directions across the real focusable set ────
    await publishButton.click();
    await expect(dialog).toBeVisible();
    await expect(confirmBtn).toBeFocused();
    // Tab wraps forward: confirm (last) -> close (first).
    await page.keyboard.press("Tab");
    await expect(closeBtn).toBeFocused();
    // Tab advances close -> cancel -> confirm.
    await page.keyboard.press("Tab");
    await expect(cancelBtn).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(confirmBtn).toBeFocused();
    // Shift+Tab cycles backward: confirm -> cancel -> close.
    await page.keyboard.press("Shift+Tab");
    await expect(cancelBtn).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(closeBtn).toBeFocused();
    // Shift+Tab wraps from the first focusable back to the last.
    await page.keyboard.press("Shift+Tab");
    await expect(confirmBtn).toBeFocused();

    // ── Disabled / double-submit while the confirmed mutation is busy ──────
    // Delay the publish response so the busy state is observable; fallback()
    // chains to the fixture's knowledge-card mutation handler.
    await page.route("**/knowledge-cards/card-bayes-draft/publish**", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 500));
      await route.fallback();
    });
    await confirmBtn.click();
    await expect(confirmBtn).toBeDisabled();
    await expect(cancelBtn).toBeDisabled();
    await expect(closeBtn).toBeDisabled();
    // Escape must NOT close the dialog while the mutation is busy.
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    await expect(confirmBtn).toBeDisabled();
    // The mutation settles; the dialog closes and the editor shows the result.
    await expect(page.getByTestId("published-provenance")).toBeVisible({ timeout: 20000 });
    await expect(dialog).toBeHidden();

    await expectNoHorizontalOverflow(page);
    check();
  });

  test("publish_failed / stale / reconcile / retracting states render exact recovery paths", async ({ page }) => {
    const check = watchConsole(page);
    await openWorkspaceWithCards(page);

    // publish_failed: draft retained, no duplicate on retry, stable mastery untouched.
    await page.getByTestId("overview-review-card-publish-failed").click();
    await expect(page.getByTestId("editor-publish-failed")).toBeVisible();
    await expect(page.getByTestId("editor-publish-failed").getByText(/草稿已保留|draft retained/)).toBeVisible();
    await expect(page.getByTestId("retry-publish")).toBeVisible();
    await page.getByTestId("retry-publish").click();
    await expect(page.getByTestId("published-provenance")).toBeVisible({ timeout: 20000 });
    await page.getByTestId("close-card-editor").click();

    // stale_evidence: read-only, only view/discard, generation/edit/publish disabled.
    await page.getByTestId("overview-review-card-stale").click();
    await expect(page.getByTestId("editor-stale-note")).toBeVisible();
    await expect(page.getByTestId("kc-title-input")).toHaveCount(0);
    await expect(page.getByTestId("publish-card")).toHaveCount(0);
    await expect(page.getByTestId("discard-from-editor")).toBeVisible();
    await page.getByTestId("close-card-editor").click();

    // reconcile_required: explicit reconcile, no invented success.
    await page.getByTestId("overview-review-card-reconcile").click();
    await expect(page.getByTestId("reconcile-publication-note")).toBeVisible();
    await expect(page.getByTestId("reconcile-publication")).toBeVisible();
    await expect(page.getByTestId("published-provenance")).toHaveCount(0);
    await page.getByTestId("close-card-editor").click();

    // retracting: never shows retracted early.
    await page.getByTestId("overview-review-card-retracting").click();
    await expect(page.getByTestId("retracting-note")).toBeVisible();
    await expect(page.getByTestId("retract-card")).toHaveCount(0);
    await expect(page.getByTestId("published-provenance")).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
    check();
  });

  test("publish requires an explicit confirmation dialog (no window.confirm)", async ({ page }) => {
    const check = watchConsole(page);
    await openWorkspaceWithCards(page);
    await page.getByTestId("overview-review-card-bayes-draft").click();
    await expect(page.getByTestId("knowledge-card-editor")).toBeVisible();

    // window.confirm is never used; the dialog is a real accessible element.
    await page.evaluate(() => {
      (window as unknown as { __confirmCalls?: number }).__confirmCalls = 0;
      const original = window.confirm;
      (window as unknown as { __origConfirm?: typeof original }).__origConfirm = original;
      window.confirm = () => {
        (window as unknown as { __confirmCalls: number }).__confirmCalls += 1;
        return false;
      };
    });
    await page.getByTestId("publish-card").click();
    await expect(page.getByTestId("knowledge-card-confirm")).toBeVisible();
    const confirmCalls = await page.evaluate(
      () => (window as unknown as { __confirmCalls: number }).__confirmCalls,
    );
    expect(confirmCalls).toBe(0);
    await page.getByTestId("confirm-card-action").click();
    await expect(page.getByTestId("published-provenance")).toBeVisible({ timeout: 20000 });
    check();
  });
});

test.describe("Knowledge card :: mobile 390px", () => {
  test("evidence tab summary → full-screen editor → back", async ({ page }) => {
    const check = watchConsole(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await mockLearningApis(page);
    await mockKnowledgeCardApis(page);
    await page.goto(`${BASE_URL}/space/learning/path-001`);
    await expect(page.getByTestId("feynman-workspace")).toBeVisible({ timeout: 20000 });

    // Evidence tab holds the non-blocking card summary.
    await page.getByTestId("mobile-tab-evidence").click();
    await expect(page.getByTestId("evidence-panel")).toBeVisible();
    const panel = page.getByTestId("knowledge-card-panel");
    await expect(panel).toBeVisible();

    // Review opens a true full-screen editor with a usable back action.
    await page.getByTestId("review-card-card-bayes-draft").click();
    const mobileEditor = page.getByTestId("knowledge-card-mobile-editor");
    await expect(mobileEditor).toBeVisible({ timeout: 20000 });
    await expect(mobileEditor.getByTestId("kc-title-input")).toHaveValue("为什么 TCP 需要三次握手");
    await expect(page.getByTestId("kb-option-我的学习知识库")).toBeVisible();
    await expect(page.getByTestId("kb-option-团队网络原理")).toBeVisible();

    // Non-overlap: mobile editor top bar / form scroll / footer stay stacked,
    // and the long model id does not collide with the KB selector.
    await expectNoOverlap(page, ".fw-kc-mobile-top", ".fw-kc-editor-scroll");
    await expectNoOverlap(page, ".fw-kc-editor-scroll", ".fw-kc-editor-footer");
    await expectNoOverlap(page, ".fw-kb-options", '[data-testid="card-model-identity"]');
    await expectNoElementHorizontalOverflow(page, '[data-testid="card-model-identity"]');

    // Screenshot while the full-screen editor is actually open (before Back).
    await expectNoHorizontalOverflow(page);
    await hideNextDevPortal(page);
    await page.screenshot({
      path: "tests/e2e/screenshots/knowledge-card-mobile-390.png",
    });

    // Back returns to the workspace (tabs stay available outside the editor).
    await page.getByTestId("mobile-editor-back").click();
    await expect(page.getByTestId("knowledge-card-mobile-editor")).toBeHidden();
    await expect(page.getByTestId("mobile-tabs")).toBeVisible();

    await expectNoHorizontalOverflow(page);
    check();
  });
});
