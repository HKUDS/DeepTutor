"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Bookmark,
  Check,
  ClipboardList,
  FolderOpen,
  Loader2,
  Search,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import PickerShell from "@/components/common/PickerShell";
import PickerHeader from "@/components/common/PickerHeader";
import {
  listCategories,
  listNotebookEntries,
  listQuestionBankMaterials,
  type NotebookCategory,
  type NotebookEntry,
  type QuestionBankMaterial,
} from "@/lib/notebook-api";

export interface SelectedQuestionEntry {
  id: number;
  question: string;
  session_title: string;
  is_correct: boolean;
  difficulty: string;
}

function provenanceLabel(entry: NotebookEntry): string {
  return (
    entry.session_title ||
    entry.section_title ||
    entry.material_title ||
    (entry.origin_type === "conversation" ? "" : entry.origin_ref || "")
  );
}

interface QuestionBankPickerProps {
  open: boolean;
  initialSelected: SelectedQuestionEntry[];
  onClose: () => void;
  onApply: (entries: SelectedQuestionEntry[]) => void;
}

type FilterMode = "all" | "bookmarked" | "wrong";

const FILTER_MODES: { value: FilterMode; label: string }[] = [
  { value: "all", label: "All" },
  { value: "bookmarked", label: "Bookmarked" },
  { value: "wrong", label: "Wrong Only" },
];

