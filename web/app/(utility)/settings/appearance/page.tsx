"use client";

import { useTranslation } from "react-i18next";

import { useSettings } from "@/components/settings/SettingsContext";
import { ThemePreviewCard } from "@/components/settings/ThemePreviewCard";
import {
  SettingRow,
  SettingSection,
  SettingsPageHeader,
} from "@/components/settings/shared";
import { uiLanguageOptions, type AppLanguage } from "@/lib/ui-languages";

export default function AppearanceSettingsPage() {
  const { t } = useTranslation();
  const { theme, language, updateTheme, updateLanguage } = useSettings();

  return (
    <div data-tour="tour-appearance">
      <SettingsPageHeader
        title={t("Appearance")}
        description={t(
          "Tune the visual theme and interface language. Changes apply immediately and are stored in your account.",
        )}
      />

      <SettingSection
        title={t("Language")}
        description={t("Choose the interface language.")}
      >
        <SettingRow
          title={t("Interface language")}
          description={t(
            "Affects the UI only. Model output language is controlled by your prompt.",
          )}
          control={
            <select
              value={language}
              onChange={(event) =>
                updateLanguage(event.target.value as AppLanguage)
              }
              className="min-w-36 rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)] shadow-sm outline-none transition-colors hover:border-[var(--muted-foreground)] focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20"
            >
              {uiLanguageOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {t(option.labelKey)}
                </option>
              ))}
            </select>
          }
        />
      </SettingSection>

      <SettingSection
        title={t("Theme")}
        description={t(
          "Pick the colour palette and interface style. Each tile previews the theme it applies.",
        )}
      >
        <div className="py-4">
          {/* Order is intentional: warm-light → cool-light → warm-dark →
              cool-dark. Cream is the default, Snow is its cool sibling,
              Dark mirrors Cream's accent, Glass mirrors Snow's. */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(
              [
                { id: "light", label: t("Cream") },
                { id: "snow", label: t("Snow") },
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
              "Cream is a warm, paper-like default with a terracotta accent. Snow is its cool, blue-tinted sibling with a royal-blue accent. Dark keeps Cream's warmth on near-black. Glass adds translucent purple panels on a deep gradient.",
            )}
          </p>
        </div>
      </SettingSection>
    </div>
  );
}
