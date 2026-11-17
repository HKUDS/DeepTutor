import { expect, test, type Page } from "@playwright/test";

/**
 * Gate 1 of the Darsyar Phase 1 roadmap.
 *
 * `ROADMAP.md` line 327 asks for browser E2E over exactly these paths:
 * login, refresh / direct route, non-admin redirect, admin navigation and a
 * responsive shell. Everything here is something that cannot be established
 * without a real browser: rendering, hydration, layout and the middleware's
 * redirect behaviour as the browser experiences it.
 *
 * The middleware itself is unit-tested in `tests/proxy-policy.test.ts`. This
 * file proves those decisions actually reach the user.
 *
 * ---------------------------------------------------------------------------
 * Running
 * ---------------------------------------------------------------------------
 * Requires a reachable web instance and Playwright's chromium:
 *
 *   npx playwright install --with-deps chromium
 *   npm run build && npm run start &          # or: npm run dev
 *   WEB_BASE_URL=http://localhost:3000 \
 *     npx playwright test --project=phase1-shell
 *
 * `WEB_BASE_URL` defaults to http://localhost:3000 (see playwright.config.ts).
 *
 * Tests that need seeded accounts skip themselves when the seed is absent, so
 * a misconfigured run reports "skipped" rather than a false failure. Set
 * DEEPTUTOR_PHASE1_SEED=1 once the accounts below exist.
 */

const SEEDED = process.env.DEEPTUTOR_PHASE1_SEED === "1";
const ADMIN_USER = process.env.PHASE1_ADMIN_USER ?? "phase1-admin";
const ADMIN_PASS = process.env.PHASE1_ADMIN_PASS ?? "phase1-admin-pass";
const STUDENT_USER = process.env.PHASE1_STUDENT_USER ?? "phase1-student";
const STUDENT_PASS = process.env.PHASE1_STUDENT_PASS ?? "phase1-student-pass";

/** Sign in through the real form, so the form itself is on the test path. */
async function signIn(page: Page, username: string, password: string, path = "/login") {
  await page.goto(path);
  await page.getByLabel(/email or username|نام کاربری/i).fill(username);
  await page.getByLabel(/^password|گذرواژه/i).fill(password);
  await page.getByRole("button", { name: /^sign in|ورود$/i }).click();
}

/** Force Persian and LTR/RTL before any app code runs. */
async function useLanguage(page: Page, language: "fa" | "en") {
  await page.addInitScript((lang) => {
    localStorage.setItem("deeptutor-language", lang);
  }, language);
}

test.describe("public entry points", () => {
  test("the product presents itself as درسیار in metadata and on screen", async ({ page }) => {
    await page.goto("/login");
    // The tab title is generated from `metadata.title`, i.e. from the brand module.
    await expect(page).toHaveTitle(/درسیار|Darsyar/);
  });

  test("the login page renders a real, usable form", async ({ page }) => {
    await page.goto("/login");

    const username = page.getByLabel(/email or username|نام کاربری/i);
    await expect(username).toBeVisible();
    await expect(page.getByLabel(/^password|گذرواژه/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /^sign in|ورود$/i })).toBeEnabled();

    // Hydration proof: typing must reach React state. A shell-only render
    // accepts keystrokes into the DOM but the value would not stick through
    // the controlled component.
    await username.fill("someone@example.com");
    await expect(username).toHaveValue("someone@example.com");
  });

  test("the brand panel appears on desktop and is dropped on mobile", async ({ page }) => {
    // Desktop: two columns, the identity panel is visible.
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/login");
    // /login is a client-rendered page behind <Suspense>, so the server sends
    // the fallback. Waiting for a form control is what proves the components
    // mounted; asserting on `aside` alone races the hydration.
    await expect(page.getByLabel(/email or username|نام کاربری/i)).toBeVisible();
    const panel = page.locator("aside");
    await expect(panel).toHaveCount(1);

    // Report what the browser actually decided, rather than failing with a
    // bare "not visible". `hidden lg:flex` resolves by media query and CSS
    // order, and only the computed style can say which one won.
    const diag = await panel.evaluate((el) => {
      const cs = getComputedStyle(el as HTMLElement);
      return {
        display: cs.display,
        visibility: cs.visibility,
        width: (el as HTMLElement).getBoundingClientRect().width,
        innerWidth: window.innerWidth,
        matchesLg: window.matchMedia("(min-width: 1024px)").matches,
      };
    });
    if (diag.display === "none") {
      throw new Error(`panel display:none at ${diag.innerWidth}px (lg=${diag.matchesLg})`);
    }
    expect(diag.width).toBeGreaterThan(0);

    // Mobile: the panel is hidden and the compact wordmark takes over, so a
    // phone user still knows which product they opened.
    await page.setViewportSize({ width: 375, height: 812 });
    await expect(panel).toBeHidden();
    await expect(page.locator("img[alt='']").first()).toBeVisible();
  });

  test("Persian renders right-to-left and the shell mirrors", async ({ page }) => {
    await useLanguage(page, "fa");
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/login");

    // The i18n provider sets these on <html>; if that ever regresses, every
    // logical property in the app silently resolves to LTR.
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(page.locator("html")).toHaveAttribute("lang", /^fa/);
  });

  test("the admin sign-in is a separate entrance that says so", async ({ page }) => {
    await page.goto("/admin/login");
    await expect(page.getByRole("heading")).toBeVisible();
    await expect(page.getByLabel(/email or username|نام کاربری/i)).toBeVisible();
    // Reachable without a session: a sign-in page behind its own gate loops.
    await expect(page.getByRole("link")).toBeVisible();
  });
});

