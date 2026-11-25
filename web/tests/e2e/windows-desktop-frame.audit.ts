import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { sourceModuleInventory } from "./fixtures/modules";

const WINDOWS_DESKTOP_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 OpenDeepTutor/1.7.4 (Windows; x64)";
const MACOS_DESKTOP_UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 OpenDeepTutor/1.7.4 (macOS; arm64)";
const CHROME_WINDOWS_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36";

type FrameTheme = "snow" | "light" | "dark" | "glass";

const EMPTY_CATALOG_SERVICES = Object.fromEntries(
  ["llm", "task", "embedding", "search", "tts", "stt", "imagegen", "videogen"].map(
    (service) => [
      service,
      { active_profile_id: null, active_model_id: null, profiles: [] },
    ],
  ),
);

const EXPECTED_SHELL_RGB: Record<FrameTheme, string> = {
  snow: "rgb(247, 247, 248)",
  light: "rgb(245, 242, 234)",
  dark: "rgb(23, 23, 25)",
  glass: "rgb(14, 13, 26)",
};

async function openMockedContext(
  browser: Browser,
  options: {
    userAgent: string;
    viewport: { width: number; height: number };
    theme?: FrameTheme;
  },
): Promise<{ context: BrowserContext; page: Page }> {
  const theme = options.theme ?? "snow";
  const context = await browser.newContext({
    userAgent: options.userAgent,
    viewport: options.viewport,
  });
  const page = await context.newPage();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript((selectedTheme: FrameTheme) => {
    localStorage.setItem("deeptutor.ui-layout", "modern");
    localStorage.setItem("deeptutor-language", "en");
    localStorage.setItem("deeptutor-theme", selectedTheme);
  }, theme);

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (payload: unknown) => route.fulfill({ json: payload });
    if (path === "/api/modules") return json(sourceModuleInventory);
    if (path === "/api/auth/status") {
      return json({ enabled: false, authenticated: true, is_admin: true, preset: null });
    }
    if (path === "/api/settings" || path === "/api/settings/ui") {
      return json({
        ui: {
          theme,
          language: "en",
          response_language: "en",
          code_block_theme: "github",
          code_block_show_line_numbers: true,
          code_block_wrap_long_lines: true,
        },
        catalog: { version: 1, connections: [], services: EMPTY_CATALOG_SERVICES },
        providers: { llm: [] },
        connection_targets: [],
      });
    }
    if (path === "/api/settings/readiness") {
      return json({
        schema_version: "deeptutor.settings-readiness/v2",
        ok: true,
        summary: {},
        rows: [],
        notices: [],
      });
    }
    if (path === "/api/settings/draft") return json({ draft: null });
    if (path === "/api/settings/chat-response-timeout") return json({ chat_response_timeout: 300 });
    if (path === "/api/settings/chat-starters") {
      return json({
        settings: { trace_count: 5, ask_hint_enabled: true },
        bounds: { trace_count: { min: 1, max: 50 } },
      });
    }
    if (path === "/api/system/status") return json({ backend: { status: "online" } });
    if (path === "/api/settings/llm-options" || path.includes("llm/options")) {
      return json({ options: [], active: null });
    }
    if (path === "/api/settings/workspace/resources") {
      return json({ skills: [], mcp: [], knowledge_bases: [] });
    }
    if (path === "/api/settings/workspace/registrations") return json({ workspaces: [] });
    if (path === "/api/settings/page-customization") {
      return json({
        chat: {
          hidden_modes: [],
          controls: {
            skills: true,
            mcp: true,
            partners: true,
            preferences: true,
            voice: true,
          },
          starters: {},
        },
        learning: { hidden_features: [] },
      });
    }
    if (path === "/api/capabilities/registered") return json({ capabilities: ["chat"] });
    if (path === "/api/sessions") return json({ sessions: [] });
    if (
      path === "/api/mastery-paths/topics/index" ||
      path === "/api/reading/workspaces/index" ||
      path === "/api/space/mcp/servers" ||
      path === "/api/partner-groups" ||
      path.includes("partners") ||
      path.includes("personas")
    ) {
      return json([]);
    }
    if (path === "/api/task-board/events") {
      return route.fulfill({ status: 200, contentType: "text/event-stream", body: "" });
    }
    if (path === "/api/dashboard/suggestions") return json({ suggestions: [] });
    if (path === "/api/task-board") return json({ tasks: [] });
    if (path.includes("tools")) return json({ tools: [] });
    if (path.includes("knowledge")) return json({ knowledge_bases: [] });
    if (path.includes("folders")) return json({ folders: [] });
    if (path.includes("tags")) return json({ tags: [] });
    if (path.includes("activities")) return json({ activities: [] });
    if (path.includes("settings")) return json({});
    return route.fulfill({ status: 404, json: {} });
  });

  return { context, page };
}

