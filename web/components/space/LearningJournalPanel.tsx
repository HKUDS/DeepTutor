"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { getLearningJournal, type LearningJournal } from "@/lib/learning-journal-api";
import SpaceSectionHeader from "./SpaceSectionHeader";

export default function LearningJournalPanel() {
  const { t } = useTranslation();
  const params = useSearchParams();
  const workspace = params.get("dt_workspace") ?? params.get("workspace") ?? "";
  const [result, setResult] = useState<{ workspace: string; revision: number; journal?: LearningJournal; error?: boolean } | null>(null);
  const [revision, setRevision] = useState(0);
  const current = result?.workspace === workspace && result.revision === revision ? result : null;
  const journal = current?.journal;
  const error = current?.error;

  useEffect(() => {
    const controller = new AbortController();
    void getLearningJournal(controller.signal).then((snapshot) => {
      if (!controller.signal.aborted) setResult({ workspace, revision, journal: snapshot });
    }).catch(() => {
      if (!controller.signal.aborted) setResult({ workspace, revision, error: true });
    });
    return () => controller.abort();
  }, [workspace, revision]);

  const card = "rounded-xl border border-[var(--border)] p-5 space-y-3";
  return (
    <section className="space-y-5">
      <SpaceSectionHeader title={t("Learning journal")} description={t("Your tutor's mission, handoff and confirmed learning records.")}
        action={<button className="text-sm underline" onClick={() => setRevision((n) => n + 1)}>{t("Refresh")}</button>} />
      {error ? <div role="alert" className={card}>{t("Could not read the learning journal. Its original data is preserved. Try refreshing.")}</div>
        : !journal ? <p role="status">{t("Loading...")}</p>
        : <>
          <section className={card} aria-label={t("Current mission")}>
            <h2 className="font-semibold">{t("Current mission")}</h2>
            {journal.mission.topic ? <>
              <p className="font-medium break-words">{journal.mission.topic}</p>
              {journal.mission.why && <p className="whitespace-pre-wrap break-words">{journal.mission.why}</p>}
              {journal.mission.level && <p className="text-sm">{t("Level")}: {journal.mission.level}</p>}
              {journal.mission.updated_at && <time className="text-xs text-[var(--muted-foreground)]" dateTime={journal.mission.updated_at}>{journal.mission.updated_at}</time>}
            </> : <p>{t("Your tutor has no mission for you yet. Ask it to set one in conversation.")}</p>}
          </section>
          <section className={card} aria-label={t("Last-session handoff")}>
            <h2 className="font-semibold">{t("Last-session handoff")}</h2>
            {journal.last_session.summary || journal.last_session.next_focus ? <>
              <p className="whitespace-pre-wrap break-words">{journal.last_session.summary}</p>
              {journal.last_session.next_focus && <p className="whitespace-pre-wrap break-words"><strong>{t("Next focus")}: </strong>{journal.last_session.next_focus}</p>}
              {journal.last_session.updated_at && <time className="text-xs text-[var(--muted-foreground)]" dateTime={journal.last_session.updated_at}>{journal.last_session.updated_at}</time>}
            </> : <p>{t("No session handoff yet.")}</p>}
          </section>
          <section className={card} aria-label={t("Confirmed learning records")}>
            <h2 className="font-semibold">{t("Confirmed learning records")}</h2>
            {journal.records.length ? <ol className="space-y-4">{journal.records.map((record) => <li key={record.id}>
              <h3 className="font-medium break-words">{record.title}</h3>
              <p className="whitespace-pre-wrap break-words">{record.insight}</p>
              {record.created_at && <time className="text-xs text-[var(--muted-foreground)]" dateTime={record.created_at}>{record.created_at}</time>}
            </li>)}</ol> : <p>{t("No confirmed learning records yet.")}</p>}
          </section>
        </>}
    </section>
  );
}