export default function QuestionBankPicker({
  open,
  initialSelected,
  onClose,
  onApply,
}: QuestionBankPickerProps) {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<NotebookEntry[]>([]);
  const [categories, setCategories] = useState<NotebookCategory[]>([]);
  const [materials, setMaterials] = useState<QuestionBankMaterial[]>([]);
  const [filter, setFilter] = useState<FilterMode>("all");
  const [activeCategoryId, setActiveCategoryId] = useState<number | null>(null);
  const [activeMaterialId, setActiveMaterialId] = useState("");
  const [selectedById, setSelectedById] = useState<Map<number, SelectedQuestionEntry>>(
    () => new Map(),
  );
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open) {
      setSelectedById(new Map(initialSelected.map((entry) => [entry.id, entry])));
    }
  }, [open, initialSelected]);

  useEffect(() => {
    if (!open) return;
    let mounted = true;
    void (async () => {
      try {
        const [nextCategories, nextMaterials] = await Promise.all([
          listCategories(),
          listQuestionBankMaterials(),
        ]);
        if (mounted) {
          setCategories(nextCategories);
          setMaterials(nextMaterials);
        }
      } catch {
        if (mounted) {
          setCategories([]);
          setMaterials([]);
        }
      }
    })();
    return () => {
      mounted = false;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let mounted = true;
    setLoading(true);
    void (async () => {
      try {
        const items: NotebookEntry[] = [];
        let total = 0;
        do {
          const result = await listNotebookEntries({
            bookmarked: filter === "bookmarked" ? true : undefined,
            is_correct: filter === "wrong" ? false : undefined,
            category_id: activeCategoryId ?? undefined,
            material_id: activeMaterialId || undefined,
            limit: 200,
            offset: items.length,
          });
          items.push(...result.items);
          total = result.total;
          if (!result.items.length) break;
        } while (items.length < total && mounted);
        if (!mounted) return;
        setEntries(items);
      } catch {
        if (!mounted) return;
        setEntries([]);
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [open, filter, activeCategoryId, activeMaterialId]);

  const filteredEntries = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return entries;
    return entries.filter((entry) => {
      const question = String(entry.question || "").toLowerCase();
      const provenance = provenanceLabel(entry).toLowerCase();
      return question.includes(keyword) || provenance.includes(keyword);
    });
  }, [entries, query]);

  const asSelected = (entry: NotebookEntry): SelectedQuestionEntry => ({
    id: entry.id,
    question: entry.question,
    session_title: entry.session_title,
    is_correct: entry.is_correct,
    difficulty: entry.difficulty || "",
  });

  const toggleEntry = (entry: NotebookEntry) => {
    setSelectedById((prev) => {
      const next = new Map(prev);
      if (next.has(entry.id)) next.delete(entry.id);
      else next.set(entry.id, asSelected(entry));
      return next;
    });
  };

  const selectVisible = () => {
    setSelectedById((prev) => {
      const next = new Map(prev);
      filteredEntries.forEach((entry) => next.set(entry.id, asSelected(entry)));
      return next;
    });
  };

  const handleApply = () => {
    onApply([...selectedById.values()]);
    onClose();
  };

  return (
    <PickerShell
      open={open}
      onClose={onClose}
      labelledBy="question-bank-picker-title"
      className="p-4 backdrop-blur-md"
      backdropClass="bg-[var(--background)]/65"
    >
      <div className="surface-card w-full max-w-4xl overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] text-[var(--card-foreground)] shadow-[0_22px_70px_rgba(0,0,0,0.18)]">
        <PickerHeader
          resourceKind="question_bank"
          icon={ClipboardList}
          titleId="question-bank-picker-title"
          title={t("Select Question Bank Entries")}
          subtitle={t("Choose quiz questions to ground the next request.")}
          onClose={onClose}
        />

        <div className="bg-[var(--background)]/40 p-5">
          {/* Filter row */}
          <div className="mb-3 flex flex-wrap items-center gap-1">
            {FILTER_MODES.map(({ value, label }) => {
              const active = filter === value && activeCategoryId === null;
              return (
                <button
                  key={value}
                  onClick={() => {
                    setFilter(value);
                    setActiveCategoryId(null);
                  }}
                  className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] transition-colors ${
                    active
                      ? "bg-[var(--muted)] font-medium text-[var(--foreground)]"
                      : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  }`}
                >
                  {t(label)}
                </button>
              );
            })}
            {categories.length > 0 && (
              <span className="mx-1 text-[var(--border)]">|</span>
            )}
            {categories.map((cat) => {
              const active = activeCategoryId === cat.id;
              return (
                <button
                  key={cat.id}
                  onClick={() => {
                    setActiveCategoryId(cat.id);
                    setFilter("all");
                  }}
                  className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] transition-colors ${
                    active
                      ? "bg-[var(--muted)] font-medium text-[var(--foreground)]"
                      : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  }`}
                >
                  <FolderOpen size={11} />
                  {cat.name}
                </button>
              );
            })}
          </div>

          <div className="mb-3">
            <select
              value={activeMaterialId}
              onChange={(event) => setActiveMaterialId(event.target.value)}
              aria-label={t("Material")}
              className="w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-[12px] text-[var(--foreground)] outline-none sm:max-w-xs"
            >
              <option value="">{t("All Materials")}</option>
              {materials.map((material) => (
                <option key={`${material.source}:${material.material_id}`} value={material.material_id}>
                  {material.material_title}
                </option>
              ))}
            </select>
          </div>

          <div className="mb-4 flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("Search questions by content")}
                className="w-full rounded-xl border border-[var(--border)] bg-[var(--card)] py-2.5 pl-9 pr-3 text-[13px] text-[var(--foreground)] outline-none transition focus:border-[var(--primary)]/50 focus:ring-2 focus:ring-[var(--primary)]/15"
              />
            </div>
            <button
              type="button"
              onClick={selectVisible}
              disabled={loading || !filteredEntries.length || filteredEntries.every((entry) => selectedById.has(entry.id))}
              className="rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {t("Select all")} ({filteredEntries.length})
            </button>
            <button
              type="button"
              onClick={() => setSelectedById(new Map())}
              className="rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              {t("Clear")}
            </button>
          </div>

          <div className="max-h-[56vh] overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--card)]">
            {loading ? (
              <div className="flex min-h-[280px] items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
              </div>
            ) : filteredEntries.length ? (
              <div className="divide-y divide-[var(--border)]">
                {filteredEntries.map((entry) => {
                  const selected = selectedById.has(entry.id);
                  return (
                    <button
                      key={entry.id}
                      onClick={() => toggleEntry(entry)}
                      aria-pressed={selected}
                      className={`flex w-full items-start gap-3 px-4 py-3 text-left transition-colors ${
                        selected
                          ? "bg-[var(--primary)]/8"
                          : "hover:bg-[var(--muted)]/40"
                      }`}
                    >
                      <div
                        className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors ${
                          selected
                            ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                            : "border-[var(--border)] text-transparent"
                        }`}
                      >
                        <Check size={12} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          {entry.difficulty && (
                            <span
                              className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase ${
                                entry.difficulty === "hard"
                                  ? "bg-red-50 text-red-600 dark:bg-red-950/30 dark:text-red-400"
                                  : entry.difficulty === "medium"
                                    ? "bg-amber-50 text-amber-600 dark:bg-amber-950/30 dark:text-amber-400"
                                    : "bg-green-50 text-green-600 dark:bg-green-950/30 dark:text-green-400"
                              }`}
                            >
                              {entry.difficulty}
                            </span>
                          )}
                          {entry.question_type && (
                            <span className="rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                              {entry.question_type}
                            </span>
                          )}
                          <span
                            className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${
                              entry.is_correct
                                ? "bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-400"
                                : "bg-red-100 text-red-700 dark:bg-red-950/30 dark:text-red-400"
                            }`}
                          >
                            {entry.is_correct ? t("Correct") : t("Incorrect")}
                          </span>
                          {entry.bookmarked && (
                            <Bookmark
                              size={11}
                              className="text-[var(--primary)]"
                              fill="currentColor"
                            />
                          )}
                        </div>
                        <p className="mt-1 line-clamp-2 text-[13px] leading-5 text-[var(--foreground)]">
                          {entry.question}
                        </p>
                        {provenanceLabel(entry) && (
                          <div className="mt-1 truncate text-[11px] text-[var(--muted-foreground)]/85">
                            {provenanceLabel(entry)}
                          </div>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="px-6 py-14 text-center text-[13px] text-[var(--muted-foreground)]">
                {entries.length === 0
                  ? t("No quiz entries yet.")
                  : t("No matching questions found.")}
              </div>
            )}
          </div>

          <div className="mt-4 flex items-center justify-between gap-3">
            <div className="text-[12px] text-[var(--muted-foreground)]">
              {selectedById.size === 1
                ? t("1 question selected")
                : t("{{n}} questions selected", { n: selectedById.size })}
            </div>
            <button
              type="button"
              onClick={handleApply}
              disabled={!selectedById.size && !initialSelected.length}
              className="btn-primary rounded-xl bg-[var(--primary)] px-4 py-2.5 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {selectedById.size
                ? t("Use Selected Questions ({{n}})", { n: selectedById.size })
                : t("Clear selection")}
            </button>
          </div>
        </div>
      </div>
    </PickerShell>
  );
}