test.describe("session and authorisation", () => {
  test.skip(!SEEDED, "Needs seeded admin and student accounts.");

  test("a signed-in administrator reaches the admin panel", async ({ page }) => {
    await signIn(page, ADMIN_USER, ADMIN_PASS, "/admin/login");
    await page.waitForURL(/\/admin/, { timeout: 20_000 });

    // The landing page must render its real entry rather than an invented
    // dashboard: user management is the one surface Phase 1 built.
    await expect(
      page.getByRole("link", { name: /users|کاربران/i }).first(),
    ).toBeVisible({ timeout: 20_000 });
  });

  test("direct navigation and refresh survive on an admin route", async ({ page }) => {
    await signIn(page, ADMIN_USER, ADMIN_PASS, "/admin/login");
    await page.waitForURL(/\/admin/, { timeout: 20_000 });

    // Refresh is the case a client-only guard handles badly: the server must
    // still hand over the page rather than bouncing a valid session.
    await page.goto("/admin/users");
    await expect(page).toHaveURL(/\/admin\/users/, { timeout: 20_000 });
    await page.reload();
    await expect(page).toHaveURL(/\/admin\/users/, { timeout: 20_000 });
    // Prove it rendered, not merely that the URL survived.
    await expect(page.getByRole("heading").first()).toBeVisible({ timeout: 20_000 });
  });

  test("a signed-in student is redirected away from admin", async ({ page }) => {
    await signIn(page, STUDENT_USER, STUDENT_PASS);

    // Direct request: the middleware must refuse before the page renders.
    const response = await page.goto("/admin/users");
    await expect(page).not.toHaveURL(/\/admin\/users/);
    // Redirect, not a 404 and not a rendered admin shell.
    expect([200, 307, 308]).toContain(response?.status() ?? 200);
    await expect(page.locator("body")).not.toContainText(/user management|مدیریت کاربران/i);
  });

  test("a student is told why the admin sign-in refuses them", async ({ page }) => {
    await signIn(page, STUDENT_USER, STUDENT_PASS, "/admin/login");
    // Not a silent bounce: the screen must explain, because "wrong password"
    // and "not an administrator" are different problems.
    await expect(
      page.getByText(/administrator access|دسترسی مدیر/i),
    ).toBeVisible({ timeout: 20_000 });
  });

  test("an unauthenticated visitor never sees the admin shell", async ({ page }) => {
    await page.context().clearCookies();
    await page.goto("/admin/users");
    await expect(page).toHaveURL(/\/login|\/admin\/login/);
  });
});

test.describe("responsive shell", () => {
  test.skip(!SEEDED, "Needs a seeded account to open the shell.");

  for (const [label, viewport] of [
    ["mobile", { width: 375, height: 812 }],
    ["tablet", { width: 834, height: 1112 }],
    ["desktop", { width: 1440, height: 900 }],
  ] as const) {
    test(`the workspace shell has no horizontal overflow on ${label}`, async ({ page }) => {
      await useLanguage(page, "fa");
      await page.setViewportSize(viewport);
      await signIn(page, STUDENT_USER, STUDENT_PASS);
      await page.waitForURL((url) => !url.pathname.startsWith("/login"));

      // The single most common RTL layout failure: content wider than the
      // viewport, which leaks a horizontal scrollbar and clips the shell.
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    });
  }

  test("Persian chat shell renders without mixed-direction text", async ({ page }) => {
    await useLanguage(page, "fa");
    await page.setViewportSize({ width: 1280, height: 800 });
    await signIn(page, STUDENT_USER, STUDENT_PASS);
    await page.waitForURL((url) => !url.pathname.startsWith("/login"));

    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    // No untranslated English label in the Persian navigation rail.
    const body = await page.locator("body").innerText();
    expect(body).not.toMatch(/\bSettings\b|\bKnowledge Base\b|\bCo-Writer\b/);
  });
});
