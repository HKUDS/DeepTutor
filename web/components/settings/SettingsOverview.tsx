"use client";

import Link from "next/link";
import { useCallback, useState, type SetStateAction } from "react";
import { ArrowRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { apiFetch, apiUrl } from "@/lib/api";
import { APP_LANGUAGES, isAppLanguage, type AppLanguage } from "@/i18n/init";
import AgentSetupHelp from "@/components/settings/AgentSetupHelp";
import {
  SettingRow,
  SettingSection,
  SettingsPageHeader,
  selectClass,
  selectOptionClass,
} from "./shared";
import { RESPONSE_LANGUAGE_OPTIONS, useUiSettings } from "@/features/settings/store";
import { useSettings } from "@/features/settings/store/SettingsStore";
import { useStagedSettings } from "@/features/settings/store/useStagedSettings";
import { useUiLayout } from "@/hooks/useUiLayout";
import {
  DEFAULT_UI_LAYOUT,
  UI_LAYOUTS,
  writeStoredUiLayout,
  type UiLayout,
} from "@/lib/ui-layout";

const UI_LAYOUT_LABELS: Record<UiLayout, string> = {
  classic: "Classic",
  modern: "Modern",
};

function LanguageSelect({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (next: AppLanguage) => void;
}) {
  const { t } = useTranslation();
  return (
    <select
      aria-label={label}
      className={`${selectClass} min-w-[200px]`}
      value={value}
      onChange={(event) => {
        const next = event.currentTarget.value;
        if (isAppLanguage(next)) onChange(next);
      }}
    >
      {APP_LANGUAGES.map(({ code, labelKey }) => (
        <option key={code} value={code} className={selectOptionClass}>
          {t(labelKey)}
        </option>
      ))}
    </select>
  );
}

export default function SettingsOverview() {
  const { t } = useTranslation();
  const { language, responseLanguage, updateLanguage, updateResponseLanguage } =
    useUiSettings();
  const { catalogEditable } = useSettings();
  const uiLayout = useUiLayout();
  const setLiveUiLayout = useCallback(
    (action: SetStateAction<UiLayout>) =>
      writeStoredUiLayout(typeof action === "function" ? action(uiLayout) : action),
    [uiLayout],
  );
  const [resetDialogOpen, setResetDialogOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState("");
  const [stagedUiLayout, stageUiLayout] = useStagedSettings(
    "ui-layout",
    uiLayout,
    setLiveUiLayout,
  );
  const resetConfigurations = async () => {
    setResetting(true);
    setResetError("");
    try {
      const response = await apiFetch(apiUrl("/api/settings/reset"), {
        method: "POST",
      });
      if (!response.ok)
        throw new Error(
          t("Could not reset configurations (HTTP {{status}}).", {
            status: response.status,
          }),
        );
      writeStoredUiLayout(DEFAULT_UI_LAYOUT);
      window.location.reload();
    } catch (error) {
      setResetDialogOpen(false);
      setResetError(
        error instanceof Error
          ? error.message
          : t("Could not reset configurations."),
      );
    } finally {
      setResetting(false);
    }
  };
  return (
    <div>
      <SettingsPageHeader
        title={t("General")}
        description={t(
          "Make Astitvam feel at home. Apply your preferences using the bar below.",
        )}
      />
      <SettingSection title={t("Language")}>
        <SettingRow
          title={t("Interface language")}
          description={t(
            "Controls navigation, settings, and status text only.",
          )}
          control={
            <LanguageSelect
              label={t("Interface language")}
              value={language}
              onChange={updateLanguage}
            />
          }
        />
        <SettingRow
          title={t("Model output language")}
          description={t(
            "Sets the default language for chat and capability responses.",
          )}
          control={
            <select
              aria-label={t("Model output language")}
              value={responseLanguage}
              onChange={(event) =>
                void updateResponseLanguage(
                  event.target.value as typeof responseLanguage,
                )
              }
              className={`${selectClass} min-w-[200px] pr-8`}
            >
              {RESPONSE_LANGUAGE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          }
        />
      </SettingSection>
      <SettingSection title={t("Layout")}>
        <SettingRow
          title={t("Interface layout")}
          description={t(
            "Classic keeps the familiar navigation; Modern is the redesigned interface.",
          )}
          control={
            <select
              aria-label={t("Interface layout")}
              value={stagedUiLayout}
              onChange={(event) => stageUiLayout(event.target.value as UiLayout)}
              className={`${selectClass} min-w-[200px] pr-8`}
            >
              {UI_LAYOUTS.map((layout) => (
                <option key={layout} value={layout} className={selectOptionClass}>
                  {t(UI_LAYOUT_LABELS[layout])}
                </option>
              ))}
            </select>
          }
        />
      </SettingSection>
      {catalogEditable && <SettingSection
        title={t("Set up chat first")}
        description={t("Connect a provider and choose a language model. Other services are optional.")}
      >
        <AgentSetupHelp />
        {[
          {
            href: "/settings/connections",
            title: t("1. Connect a provider"),
            description: t("Add your provider and credentials, then test the connection."),
          },
          {
            href: "/settings/llm",
            title: t("2. Choose a chat model"),
            description: t("Add a language model, test it, and select it as the default for conversations."),
          },
          {
            href: "/settings/status",
            title: t("3. Apply and check"),
            description: t("Apply your changes using the bottom bar, then check service status before starting a conversation."),
          },
        ].map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="group flex items-center justify-between gap-5 border-b border-[var(--border)]/50 py-4 last:border-0 rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
          >
            <div>
              <div className="text-[14px] font-medium">{item.title}</div>
              <p className="mt-1 text-[13px] leading-relaxed text-[var(--muted-foreground)]">
                {item.description}
              </p>
            </div>
            <ArrowRight size={17} className="shrink-0 text-[var(--muted-foreground)]" />
          </Link>
        ))}
      </SettingSection>}
      {catalogEditable && <SettingSection
        title={t("Add more when you need it")}
        description={t("These services are not required for basic chat.")}
      >
        {[
          { href: "/settings/embedding", title: t("Knowledge search"), description: t("Configure an embedding model before indexing a knowledge base.") },
          { href: "/settings/search", title: t("Web search"), description: t("Connect a search service to find information on the web.") },
          { href: "/settings/task-models", title: t("Background task models"), description: t("Choose models for automatic tasks such as titles and suggestions.") },
        ].map(item => (
          <Link key={item.href} href={item.href} className="flex items-center justify-between gap-5 border-b border-[var(--border)]/50 py-4 last:border-0 rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ring)]">
            <div>
              <div className="text-[14px] font-medium">{item.title}</div>
              <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">{item.description}</p>
            </div>
            <ArrowRight size={17} className="shrink-0 text-[var(--muted-foreground)]" />
          </Link>
        ))}
      </SettingSection>}
      {catalogEditable && (
        <SettingSection
          title={t("Reset configurations")}
          description={t(
            "Restore saved application settings and model providers to their defaults.",
          )}
        >
          <div className="space-y-3">
            <p className="text-[13px] leading-relaxed text-[var(--muted-foreground)]">
              {t(
                "This removes configured models and provider credentials. Accounts, conversations, knowledge bases, and uploaded files are preserved. Deployment environment variables are not changed; some settings may require restarting Astitvam.",
              )}
            </p>
            {resetError && (
              <p role="alert" className="text-sm text-red-600 dark:text-red-400">
                {resetError}
              </p>
            )}
            <button
              type="button"
              disabled={resetting}
              onClick={() => setResetDialogOpen(true)}
              className="rounded-lg border border-red-500/50 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-500/10 dark:text-red-300 disabled:opacity-40"
            >
              {t("Reset all configurations")}
            </button>
          </div>
          <ConfirmDialog
            open={resetDialogOpen}
            title={t("Reset all configurations?")}
            tone="danger"
            confirmLabel={t("Reset configurations")}
            busy={resetting}
            busyLabel={t("Resetting…")}
            onConfirm={() => void resetConfigurations()}
            onCancel={() => setResetDialogOpen(false)}
          >
            {t(
              "All saved configuration, model profiles, provider credentials, and unapplied settings drafts will be cleared. Your account and learning data will remain. This cannot be undone.",
            )}
          </ConfirmDialog>
        </SettingSection>
      )}
    </div>
  );
}
