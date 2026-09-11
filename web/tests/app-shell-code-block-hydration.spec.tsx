import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { AppShellProvider, useAppShell } from "@/context/AppShellContext";
import {
  CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY,
  CODE_BLOCK_THEME_STORAGE_KEY,
  CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY,
  LANGUAGE_STORAGE_KEY,
} from "@/context/app-shell-storage";

function CodeBlockPreferencesProbe() {
  const {
    codeBlockTheme,
    codeBlockShowLineNumbers,
    codeBlockWrapLongLines,
  } = useAppShell();

  return (
    <output
      aria-label="code block preferences"
      data-theme={codeBlockTheme}
      data-show-line-numbers={String(codeBlockShowLineNumbers)}
      data-wrap-long-lines={String(codeBlockWrapLongLines)}
    />
  );
}

describe("AppShellProvider code-block hydration", () => {
  beforeEach(() => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
  });

  it("rehydrates all persisted code-block preferences after mounting", async () => {
    localStorage.setItem(CODE_BLOCK_THEME_STORAGE_KEY, "dracula");
    localStorage.setItem(CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY, "true");
    localStorage.setItem(CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY, "true");

    render(
      <AppShellProvider>
        <CodeBlockPreferencesProbe />
      </AppShellProvider>,
    );

    const preferences = screen.getByLabelText("code block preferences");
    await waitFor(() => {
      expect(preferences).toHaveAttribute("data-theme", "dracula");
      expect(preferences).toHaveAttribute("data-show-line-numbers", "true");
      expect(preferences).toHaveAttribute("data-wrap-long-lines", "true");
    });
  });
});
