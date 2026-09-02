import { expect, test } from "@playwright/test";

const BASE_URL = process.env.WEB_BASE_URL || "http://127.0.0.1:3300";

const surfaces = [
  ["Chat", "/chat"],
  ["Reading", "/reading"],
  ["Mastery", "/mastery"],
  ["Settings", "/settings"],
  ["Knowledge", "/knowledge-bases"],
  ["Co-Writer", "/co-writer"],
] as const;

const themes = ["snow", "light", "dark", "glass"] as const;
const languages = ["en", "zh"] as const;
const viewports = [
  ["mobile", { width: 390, height: 844 }],
  // A 1440 px desktop at 200% browser zoom exposes roughly 720 CSS pixels.
  ["desktop-200pct", { width: 720, height: 500 }],
  ["tablet", { width: 820, height: 1180 }],
  ["desktop", { width: 1440, height: 1000 }],
] as const;

for (const theme of themes) {
  for (const language of languages) {
    for (const [viewportName, viewport] of viewports) {
      test(`${theme}/${language}/${viewportName} keeps all primary surfaces usable`, async ({
        browser,
      }) => {
        const context = await browser.newContext({
          viewport,
          reducedMotion: "reduce",
        });
        await context.addInitScript(
          ({ selectedTheme, selectedLanguage }) => {
            localStorage.setItem("deeptutor-theme", selectedTheme);
            localStorage.setItem("deeptutor-language", selectedLanguage);
          },
          { selectedTheme: theme, selectedLanguage: language },
        );
        const page = await context.newPage();

        for (const [surface, path] of surfaces) {
          await test.step(surface, async () => {
            await page.goto(`${BASE_URL}${path}`, {
              waitUntil: "domcontentloaded",
            });
            await expect(page.locator("body")).toBeVisible();
            await page.waitForTimeout(250);

            const rootClasses = await page
              .locator("html")
              .getAttribute("class");
            if (theme === "snow") expect(rootClasses).toContain("theme-snow");
            if (theme === "dark") expect(rootClasses).toContain("dark");
            if (theme === "glass") {
              expect(rootClasses).toContain("dark");
              expect(rootClasses).toContain("theme-glass");
            }
            if (theme === "light") {
              expect(rootClasses || "").not.toMatch(
                /\bdark\b|\btheme-snow\b|\btheme-glass\b/,
              );
            }

            const layout = await page.evaluate(() => ({
              viewport: window.innerWidth,
              documentWidth: document.documentElement.scrollWidth,
              populatedPasswords: Array.from(
                document.querySelectorAll<HTMLInputElement>(
                  'input[type="password"]',
                ),
              ).filter((input) => input.value.length > 0).length,
              text: document.body.innerText,
            }));
            expect(
              layout.documentWidth,
              `${surface} overflows at ${theme}/${language}/${viewportName}`,
            ).toBeLessThanOrEqual(layout.viewport + 1);
            expect(layout.populatedPasswords).toBe(0);
            expect(layout.text).not.toMatch(
              /\bsk-[A-Za-z0-9_-]{20,}\b|\bBearer\s+[A-Za-z0-9._-]{20,}/,
            );

            const focusables = page.locator(
              'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
            );
            if ((await focusables.count()) > 0) {
              await page.keyboard.press("Tab");
              const focusedTag = await page.evaluate(
                () => document.activeElement?.tagName,
              );
              expect(focusedTag).not.toBe("BODY");
            }
          });
        }

        await context.close();
      });
    }
  }
}
