"use client";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { bookApi, type BookEditProposal } from "@/lib/book-api";

export default function BookEditReview({ bookId, pageId, revision, refreshKey, onChanged }: {
  bookId: string; pageId?: string; revision: number; refreshKey?: boolean;
  onChanged: () => Promise<void> | void;
}) {
  const { t } = useTranslation();
  const [edits, setEdits] = useState<BookEditProposal[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    bookApi.listEdits(bookId, pageId).then(value => { if (current) setEdits(value.edits); }).catch(err => { if (current) setError(String(err.message)); });
    return () => { current = false; };
  }, [bookId, pageId, revision, refreshKey]);
  async function apply(edit: BookEditProposal, undo = false) {
    setBusy(true); setError("");
    try {
      await bookApi.applyEdit(bookId, edit.id, undo ? edit.applied_revision! : edit.expected_revision, undo);
      await onChanged();
      setEdits((await bookApi.listEdits(bookId, pageId)).edits);
    } catch (err) { setError(err instanceof Error ? err.message : t("Edit failed")); }
    finally { setBusy(false); }
  }
  const visible = edits.filter(edit => edit.status === "proposed" || (edit.status === "applied" && edit.applied_revision === revision));
  if (!visible.length && !error) return null;
  return <section aria-label={t("Proposed book edits")} className="space-y-3 border-t border-[var(--border)] p-3 text-sm">
    <h3 className="font-medium">{t("Proposed book edits")}</h3>
    {error && <p role="alert">{error}</p>}
    {visible.map(edit => <details key={edit.id} className="rounded-lg border border-[var(--border)] p-2">
      <summary className="cursor-pointer">{edit.edit.title || t("Book edit")}</summary>
      <pre className="my-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs">{edit.diff}</pre>
      {edit.source_turn_id && <p className="mb-2 text-xs text-[var(--muted-foreground)]">{t("Proposed from this book conversation")}</p>}
      {edit.status === "proposed" ? <button disabled={busy || edit.expected_revision !== revision} onClick={() => void apply(edit)} className="dt-btn-primary px-3 py-1 disabled:opacity-50">{t("Apply reviewed edit")}</button>
        : <button disabled={busy} onClick={() => void apply(edit, true)} className="dt-btn-secondary px-3 py-1">{t("Undo book edit")}</button>}
      {edit.status === "proposed" && edit.expected_revision !== revision && <p>{t("Book changed; request a new proposal.")}</p>}
    </details>)}
  </section>;
}
