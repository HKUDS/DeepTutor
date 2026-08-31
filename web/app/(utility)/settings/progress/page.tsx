"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { listLearningRecords, type LearningRecord } from "@/lib/learning-records-api";

function label(record: LearningRecord): string {
  return String(record.title ?? record.material_title ?? record.material_id ?? "Learning activity");
}

export default function LearningProgressPage() {
  const { t } = useTranslation();
  const [records, setRecords] = useState<LearningRecord[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => { void listLearningRecords().then(setRecords).catch(() => setError(true)); }, []);

  return <main className="mx-auto max-w-3xl px-6 py-8"><h1 className="text-xl font-semibold">{t("Learning progress")}</h1><p className="mt-1 text-sm text-[var(--muted-foreground)]">{t("Review your own reading and learning activity.")}</p>{error ? <p className="mt-8 text-sm text-red-600">{t("Unable to load learning progress")}</p> : records === null ? <p className="mt-8 text-sm text-[var(--muted-foreground)]">{t("Loading progress")}</p> : records.length === 0 ? <p className="mt-8 text-sm text-[var(--muted-foreground)]">{t("No learning activity yet")}</p> : <ul className="mt-6 grid gap-3">{records.map((record, index) => <li key={String(record.event_id ?? record.id ?? index)} className="rounded-md border border-[var(--border)] p-4"><span className="font-medium">{label(record)}</span><span className="mt-1 block text-xs text-[var(--muted-foreground)]">{String(record.action ?? record.kind ?? "")}</span></li>)}</ul>}</main>;
}
