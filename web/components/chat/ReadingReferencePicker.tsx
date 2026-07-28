"use client";

import { useEffect, useMemo, useState } from "react";
import { BookMarked, Check, ChevronRight, Loader2, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import PickerHeader from "@/components/common/PickerHeader";
import PickerShell from "@/components/common/PickerShell";
import {
  immersiveReadingApi,
  type ReadingDocument,
  type ReadingSection,
} from "@/lib/immersive-reading-api";
import type { SelectedReadingReference } from "@/lib/reading-references";

export default function ReadingReferencePicker({
  open,
  initialReferences,
  onClose,
  onApply,
}: {
  open: boolean;
  initialReferences: SelectedReadingReference[];
  onClose: () => void;
  onApply: (references: SelectedReadingReference[]) => void;
}) {
  const { t } = useTranslation();
  const [documents, setDocuments] = useState<ReadingDocument[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [selected, setSelected] = useState<SelectedReadingReference[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let mounted = true;
    // Re-seed the picker each time it opens, matching the existing Book picker.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSelected(initialReferences);
    setLoading(true);
    void immersiveReadingApi
      .list()
      .then((result) => {
        if (!mounted) return;
        setDocuments(result.documents || []);
        setActiveId((current) => current || result.documents?.[0]?.id || null);
      })
      .finally(() => mounted && setLoading(false));
    return () => {
      mounted = false;
    };
  }, [initialReferences, open]);

  const active = documents.find((document) => document.id === activeId) || null;
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return documents;
    return documents.filter((document) =>
      `${document.title} ${document.author} ${document.source_filename}`.toLowerCase().includes(needle),
    );
  }, [documents, query]);
  const selectedKeys = useMemo(
    () =>
      new Set(
        selected.flatMap((reference) =>
          reference.sections.map((section) => `${reference.documentId}:${section.sectionId}`),
        ),
      ),
    [selected],
  );

  const toggleSection = (document: ReadingDocument, section: ReadingSection) => {
    setSelected((previous) => {
      const current = previous.find((reference) => reference.documentId === document.id);
      const exists = current?.sections.some((item) => item.sectionId === section.id);
      const nextSections = exists
        ? (current?.sections || []).filter((item) => item.sectionId !== section.id)
        : [...(current?.sections || []), { sectionId: section.id, sectionTitle: section.title }];
      const others = previous.filter((reference) => reference.documentId !== document.id);
      return nextSections.length
        ? [...others, { documentId: document.id, documentTitle: document.title, sections: nextSections }]
        : others;
    });
  };

  const toggleAll = (document: ReadingDocument) => {
    const allSelected = document.sections.every((section) =>
      selectedKeys.has(`${document.id}:${section.id}`),
    );
    setSelected((previous) => {
      const others = previous.filter((reference) => reference.documentId !== document.id);
      if (allSelected) return others;
      return [
        ...others,
        {
          documentId: document.id,
          documentTitle: document.title,
          sections: document.sections.map((section) => ({
            sectionId: section.id,
            sectionTitle: section.title,
          })),
        },
      ];
    });
  };

  const count = selected.reduce((total, reference) => total + reference.sections.length, 0);

  return (
    <PickerShell open={open} onClose={onClose} labelledBy="reading-picker-title" className="p-4 backdrop-blur-md" backdropClass="bg-[var(--background)]/65">
      <div className="surface-card flex h-[78vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-[0_22px_70px_rgba(0,0,0,0.18)]">
        <PickerHeader
          icon={BookMarked}
          titleId="reading-picker-title"
          title={t("Select Immersive Reading chapters")}
          subtitle={t("Attach source-faithful chapters from imported ebooks to the next answer.")}
          onClose={onClose}
        />
        <div className="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)]">
          <aside className="flex min-h-0 flex-col border-r border-[var(--border)] bg-[var(--background)]/40 p-4">
            <div className="relative mb-3">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("Search reading books")} className="h-10 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] pl-9 pr-3 text-sm outline-none focus:border-[var(--primary)]" />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {loading ? <div className="flex justify-center py-10"><Loader2 className="animate-spin" size={18} /></div> : filtered.length ? filtered.map((document) => (
                <button key={document.id} type="button" onClick={() => setActiveId(document.id)} className={`mb-1 flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm ${activeId === document.id ? "bg-[var(--primary)]/10 text-[var(--foreground)]" : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60"}`}>
                  <BookMarked size={15} className="shrink-0" />
                  <span className="min-w-0 flex-1 truncate">{document.title}</span>
                  <ChevronRight size={13} />
                </button>
              )) : <p className="px-3 py-8 text-center text-xs text-[var(--muted-foreground)]">{t("No immersive reading books found.")}</p>}
            </div>
          </aside>
          <section className="min-h-0 overflow-y-auto p-5">
            {active ? (
              <>
                <div className="mb-4 flex items-center justify-between gap-4">
                  <div>
                    <h3 className="font-semibold">{active.title}</h3>
                    <p className="mt-1 text-xs text-[var(--muted-foreground)]">{active.sections.length} {t("sections")}</p>
                  </div>
                  <button type="button" onClick={() => toggleAll(active)} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--muted)]">{t("Select all")}</button>
                </div>
                <div className="space-y-1">
                  {active.sections.map((section) => {
                    const checked = selectedKeys.has(`${active.id}:${section.id}`);
                    return (
                      <button key={section.id} type="button" onClick={() => toggleSection(active, section)} className="flex w-full items-start gap-3 rounded-xl px-3 py-3 text-left hover:bg-[var(--muted)]/60">
                        <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border ${checked ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]" : "border-[var(--border)]"}`}>{checked && <Check size={13} />}</span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-medium">{section.title}</span>
                          <span className="mt-0.5 block text-[11px] text-[var(--muted-foreground)]">{section.char_count.toLocaleString()} {t("characters")}</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </>
            ) : <div className="flex h-full items-center justify-center text-sm text-[var(--muted-foreground)]">{t("Select a reading book")}</div>}
          </section>
        </div>
        <footer className="flex items-center justify-between border-t border-[var(--border)] px-5 py-4">
          <span className="text-xs text-[var(--muted-foreground)]">{t("{{count}} chapters selected", { count })}</span>
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="rounded-xl px-4 py-2 text-sm text-[var(--muted-foreground)] hover:bg-[var(--muted)]">{t("Cancel")}</button>
            <button type="button" onClick={() => { onApply(selected); onClose(); }} className="rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)]">{t("Apply")}</button>
          </div>
        </footer>
      </div>
    </PickerShell>
  );
}
