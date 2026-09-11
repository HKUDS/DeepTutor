import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import RichCodeBlock from "@/components/common/RichCodeBlock";
import {
  getCodeBlockTheme,
  getCodeBlockThemeBackground,
} from "@/components/common/code-block-themes";
import { AppShellProvider } from "@/context/AppShellContext";
import {
  CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY,
  CODE_BLOCK_THEME_STORAGE_KEY,
  CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY,
  LANGUAGE_STORAGE_KEY,
} from "@/context/app-shell-storage";

function setCodeBlockPreferences({
  theme,
  showLineNumbers,
  wrapLongLines,
}: {
  theme: string;
  showLineNumbers: boolean;
  wrapLongLines: boolean;
}) {
  localStorage.setItem(CODE_BLOCK_THEME_STORAGE_KEY, theme);
  localStorage.setItem(
    CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY,
    String(showLineNumbers),
  );
  localStorage.setItem(
    CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY,
    String(wrapLongLines),
  );
}

function renderCodeBlock(raw: string, lang: string) {
  return render(
    <AppShellProvider>
      <RichCodeBlock raw={raw} lang={lang} />
    </AppShellProvider>,
  );
}

describe("RichCodeBlock preferences", () => {
  beforeEach(() => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
  });

  it("uses the selected theme background instead of a hardcoded dark style", async () => {
    setCodeBlockPreferences({
      theme: "oneLight",
      showLineNumbers: false,
      wrapLongLines: false,
    });
    const { container } = renderCodeBlock("const value = 1;", "js");
    const oneLightBackground = getCodeBlockThemeBackground(
      getCodeBlockTheme("oneLight"),
    );

    expect(oneLightBackground).toBeTruthy();
    const colorProbe = document.createElement("div");
    colorProbe.style.backgroundColor = oneLightBackground!;
    await waitFor(() => {
      expect(
        (container.querySelector(".md-code-block") as HTMLElement | null)?.style
          .backgroundColor,
      ).toBe(colorProbe.style.backgroundColor);
    });
    expect(container.innerHTML).not.toMatch(/background:\s*#1f2937/);
  });

  it("honors line-number and wrap preferences for highlighted blocks", async () => {
    setCodeBlockPreferences({
      theme: "dracula",
      showLineNumbers: true,
      wrapLongLines: true,
    });
    const { container } = renderCodeBlock(
      "print('hello')\nprint('world')",
      "python",
    );

    await waitFor(() => {
      expect(container.innerHTML).toMatch(
        /react-syntax-highlighter-line-number/,
      );
      expect(container.innerHTML).toMatch(
        /<pre[^>]*style="[^"]*white-space:\s*pre-wrap[^"]*"/,
      );
    });
  });

  it("honors line-number and wrap preferences for plain text", async () => {
    setCodeBlockPreferences({
      theme: "oneDark",
      showLineNumbers: true,
      wrapLongLines: true,
    });
    const { container } = renderCodeBlock(
      "plain text line\nanother line",
      "text",
    );

    await waitFor(() => {
      expect(container.innerHTML).toMatch(
        /react-syntax-highlighter-line-number/,
      );
      expect(container.innerHTML).toMatch(
        /<pre[^>]*style="[^"]*white-space:\s*pre-wrap[^"]*"/,
      );
    });
    expect(container.innerHTML).not.toMatch(/unknown language/i);
  });

  it("keeps long lines horizontally scrollable when wrapping is disabled", async () => {
    setCodeBlockPreferences({
      theme: "dracula",
      showLineNumbers: false,
      wrapLongLines: false,
    });
    const { container } = renderCodeBlock(
      "const veryLongLine = 'this should stay on one line and scroll instead of wrapping';",
      "javascript",
    );

    await waitFor(() => {
      expect(container.innerHTML).toMatch(
        /<pre[^>]*style="[^"]*overflow-x:\s*auto[^"]*"/,
      );
    });
    expect(container.innerHTML).not.toMatch(
      /<pre[^>]*style="[^"]*white-space:\s*pre-wrap[^"]*"/,
    );
  });

  it("breaks long unbroken tokens when wrapping is enabled", async () => {
    setCodeBlockPreferences({
      theme: "oneLight",
      showLineNumbers: false,
      wrapLongLines: true,
    });
    const { container } = renderCodeBlock("a".repeat(200), "javascript");

    await waitFor(() => {
      expect(container.innerHTML).toMatch(
        /<pre[^>]*style="[^"]*word-wrap:\s*break-word[^"]*"/,
      );
      expect(container.innerHTML).toMatch(
        /<code[^>]*style="[^"]*word-wrap:\s*break-word[^"]*"/,
      );
    });
  });

  it("does not let line-number flex wrappers defeat overflow wrapping", async () => {
    setCodeBlockPreferences({
      theme: "oneLight",
      showLineNumbers: true,
      wrapLongLines: true,
    });
    const { container } = renderCodeBlock(
      `${"a".repeat(200)} tail`,
      "javascript",
    );

    await waitFor(() => {
      expect(container.innerHTML).toMatch(
        /react-syntax-highlighter-line-number/,
      );
    });
    const code = container.querySelector("code");
    expect(code).not.toBeNull();
    expect(code!.innerHTML).not.toMatch(
      /<span[^>]*style="[^"]*display:\s*flex[^"]*"/,
    );
  });
});
