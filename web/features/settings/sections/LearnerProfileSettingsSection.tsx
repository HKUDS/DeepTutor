"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  getOwnLearnerProfile,
  setOwnLearnerProfile,
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
  const [profile, setProfile] = useState<LearnerProfile>({});
  const [status, setStatus] = useState<"idle" | "loading" | "saved" | "error">(
    "loading",
  );

  useEffect(() => {
    void getOwnLearnerProfile()
      .then((value) => {
        setProfile(value ?? {});
        setStatus("idle");
      })
      .catch(() => setStatus("error"));
  }, []);

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

  const save = async () => {
    setStatus("loading");
    try {
      setProfile((await setOwnLearnerProfile(profile)) ?? {});
      setStatus("saved");
    } catch {
      setStatus("error");
    }
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
        <button
          type="button"
          onClick={() => void save()}
          disabled={status === "loading"}
          className="rounded-md bg-[var(--primary)] px-4 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-60"
        >
          {t("Save profile")}
        </button>
        {status === "saved" && <span className="text-sm">{t("Saved")}</span>}
        {status === "error" && (
          <span className="text-sm text-red-600">
            {t("Unable to save profile")}
          </span>
        )}
      </div>
    </main>
  );
}
