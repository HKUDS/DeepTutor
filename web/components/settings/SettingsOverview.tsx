"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { SettingRow, SettingSection, SettingsPageHeader } from "./shared";
import { useUiSettings } from "@/features/settings/store";
import { useSettings } from "@/features/settings/store/SettingsStore";

/** The en/zh segmented control both language rows use. */
function LanguageToggle({
  value,
  onChange,
}: {
  value: string;
  onChange: (next: "en" | "zh") => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex gap-0.5 rounded-lg bg-[var(--muted)] p-0.5">
      {(["en", "zh"] as const).map((option) => (
        <button
          key={option}
          aria-pressed={value === option}
          onClick={() => onChange(option)}
          className={`rounded-md px-2.5 py-1 text-[12px] transition-all ${
            value === option
              ? "bg-[var(--card)] font-medium text-[var(--foreground)] shadow-sm"
              : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          }`}
        >
          {option === "en" ? t("language.english") : t("language.chinese")}
        </button>
      ))}
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
            <LanguageToggle value={language} onChange={updateLanguage} />
          }
        />
        <SettingRow
          title={t("Model output language")}
          description={t(
            "Sets the default language for chat and capability responses.",
          )}
          control={
            <LanguageToggle
              value={responseLanguage}
              onChange={updateResponseLanguage}
            />
          }
        />
      </SettingSection>
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
