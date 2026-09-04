"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  listLearningRecords,
  type LearningRecords,
} from "@/lib/learning-records-api";

function percent(value: number): number {
  return Math.round(value * 100);
}

export default function LearningProgressPage() {
  const { t } = useTranslation();
  const [records, setRecords] = useState<LearningRecords | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => { void listLearningRecords().then(setRecords).catch(() => setError(true)); }, []);

  const progress = records?.progress ?? [];
  const activities = records?.activities ?? [];
  const hasRecords = progress.length > 0 || activities.length > 0;

  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      <h1 className="text-xl font-semibold">{t("Learning progress")}</h1>
      <p className="mt-1 text-sm text-[var(--muted-foreground)]">
        {t("Review your own reading and learning activity.")}
      </p>
      {error ? (
        <p className="mt-8 text-sm text-red-600">{t("Unable to load learning progress")}</p>
      ) : records === null ? (
        <p className="mt-8 text-sm text-[var(--muted-foreground)]">{t("Loading progress")}</p>
      ) : !hasRecords ? (
        <p className="mt-8 text-sm text-[var(--muted-foreground)]">{t("No learning activity yet")}</p>
      ) : (
        <>
          <div className="mt-6 grid grid-cols-2 gap-3">
            <div className="rounded-md border border-[var(--border)] p-4">
              <span className="block text-xs text-[var(--muted-foreground)]">{t("Materials")}</span>
              <strong className="mt-1 block text-xl">{progress.length}</strong>
            </div>
            <div className="rounded-md border border-[var(--border)] p-4">
              <span className="block text-xs text-[var(--muted-foreground)]">{t("Learning actions")}</span>
              <strong className="mt-1 block text-xl">{activities.length}</strong>
            </div>
          </div>
          <section className="mt-6">
            <h2 className="text-sm font-semibold">{t("Reading progress")}</h2>
            {progress.length === 0 ? (
              <p className="mt-3 text-sm text-[var(--muted-foreground)]">{t("No reading progress yet")}</p>
            ) : (
              <ul className="mt-3 grid gap-3">
                {progress.map((record) => (
                  <li key={record.material_id} className="rounded-md border border-[var(--border)] p-4">
                    <div className="flex items-center justify-between gap-3">
                      <span className="min-w-0 truncate font-medium">{record.material_id}</span>
                      <span className="text-xs text-[var(--muted-foreground)]">
                        {percent(record.furthest_percentage)}%
                      </span>
                    </div>
                    <div
                      className="mt-3 h-1.5 overflow-hidden rounded-full bg-[var(--border)]"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={percent(record.furthest_percentage)}
                      aria-label={t("Furthest reading progress")}
                    >
                      <div
                        className="h-full rounded-full bg-[var(--primary)]"
                        style={{ width: `${Math.min(100, Math.max(0, percent(record.furthest_percentage)))}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="mt-6">
            <h2 className="text-sm font-semibold">{t("Learning actions")}</h2>
            {activities.length === 0 ? (
              <p className="mt-3 text-sm text-[var(--muted-foreground)]">{t("No learning actions yet")}</p>
            ) : (
              <ul className="mt-3 grid gap-3">
                {activities.map((record) => (
                  <li key={record.activity_id} className="rounded-md border border-[var(--border)] p-4">
                    <span className="font-medium">{record.material_id}</span>
                    <span className="mt-1 block text-xs text-[var(--muted-foreground)]">
                      {record.action} · {record.extension_id} · {t("Locator")} {record.locator}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </main>
  );
}
