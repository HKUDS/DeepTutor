"use client";

import Link from "next/link";
import { ArrowRight, ChevronDown, Languages } from "lucide-react";
import { useTranslation } from "react-i18next";
import SettingsPresetsPanel from "@/components/settings/SettingsPresetsPanel";
import {
  SettingRow,
  SettingSection,
  SettingsPageHeader,
  selectClass,
  selectOptionClass,
} from "./shared";
import { RESPONSE_LANGUAGE_OPTIONS, useUiSettings } from "@/features/settings/store";
import { useSettings } from "@/features/settings/store/SettingsStore";
import { APP_LANGUAGE_DEFINITIONS, isAppLanguage } from "@/i18n/languages";
import type { AppLanguage } from "@/i18n/languages";

/** A compact selector that remains usable as the language list grows. */
function LanguageSelect({
  value,
  label,
  onChange,
}: {
  value: AppLanguage;
  label: string;
  onChange: (next: AppLanguage) => void;
}) {
  return (
    <div className="relative w-[180px] sm:w-[220px]">
      <Languages
        aria-hidden="true"
        className="pointer-events-none absolute left-3 top-1/2 z-10 size-4 -translate-y-1/2 text-[var(--muted-foreground)]"
      />
      <select
        aria-label={label}
        value={value}
        onChange={(event) => {
          const next = event.currentTarget.value;
          if (isAppLanguage(next)) onChange(next);
        }}
        className={`${selectClass} h-9 py-0 pl-9 pr-9 text-[13px] font-medium shadow-sm hover:border-[var(--muted-foreground)]/60`}
      >
        {APP_LANGUAGE_DEFINITIONS.map(({ code, nativeLabel }) => (
          <option key={code} value={code} className={selectOptionClass}>
            {nativeLabel}
          </option>
        ))}
      </select>
      <ChevronDown
        aria-hidden="true"
        className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-[var(--muted-foreground)]"
      />
    </div>
  );
}

export default function SettingsOverview() {
  const { t } = useTranslation();
  const { language, responseLanguage, updateLanguage, updateResponseLanguage } =
    useUiSettings();
  const { catalogEditable } = useSettings();
  return (
    <div>
      <SettingsPageHeader
        title={t("General")}
        description={t(
          "Make DeepTutor feel at home. Apply your preferences using the bar below.",
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
      {catalogEditable === true && <SettingsPresetsPanel enabled={true} />}
      {catalogEditable && <SettingSection
        title={t("Set up chat first")}
        description={t("Connect a provider and choose a language model. Other services are optional.")}
      >
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
    </div>
  );
}