test.describe("Windows desktop shell and card frame", () => {
  for (const theme of ["snow", "light", "dark", "glass"] as const) {
    test(`/chat applies the Windows desktop frame for the ${theme} palette`, async ({
      browser,
    }) => {
      const { context, page } = await openMockedContext(browser, {
        userAgent: WINDOWS_DESKTOP_UA,
        viewport: { width: 1440, height: 900 },
        theme,
      });

      try {
        await page.goto("/chat", { waitUntil: "domcontentloaded" });
        await expect(page.locator("html")).toHaveAttribute("data-desktop-frame", "windows");

        const shell = page.locator("[data-desktop-shell]");
        const sidebarAside = page.locator("[data-desktop-sidebar] aside").first();
        const main = page.locator("[data-desktop-main]");

        await expect(shell).toBeVisible({ timeout: 15000 });
        await expect(sidebarAside).toBeVisible({ timeout: 15000 });
        await expect(main).toBeVisible({ timeout: 15000 });

        await expect
          .poll(() => shell.evaluate((el) => getComputedStyle(el).backgroundColor))
          .toBe(EXPECTED_SHELL_RGB[theme]);

        await expect
          .poll(() =>
            sidebarAside.evaluate((el) => {
              const s = getComputedStyle(el);
              return { bg: s.backgroundColor, borderRight: s.borderRightWidth };
            }),
          )
          .toEqual({ bg: "rgba(0, 0, 0, 0)", borderRight: "0px" });

        await expect
          .poll(() =>
            main.evaluate((el) => {
              const s = getComputedStyle(el);
              return {
                radius: s.borderTopLeftRadius,
                borderTop: s.borderTopWidth,
                borderLeft: s.borderLeftWidth,
              };
            }),
          )
          .toEqual({ radius: "16px", borderTop: "1px", borderLeft: "1px" });

        if (theme === "glass") {
          const bodyBgImage = await page.evaluate(() => getComputedStyle(document.body).backgroundImage);
          expect(bodyBgImage).toContain("radial-gradient");
        }

        if (theme === "snow" || theme === "dark") {
          await page.screenshot({ path: test.info().outputPath(`chat-${theme}.png`) });
        }

        if (theme === "snow") {
          await page.getByRole("button", { name: "Collapse sidebar", exact: true }).click();
          const rail = page.locator("[data-desktop-sidebar] aside.dt-rail");
          await expect(rail).toBeVisible();
          await expect
            .poll(() =>
              rail.evaluate((el) => {
                const s = getComputedStyle(el);
                return {
                  bg: s.backgroundColor,
                  borderRight: s.borderRightWidth,
                  transitionProperty: s.transitionProperty,
                  width: s.width,
                };
              }),
            )
            .toEqual({
              bg: "rgba(0, 0, 0, 0)",
              borderRight: "0px",
              transitionProperty: "width",
              width: "60px",
            });
        }
      } finally {
        await context.close();
      }
    });
  }

  for (const theme of ["snow", "dark", "glass"] as const) {
    test(`/settings participates in the Windows desktop frame for ${theme}`, async ({
      browser,
    }) => {
      const { context, page } = await openMockedContext(browser, {
        userAgent: WINDOWS_DESKTOP_UA,
        viewport: { width: 1440, height: 900 },
        theme,
      });

      try {
        await page.goto("/settings/general", { waitUntil: "domcontentloaded" });
        await expect(page.locator("html")).toHaveAttribute("data-desktop-frame", "windows");

        const shell = page.locator("[data-settings-shell][data-desktop-shell]");
        const sidebar = page.locator("aside[data-desktop-sidebar]");
        const main = page.locator("main[data-desktop-main]");

        await expect(shell).toBeVisible({ timeout: 15000 });
        await expect(sidebar).toBeVisible({ timeout: 15000 });
        await expect(main).toBeVisible({ timeout: 15000 });

        await expect
          .poll(() =>
            shell.evaluate((el) => {
              const s = getComputedStyle(el);
              return { bg: s.backgroundColor, zIndex: s.zIndex };
            }),
          )
          .toEqual({ bg: EXPECTED_SHELL_RGB[theme], zIndex: "40" });

        await expect
          .poll(() =>
            sidebar.evaluate((el) => {
              const s = getComputedStyle(el);
              return { bg: s.backgroundColor, borderRight: s.borderRightWidth };
            }),
          )
          .toEqual({ bg: "rgba(0, 0, 0, 0)", borderRight: "0px" });

        await expect
          .poll(() =>
            main.evaluate((el) => {
              const s = getComputedStyle(el);
              return {
                radius: s.borderTopLeftRadius,
                borderTop: s.borderTopWidth,
                borderLeft: s.borderLeftWidth,
              };
            }),
          )
          .toEqual({ radius: "16px", borderTop: "1px", borderLeft: "1px" });

        if (theme === "dark") {
          await page.screenshot({ path: test.info().outputPath("settings-dark.png") });
        }
      } finally {
        await context.close();
      }
    });
  }

  for (const [label, userAgent] of [
    ["desktop browser", CHROME_WINDOWS_UA],
    ["macOS desktop client", MACOS_DESKTOP_UA],
  ] as const) {
    test(`leaves the frame unrounded for ${label}`, async ({ browser }) => {
      const { context, page } = await openMockedContext(browser, {
        userAgent,
        viewport: { width: 1440, height: 900 },
        theme: "snow",
      });

      try {
        await page.goto("/chat", { waitUntil: "domcontentloaded" });
        const frame = await page.locator("html").getAttribute("data-desktop-frame");
        expect(frame).toBeNull();
        const main = page.locator("[data-desktop-main]");
        await expect(main).toBeVisible({ timeout: 15000 });
        await expect(main).toHaveCSS("border-top-left-radius", "0px");
      } finally {
        await context.close();
      }
    });
  }

  test("omits the desktop card radius below the 768px breakpoint on mobile viewports", async ({
    browser,
  }) => {
    const { context, page } = await openMockedContext(browser, {
      userAgent: WINDOWS_DESKTOP_UA,
      viewport: { width: 390, height: 844 },
      theme: "snow",
    });

    try {
      await page.goto("/chat", { waitUntil: "domcontentloaded" });
      await expect(page.locator("html")).toHaveAttribute("data-desktop-frame", "windows");
      const main = page.locator("[data-desktop-main]");
      await expect(main).toBeVisible({ timeout: 15000 });
      await expect(main).toHaveCSS("border-top-left-radius", "0px");
    } finally {
      await context.close();
    }
  });
});
