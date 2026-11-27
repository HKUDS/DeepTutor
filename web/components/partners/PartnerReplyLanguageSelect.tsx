"use client";

/**
 * Reply-language picker shared by the partner wizard and the partner
 * configuration panel.
 *
 * An empty value means "follow the account's model output language". The
 * label spells that language out instead of hardcoding English, so a user who
 * selected French in Settings sees "Auto (Français)" here.
 */

import { useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

import {
  readStoredResponseLanguage,
  RESPONSE_LANGUAGE_EVENT,
} from "@/context/app-shell-storage";
import { RESPONSE_LANGUAGE_OPTIONS } from "@/features/settings/store/response-language-options";

function subscribe(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener(RESPONSE_LANGUAGE_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(RESPONSE_LANGUAGE_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export default function PartnerReplyLanguageSelect({
  value,
  onChange,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const responseLanguage = useSyncExternalStore(
    subscribe,
    readStoredResponseLanguage,
    () => "en" as const,
  );
  const autoLabel =
    RESPONSE_LANGUAGE_OPTIONS.find(
      (option) => option.value === responseLanguage,
    )?.label ?? "English";

  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className={className}
    >
      <option value="">
        {t("Auto ({{value}})", { value: autoLabel })}
      </option>
      {RESPONSE_LANGUAGE_OPTIONS.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
