"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { AlertTriangle, ClipboardList, Inbox, Loader2, School, Search, X } from "lucide-react";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import { listCourses, type StudyCourse } from "@/lib/courses-api";
import BankScopeRail from "./BankScopeRail";
import BankSelectionBar from "./BankSelectionBar";
import BankToolbar from "./BankToolbar";
import CategoryManager from "./CategoryManager";
import QuestionCard from "./QuestionCard";
import { useQuestionBank } from "./useQuestionBank";

function EmptyState({
  icon: Icon,
  title,
  hint,
}: {
  icon: typeof ClipboardList;
  title: string;
  hint: string;
}) {
  return (
    <div className="flex min-h-[300px] flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border)] text-center">
      <div className="mb-3 rounded-xl bg-[var(--muted)] p-2.5 text-[var(--muted-foreground)]">
        <Icon size={18} />
      </div>
      <p className="text-[14px] font-medium text-[var(--foreground)]">{title}</p>
      <p className="mt-1.5 max-w-xs text-[13px] text-[var(--muted-foreground)]">{hint}</p>
    </div>
  );
}

/**
 * Learning Space → Question Bank.
 *
 * Everything stateful lives in ``useQuestionBank``; this file is layout and
 * which empty state to show. The three jobs it has to support are review
 * (read a question back), triage (work the unfiled pile down), and filing
 * (put questions into a set) — the last one being what the surface used to
 * make impossible: categories could be created but never filled.
 */
