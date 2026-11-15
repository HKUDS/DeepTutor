"use client";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { bookApi, type BookEditInput, type BookEditProposal } from "@/lib/book-api";
import type { BookDetail } from "@/lib/book-types";
import BookEditReview from "./BookEditReview";

const actions: [BookEditInput["action"], string][] = [
  ["add_chapter", "Add chapter"], ["rename_chapter", "Rename chapter"], ["move_chapter", "Move chapter"], ["delete_chapter", "Delete chapter"],
  ["add_page", "Add section"], ["rename_page", "Rename section"], ["move_page", "Move section"], ["delete_page", "Delete section"],
];
export default function BookStructureEditor({ detail, onChanged, onClose }: {
  detail: BookDetail; onChanged: () => Promise<void> | void; onClose: () => void;
}) {
  const { t } = useTranslation();
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const root = dialog.current;
    root?.querySelector<HTMLElement>("button")?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
      if (event.key !== "Tab") return;
      const items = Array.from(root?.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary") || []);
      if (!items.length) return;
      const first = items[0], last = items.at(-1)!;
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    root?.addEventListener("keydown", keydown);
    return () => { root?.removeEventListener("keydown", keydown); previous?.focus(); };
  }, [onClose]);
  const [action, setAction] = useState<BookEditInput["action"]>("add_page");
  const chapters = detail.spine?.chapters.filter(ch => ch.content_type !== "overview") || [];
  const [chapterId, setChapterId] = useState(chapters[0]?.id || "");
  const [pageId, setPageId] = useState(detail.pages.find(p => p.content_type !== "overview")?.id || "");
  const [title, setTitle] = useState("");
  const [objective, setObjective] = useState("");
  const [position, setPosition] = useState(1);
  const [proposal, setProposal] = useState<BookEditProposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function preview() {
    setBusy(true); setError("");
    try { setProposal(await bookApi.previewEdit(detail.book.id, { action, chapter_id: chapterId, page_id: pageId, title, position: position - 1, learning_objectives: objective.trim() ? [objective.trim()] : [] })); }
    catch (err) { setError(err instanceof Error ? err.message : t("Edit failed")); }
    finally { setBusy(false); }
  }
  async function apply() {
    if (!proposal) return;
    setBusy(true); setError("");
    try { await bookApi.applyEdit(detail.book.id, proposal.id, proposal.expected_revision); setProposal(null); await onChanged(); }
    catch (err) { setError(err instanceof Error ? err.message : t("Edit failed")); }
    finally { setBusy(false); }
  }
  const inputClass = "w-full rounded border border-[var(--border)] bg-[var(--background)] p-2";
  return <div ref={dialog} role="dialog" aria-modal="true" aria-label={t("Edit book structure")} className="absolute inset-0 z-40 overflow-auto bg-[var(--background)] p-6">
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex justify-between"><h2 className="text-lg font-semibold">{t("Edit book structure")}</h2><button onClick={onClose}>{t("Close")}</button></div>
      <p className="text-sm text-[var(--muted-foreground)]">{t("New sections generate when opened. Existing content stays intact. Review changes before applying.")}</p>
      <fieldset disabled={busy || !!proposal} className="space-y-3 disabled:opacity-60">
        <label className="block">{t("Action")}<select className={inputClass} value={action} onChange={e => setAction(e.target.value as BookEditInput["action"])}>{actions.map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}</select></label>
        {action !== "add_chapter" && <label className="block">{t("Chapter")}<select className={inputClass} value={chapterId} onChange={e => setChapterId(e.target.value)}>{chapters.map(ch => <option key={ch.id} value={ch.id}>{ch.title}</option>)}</select></label>}
        {["rename_page", "move_page", "delete_page"].includes(action) && <label className="block">{t("Section")}<select className={inputClass} value={pageId} onChange={e => setPageId(e.target.value)}>{detail.pages.filter(p => p.content_type !== "overview" && !p.parent_page_id).map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</select></label>}
        {(action.startsWith("add") || action.startsWith("rename")) && <label className="block">{t("Title")}<input className={inputClass} value={title} maxLength={300} onChange={e => setTitle(e.target.value)} /></label>}
        {action.startsWith("add") && <label className="block">{t("Learning objective")}<textarea className={inputClass} value={objective} onChange={e => setObjective(e.target.value)} /></label>}
        {(action.startsWith("add") || action.startsWith("move")) && <label className="block">{t("Position")}<input className={inputClass} type="number" min={1} max={10001} value={position} onChange={e => setPosition(Math.max(1, Number(e.target.value) || 1))} /></label>}
        <button className="dt-btn-secondary px-3 py-2" onClick={() => void preview()}>{t("Preview edit")}</button>
      </fieldset>
      {error && <p role="alert" className="text-sm">{error}</p>}
      {proposal && <section className="space-y-3"><pre className="max-h-96 overflow-auto whitespace-pre-wrap text-xs">{proposal.diff}</pre><div className="flex gap-3"><button disabled={busy} className="dt-btn-primary px-3 py-2" onClick={() => void apply()}>{t("Apply reviewed edit")}</button><button disabled={busy} onClick={() => setProposal(null)}>{t("Cancel")}</button></div></section>}
      <BookEditReview bookId={detail.book.id} revision={detail.book.revision} onChanged={onChanged} />
    </div>
  </div>;
}
