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

/**
 * Sign in through the real form, so the form itself is on the test path.
 *
 * Every step waits for its target first. The auth pages are client-rendered
 * behind <Suspense>, so the server sends a fallback and the fields appear only
 * once the tree mounts; filling without waiting races that mount and fails
 * intermittently. The label patterns accept both languages because the runner
 * may have either language persisted from an earlier test.
 */
async function signIn(page: Page, username: string, password: string, path = "/login") {
  await page.goto(path);
  const user = page.getByLabel(/email or username|نام کاربری|ایمیل/i);
  await user.waitFor({ state: "visible", timeout: 30_000 });
  await user.fill(username);

  const pass = page.getByLabel(/^password|گذرواژه|رمز/i);
  await pass.waitFor({ state: "visible", timeout: 30_000 });
  await pass.fill(password);

  const submit = page.getByRole("button", { name: /^sign in|signing in|ورود|در حال/i });
  await submit.waitFor({ state: "visible", timeout: 30_000 });
  await submit.click();
}

/**
 * Assert the login actually succeeded.
 *
 * Without this, a failed sign-in surfaces as whatever the *next* assertion
 * expected, which is why three tests kept reporting "text not visible" when the
 * real problem was that nobody was signed in. The surface text is included
 * because that is what distinguishes a rejected credential from a broken page.
 */
async function expectSignedIn(page: Page, { from }: { from?: string } = {}) {
  // Both sign-in screens count as "still on the form": `/admin/login` starts
  // with `/admin`, not `/login`, so the original check passed instantly for the
  // admin entrance without proving anything. Naming the screen explicitly is
  // what makes the assertion mean the same thing on both.
  const isForm = (pathname: string) =>
    pathname === "/login" || pathname === "/admin/login";
  // Wait for the form to be left *and* to land somewhere that is not another
  // sign-in screen. `router.replace` from /admin/login goes to /admin/users,
  // which may bounce to /login when the session did not stick - that is a
  // failed sign-in, not a success.
  try {
    await page.waitForURL((url) => !isForm(url.pathname), { timeout: 30_000 });
  } catch {
    const body = await page.locator("body").innerText();
    throw new Error(
      `sign-in did not leave ${from ?? "the form"} (now at ${new URL(page.url()).pathname}). Page says: ${body.slice(0, 300)}`,
    );
  }
  // Report where it landed, so a later assertion failure is self-explanatory.
  const landed = new URL(page.url()).pathname;
  if (isForm(landed)) {
    throw new Error(`sign-in bounced back to ${landed}`);
  }
  return landed;
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
    const formField = page.getByLabel(/email or username|نام کاربری|ایمیل/i);
    // `count()` returns immediately; waiting is what distinguishes "not there
    // yet" from "not there". The client tree mounts after the Suspense
    // fallback, so this has to wait rather than sample once.
    try {
      await formField.first().waitFor({ state: "visible", timeout: 30_000 });
    } catch {
      const body = await page.locator("body").innerText();
      throw new Error(`username field never appeared; body: ${body.slice(0, 300)}`);
    }
    const fieldCount = await formField.count();
    if (fieldCount === 0) {
      const body = await page.locator("body").innerText();
      throw new Error(`no labelled username field; body starts: ${body.slice(0, 300)}`);
    }
    await expect(formField.first()).toBeVisible();

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
    // The wordmark is the *second* `img[alt=""]` in the document: the panel's
    // own decorative mark comes first and is inside the element that is now
    // display:none. `.first()` therefore selected a hidden image and failed
    // while the compact wordmark was on screen the whole time.
    await expect(page.locator("img[alt='']:visible").first()).toBeVisible();
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

  // Diagnostic first: when the session tests fail, this says *where* the
  // browser ends up and what it can see, instead of leaving the next test to
  // report a missing element three steps downstream. It also proves the
  // browser and curl disagree for a reason, if they do.
  test("the browser can hold a session at all", async ({ page, context }) => {
    await signIn(page, ADMIN_USER, ADMIN_PASS, "/admin/login");
    const landed = await expectSignedIn(page, { from: "/admin/login" });
    const cookies = await context.cookies();
    const names = cookies.map((c) => `${c.name}@${c.domain}${c.path}`).join(",");
    const html = await page.evaluate(() => document.body.innerText.slice(0, 200));
    throw new Error(
      `landed=${landed} cookies=[${names}] body=${html.replace(/\s+/g, " ").slice(0, 160)}`,
    );
  });

  test("a signed-in administrator reaches the admin panel", async ({ page }) => {
    await signIn(page, ADMIN_USER, ADMIN_PASS, "/admin/login");
    await expectSignedIn(page);

    // The landing page must render its real entry rather than an invented
    // dashboard: user management is the one surface Phase 1 built.
    await expect(
      page.getByRole("link", { name: /users|کاربران/i }).first(),
    ).toBeVisible({ timeout: 20_000 });
  });

  test("direct navigation and refresh survive on an admin route", async ({ page }) => {
    await signIn(page, ADMIN_USER, ADMIN_PASS, "/admin/login");
    await expectSignedIn(page);

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
      await expectSignedIn(page);

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
