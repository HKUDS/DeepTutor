"use client";

import dynamic from "next/dynamic";
import { useTranslation } from "react-i18next";

import type { CodeBlockThemeId } from "@/components/common/code-block-themes";
import { CODE_BLOCK_THEME_OPTIONS } from "@/components/common/code-block-themes";
import { Toggle } from "@/components/settings/Toggle";
import { useUiSettings } from "@/features/settings/store";
import { ThemePreviewCard } from "@/components/settings/ThemePreviewCard";
import {
  SettingRow,
  SettingSection,
  SettingsPageHeader,
  selectClass,
  selectOptionClass,
} from "@/components/settings/shared";

const CODE_BLOCK_PREVIEW_SNIPPET = `def fibonacci(n):
    """Generate the first n Fibonacci numbers."""
    a, b = 0, 1
    result = []
    for _ in range(n):
        result.append(a)
        a, b = b, a + b
    return result


# Build a deliberately long summary so the wrapping preference is easy to see
summary = f"First twenty Fibonacci values rendered with the selected syntax theme, line-number setting, and wrapping preference: {', '.join(str(value) for value in fibonacci(20))}"
print(summary)
`;

const RichCodeBlockPreview = dynamic(
  () => import("@/components/common/RichCodeBlock"),
  { ssr: false },
);

export default function AppearanceSettingsPage() {
  const { t } = useTranslation();
  const {
    theme,
    codeBlockTheme,
    codeBlockShowLineNumbers,
    codeBlockWrapLongLines,
    updateTheme,
    updateCodeBlockTheme,
    updateCodeBlockShowLineNumbers,
    updateCodeBlockWrapLongLines,
  } = useUiSettings();

  // All code-block values come straight from the settings context (backed by
  // AppShellContext, the single source of truth), so the toggles reflect the
  // current preference without any local mirror state.
  const handleShowLineNumbersChange = (next: boolean) => {
    void updateCodeBlockShowLineNumbers(next);
  };

  const handleWrapLongLinesChange = (next: boolean) => {
    void updateCodeBlockWrapLongLines(next);
  };

  return (
    <div data-tour="tour-appearance">
      <SettingsPageHeader
        title={t("Appearance")}
        description={t(
          "Customize the visual theme and code blocks. Changes apply immediately and are stored in your account.",
        )}
      />

      <SettingSection
        title={t("Theme")}
        description={t(
          "Pick the colour palette and interface style. Each tile previews the theme it applies.",
        )}
      >
        <div className="py-3.5">
          {/* Order is intentional: Default (pure-white neutral, the default
              selection; theme id "snow" kept for stored preferences) →
              warm-light Cream → warm-dark Dark → cool-dark Glass. */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(
              [
                { id: "snow", label: t("Default") },
                { id: "light", label: t("Cream") },
                { id: "dark", label: t("Dark") },
                { id: "glass", label: t("Glass") },
              ] as const
            ).map(({ id, label }) => (
              <ThemePreviewCard
                key={id}
                theme={id}
                label={label}
                selected={theme === id}
                onSelect={updateTheme}
              />
            ))}
          </div>
          <p className="mt-4 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]/80">
            {t(
              "Default is a clean pure-white theme with a blue accent. Cream is warm and paper-like with a terracotta accent. Dark keeps Cream's warmth on near-black. Glass adds translucent purple panels on a deep gradient.",
            )}
          </p>
        </div>
      </SettingSection>

      <SettingSection
        title={t("Code blocks")}
        description={t(
          "Choose how code snippets look across the app. Changes apply immediately to saved and streamed responses.",
        )}
      >
        <div className="border-t border-[var(--border)]/50 py-3.5 first:border-t-0">
          <div className="text-[13.5px] font-medium text-[var(--foreground)]">
            {t("Preview")}
          </div>
          <p className="mb-3 mt-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
            {t("Updates live as you change the settings below.")}
          </p>
          <RichCodeBlockPreview
            raw={CODE_BLOCK_PREVIEW_SNIPPET}
            lang="python"
          />
        </div>

        <SettingRow
          title={t("Syntax theme")}
          description={t(
            "Select the Prism theme used for highlighted code blocks.",
          )}
          control={
            <select
              value={codeBlockTheme}
              onChange={(event) =>
                void updateCodeBlockTheme(
                  event.target.value as CodeBlockThemeId,
                )
              }
              className={`${selectClass} min-w-[220px] pr-8`}
            >
              {CODE_BLOCK_THEME_OPTIONS.map((option) => (
                <option
                  key={option.id}
                  value={option.id}
                  className={selectOptionClass}
                >
                  {option.label}
                </option>
              ))}
            </select>
          }
        />

        <SettingRow
          title={t("Show line numbers")}
          description={t(
            "Display a gutter with line numbers beside each code block.",
          )}
          control={
            <Toggle
              checked={codeBlockShowLineNumbers}
              onChange={handleShowLineNumbersChange}
            />
          }
        />

        <SettingRow
          title={t("Wrap long lines")}
          description={t(
            "Wrap long code lines instead of forcing horizontal scrolling.",
          )}
          control={
            <Toggle
              checked={codeBlockWrapLongLines}
              onChange={handleWrapLongLinesChange}
            />
          }
        />
      </SettingSection>
    </div>
  );
}