export default function QuestionBankSection({
  embedded = false,
  mistakesOnly = false,
  onPractice,
  onChanged,
}: {
  embedded?: boolean;
  mistakesOnly?: boolean;
  onPractice?: (ids: number[]) => void;
  onChanged?: () => void;
}) {
  const { t } = useTranslation();
  const router = useRouter();
  // A course arrives in the URL — from its page or from a Course Study
  // hand-off — and narrows the whole surface for the visit. It is deliberately
  // not part of the scope rail: the learner keeps clicking through wrong /
  // bookmarked / a category *inside* the course.
  const courseId = useSearchParams().get("course")?.trim() ?? "";
  const bank = useQuestionBank({ courseId, mistakesOnly });
  useEffect(() => {
    onChanged?.();
  }, [bank.stats, onChanged]);
  const [course, setCourse] = useState<StudyCourse | null>(null);

  useEffect(() => {
    if (!courseId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCourse(null);
      return;
    }
    let cancelled = false;
    void listCourses()
      .then(courses => {
        if (!cancelled) setCourse(courses.find(item => item.id === courseId) ?? null);
      })
      .catch(() => {
        // The scope still applies server-side; only its name is missing, and
        // the chip falls back to saying "this course".
        if (!cancelled) setCourse(null);
      });
    return () => {
      cancelled = true;
    };
  }, [courseId]);
  const [managerOpen, setManagerOpen] = useState(false);

  const selectedIds = Array.from(bank.selectedIds);
  const searching = bank.searchInput.trim().length > 0;

  return (
    <div className="space-y-3">
      {!embedded && (
        <SpaceSectionHeader
          icon={ClipboardList}
          title={t("Question Bank")}
          description={t(
            "Review and organize quiz questions across sessions. Bookmark items, group them into categories, and jump back to the original chat.",
          )}
          meta={
            <>
              <span className="rounded-full border border-[var(--border)] bg-[var(--card)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]">
                {bank.stats.total} {t("questions.count.suffix")}
              </span>
              {courseId ? (
                <span className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--card)] py-0.5 pl-2 pr-1 text-[10.5px] font-medium text-[var(--muted-foreground)]">
                  <Link
                    href={`/courses/${courseId}`}
                    className="inline-flex items-center gap-1 transition-colors hover:text-[var(--foreground)]"
                  >
                    <School size={11} strokeWidth={1.8} />
                    {course?.name || t("This course")}
                  </Link>
                  <button
                    type="button"
                    onClick={() => router.replace("/space/questions")}
                    aria-label={t("Show every course")}
                    className="rounded-full p-0.5 transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                  >
                    <X size={11} />
                  </button>
                </span>
              ) : null}
            </>
          }
        />
      )}

      {onPractice && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-[var(--muted-foreground)]">
            {mistakesOnly
              ? t(
                  "Mistakes stay here after review. Mark a question resolved to pause its daily reviews.",
                )
              : t("Questions from every source, together with your own imports.")}
          </p>
          <button
            type="button"
            disabled={bank.loading || bank.refreshing || !bank.items.length}
            onClick={() =>
              onPractice(selectedIds.length ? selectedIds : bank.items.map(item => item.id))
            }
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium hover:bg-[var(--muted)] disabled:opacity-40"
          >
            {selectedIds.length
              ? t("Practice selected ({{count}})", { count: selectedIds.length })
              : t("Practice this page")}
          </button>
        </div>
      )}

      <BankToolbar
        search={bank.searchInput}
        sort={bank.sort}
        refreshing={bank.refreshing}
        managerOpen={managerOpen}
        filters={bank.reviewFilters}
        materials={bank.materials}
        onSearchChange={bank.setSearchInput}
        onSortChange={bank.setSort}
        onFiltersChange={bank.setReviewFilters}
        onToggleManager={() => setManagerOpen(open => !open)}
      />

      {managerOpen && (
        <CategoryManager
          categories={bank.categories}
          onCreate={bank.addCategory}
          onRename={bank.renameExistingCategory}
          onDelete={bank.removeCategory}
        />
      )}

      <BankScopeRail
        scope={bank.scope}
        stats={bank.stats}
        categories={bank.categories}
        onSelect={bank.setScope}
        collectionMode={embedded}
      />

      {bank.loading ? (
        <div className="flex min-h-[300px] items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
        </div>
      ) : bank.error ? (
        <div className="flex min-h-[300px] flex-col items-center justify-center rounded-xl border border-dashed border-red-300 text-center dark:border-red-900">
          <div className="mb-3 rounded-xl bg-red-50 p-2.5 text-red-500 dark:bg-red-950/30">
            <AlertTriangle size={18} />
          </div>
          <p className="text-[14px] font-medium text-[var(--foreground)]">
            {t("Failed to load entries")}
          </p>
          <p className="mt-1.5 max-w-xs text-[13px] text-[var(--muted-foreground)]">{bank.error}</p>
          <button
            type="button"
            onClick={() => void bank.refresh()}
            className="mt-3 rounded-lg bg-[var(--primary)] px-4 py-1.5 text-[12px] font-medium text-white"
          >
            {t("Retry")}
          </button>
        </div>
      ) : bank.items.length === 0 ? (
        searching ? (
          <EmptyState
            icon={Search}
            title={t("No matching questions")}
            hint={t("Try a different word, or clear the search to see everything.")}
          />
        ) : bank.scope.kind === "uncategorized" ? (
          <EmptyState
            icon={Inbox}
            title={t("Everything is filed")}
            hint={t("No questions are waiting to be sorted into a category.")}
          />
        ) : bank.stats.total === 0 ? (
          courseId ? (
            <EmptyState
              icon={ClipboardList}
              title={t("No questions from this course yet")}
              hint={t("Questions you answer in this course's conversations collect here.")}
            />
          ) : (
            <EmptyState
              icon={ClipboardList}
              title={t("No entries yet")}
              hint={t("Questions from your quizzes will appear here.")}
            />
          )
        ) : (
          <EmptyState
            icon={ClipboardList}
            title={t("Nothing in this view")}
            hint={t("Switch to another filter to see your other questions.")}
          />
        )
      ) : (
        <>
          <ul
            className={`flex flex-col gap-2.5 transition-opacity ${
              bank.refreshing ? "opacity-60" : ""
            }`}
          >
            {bank.items.map(entry => (
              <QuestionCard
                key={entry.id}
                entry={entry}
                mistakesOnly={mistakesOnly}
                collapseAnswers={embedded}
                categories={bank.categories}
                selected={bank.selectedIds.has(entry.id)}
                disabled={bank.pendingIds.has(entry.id)}
                onToggleSelected={() => bank.toggleSelected(entry.id)}
                onToggleBookmark={() => void bank.toggleBookmark(entry)}
                onToggleResolved={() => void bank.toggleResolved(entry)}
                onDelete={() => {
                  if (window.confirm(t("Delete this entry?"))) void bank.removeEntry(entry);
                }}
                onFile={categoryId => bank.fileEntries([entry.id], categoryId)}
                onUnfile={categoryId => bank.unfileEntries([entry.id], categoryId)}
                onCreateAndFile={name => bank.fileIntoNewCategory([entry.id], name)}
              />
            ))}
          </ul>

          {(bank.total > 60 || bank.page > 0) && (
            <nav
              aria-label={t("Question pages")}
              className="flex items-center justify-center gap-4 py-3 text-sm"
            >
              <button
                type="button"
                disabled={bank.page === 0 || bank.refreshing}
                onClick={() => bank.setPage(bank.page - 1)}
                className="rounded-lg border border-[var(--border)] px-3 py-2 disabled:opacity-40"
              >
                {t("Previous page")}
              </button>
              <span className="text-[var(--muted-foreground)]">
                {t("Page {{page}} of {{pages}}", {
                  page: bank.page + 1,
                  pages: Math.max(1, Math.ceil(bank.total / 60)),
                })}
              </span>
              <button
                type="button"
                disabled={(bank.page + 1) * 60 >= bank.total || bank.refreshing}
                onClick={() => bank.setPage(bank.page + 1)}
                className="rounded-lg border border-[var(--border)] px-3 py-2 disabled:opacity-40"
              >
                {t("Next page")}
              </button>
            </nav>
          )}

          <BankSelectionBar
            count={selectedIds.length}
            visibleCount={bank.items.length}
            scope={bank.scope}
            categories={bank.categories}
            onSelectAll={bank.selectAll}
            onClear={bank.clearSelection}
            // Clear the selection only when the write landed — a failed
            // bulk action should leave the rows staged for a retry.
            onFile={async categoryId => {
              const ok = await bank.fileEntries(selectedIds, categoryId);
              if (ok) bank.clearSelection();
              return ok;
            }}
            onCreateAndFile={async name => {
              const ok = await bank.fileIntoNewCategory(selectedIds, name);
              if (ok) bank.clearSelection();
              return ok;
            }}
            onUnfileFromCurrent={async () => {
              if (bank.scope.kind !== "category") return false;
              const ok = await bank.unfileEntries(selectedIds, bank.scope.categoryId);
              if (ok) bank.clearSelection();
              return ok;
            }}
          />
        </>
      )}
    </div>
  );
}
