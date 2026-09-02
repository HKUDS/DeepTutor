"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { SettingSection, SettingsPageHeader } from "@/components/settings/shared";
import { listLearningRecords, type LearningRecords } from "@/lib/learning-records-api";

function percent(value: number): number {
  return Math.round(value * 100);
}

export default function LearningProgressSettingsSection() {
  const { t } = useTranslation();
  const [records, setRecords] = useState<LearningRecords | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void listLearningRecords()
      .then((value) => {
        if (!cancelled) setRecords(value);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const progress = records?.progress ?? [];
  const activities = records?.activities ?? [];
  const hasRecords = progress.length > 0 || activities.length > 0;

  return (
    <div className="pb-8">
      <SettingsPageHeader
        title={t("Learning progress")}
        description={t("Review your own reading and learning activity.")}
      />
      {error ? (
        <p className="text-sm text-red-600" role="alert">
          {t("Unable to load learning progress")}
        </p>
      ) : records === null ? (
        <p className="text-sm text-[var(--muted-foreground)]" aria-busy="true">
          {t("Loading progress")}
        </p>
      ) : !hasRecords ? (
        <p className="text-sm text-[var(--muted-foreground)]">{t("No learning activity yet")}</p>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-md border border-[var(--border)] p-4">
              <span className="block text-xs text-[var(--muted-foreground)]">{t("Materials")}</span>
              <strong className="mt-1 block text-xl">{progress.length}</strong>
            </div>
            <div className="rounded-md border border-[var(--border)] p-4">
              <span className="block text-xs text-[var(--muted-foreground)]">
                {t("Learning actions")}
              </span>
              <strong className="mt-1 block text-xl">{activities.length}</strong>
            </div>
          </div>
          <div className="mt-8">
            <SettingSection title={t("Reading progress")}>
              {progress.length === 0 ? (
                <p className="py-4 text-sm text-[var(--muted-foreground)]">
                  {t("No reading progress yet")}
                </p>
              ) : (
                <ul className="grid gap-3 py-4">
                  {progress.map((record) => (
                    <li
                      key={record.material_id}
                      className="rounded-md border border-[var(--border)] p-4"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="min-w-0 truncate font-medium">{record.material_id}</span>
                        <span className="text-xs text-[var(--muted-foreground)]">
                          {percent(record.furthest_percentage)}%
                        </span>
                      </div>
                      <div
                        aria-label={t("Furthest reading progress")}
                        aria-valuemax={100}
                        aria-valuemin={0}
                        aria-valuenow={percent(record.furthest_percentage)}
                        className="mt-3 h-1.5 overflow-hidden rounded-full bg-[var(--border)]"
                        role="progressbar"
                      >
                        <div
                          className="h-full rounded-full bg-[var(--primary)]"
                          style={{
                            width: `${Math.min(
                              100,
                              Math.max(0, percent(record.furthest_percentage))
                            )}%`,
                          }}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </SettingSection>
          </div>
          <SettingSection title={t("Learning actions")}>
            {activities.length === 0 ? (
              <p className="py-4 text-sm text-[var(--muted-foreground)]">
                {t("No learning actions yet")}
              </p>
            ) : (
              <ul className="grid gap-3 py-4">
                {activities.map((record) => (
                  <li
                    key={record.activity_id}
                    className="rounded-md border border-[var(--border)] p-4"
                  >
                    <span className="font-medium">{record.material_id}</span>
                    <span className="mt-1 block text-xs text-[var(--muted-foreground)]">
                      {record.action} - {record.extension_id} - {t("Locator")} {record.locator}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </SettingSection>
        </>
      )}
    </div>
  );
}
