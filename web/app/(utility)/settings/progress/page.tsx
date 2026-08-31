"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { listLearningRecords, type LearningRecord } from "@/lib/learning-records-api";

function label(record: LearningRecord): string {
  return String(record.title ?? record.material_title ?? record.material_id ?? "Learning activity");
}

function isCompleted(record: LearningRecord): boolean {
  return record.completed === true;
}

function score(record: LearningRecord): number | null {
  const value = Number(record.score);
  const total = Number(record.total);
  return Number.isFinite(value) && Number.isFinite(total) && total > 0 ? value / total : null;
}

export default function LearningProgressPage() {
  const { t } = useTranslation();
  const [records, setRecords] = useState<LearningRecord[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => { void listLearningRecords().then(setRecords).catch(() => setError(true)); }, []);

  const completed = records?.filter(isCompleted).length ?? 0;
  const scores = records?.map(score).filter((value): value is number => value !== null) ?? [];
  const averageScore = scores.length ? Math.round((scores.reduce((sum, value) => sum + value, 0) / scores.length) * 100) : null;

  return <main className="mx-auto max-w-3xl px-6 py-8"><h1 className="text-xl font-semibold">{t("Learning progress")}</h1><p className="mt-1 text-sm text-[var(--muted-foreground)]">{t("Review your own reading and learning activity.")}</p>{error ? <p className="mt-8 text-sm text-red-600">{t("Unable to load learning progress")}</p> : records === null ? <p className="mt-8 text-sm text-[var(--muted-foreground)]">{t("Loading progress")}</p> : records.length === 0 ? <p className="mt-8 text-sm text-[var(--muted-foreground)]">{t("No learning activity yet")}</p> : <><div className="mt-6 grid grid-cols-2 gap-3"><div className="rounded-md border border-[var(--border)] p-4"><span className="block text-xs text-[var(--muted-foreground)]">{t("Activities")}</span><strong className="mt-1 block text-xl">{records.length}</strong></div><div className="rounded-md border border-[var(--border)] p-4"><span className="block text-xs text-[var(--muted-foreground)]">{t("Completed")}</span><strong className="mt-1 block text-xl">{completed}</strong></div>{averageScore !== null && <div className="rounded-md border border-[var(--border)] p-4"><span className="block text-xs text-[var(--muted-foreground)]">{t("Average score")}</span><strong className="mt-1 block text-xl">{averageScore}%</strong></div>}</div><ul className="mt-6 grid gap-3">{records.map((record, index) => <li key={String(record.event_id ?? record.id ?? index)} className="rounded-md border border-[var(--border)] p-4"><span className="font-medium">{label(record)}</span><span className="mt-1 block text-xs text-[var(--muted-foreground)]">{String(record.action ?? record.kind ?? "")}</span></li>)}</ul></>}</main>;
}
