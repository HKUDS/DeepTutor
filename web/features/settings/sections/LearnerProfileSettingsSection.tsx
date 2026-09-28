"use client";

import { useSettings } from "@/features/settings/store/SettingsStore";
import { useStagedSettings } from "@/features/settings/store/useStagedSettings";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  getOwnLearnerProfile,
  type LearnerProfile,
} from "@/lib/profile-api";

const fields: Array<[keyof LearnerProfile, string]> = [
  ["age", "Age"],
  ["grade_level", "Grade level"],
  ["curriculum", "Curriculum"],
  ["language", "Preferred language"],
  ["reading_level", "Reading level"],
  ["explanation_style", "Explanation style"],
];

export default function LearnerProfileSettingsPage() {
  const { t } = useTranslation();
  const { draftRevision } = useSettings();
  const [live, setLive] = useState<LearnerProfile>({});
  const [profile, setProfile] = useStagedSettings("learner-profile", live, setLive);
  const [status, setStatus] = useState<"idle" | "loading" | "saved" | "error">(
    "loading",
  );

  useEffect(() => {
    void getOwnLearnerProfile()
      .then((value) => {
        setLive(value ?? {});
        setStatus("idle");
      })
      .catch(() => setStatus("error"));
  }, [draftRevision]);

  const update = (key: keyof LearnerProfile, value: string) => {
    setProfile((current) => ({
      ...current,
      [key]:
        key === "age"
          ? value
            ? Number(value)
            : undefined
          : value || undefined,
    }));
  };

  return (
    <main className="mx-auto max-w-2xl px-6 py-8">
      <h1 className="text-xl font-semibold">{t("Learner profile")}</h1>
      <p className="mt-1 text-sm text-[var(--muted-foreground)]">
        {t("Personalize explanations and reading support for your account.")}
      </p>
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        {fields.map(([key, label]) => (
          <label key={key} className="grid gap-1 text-sm">
            <span>{t(label)}</span>
            <input
              disabled={status === "loading"}
              type={key === "age" ? "number" : "text"}
              min={key === "age" ? 3 : undefined}
              max={key === "age" ? 120 : undefined}
              value={profile[key] ?? ""}
              onChange={(event) => update(key, event.target.value)}
              className="rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-2"
            />
          </label>
        ))}
      </div>
      <div className="mt-6 flex items-center gap-3">
        {status === "error" && (
          <span className="text-sm text-red-600">
            {t("Unable to save profile")}
          </span>
        )}
      </div>
    </main>
  );
}
