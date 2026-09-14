"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { ArrowLeft, ClipboardList, RefreshCw, Send } from "lucide-react";
import { fetchAuthStatus } from "@/lib/auth";
import { fetchClassRosters, type ClassRoster } from "@/lib/class-insights-api";
import { fetchAllProgress } from "@/lib/learning-api";
import {
  createAssignment,
  fetchKpQuestions,
  fetchTeacherAssignments,
  type KpQuestionOption,
  type TeacherAssignment,
} from "@/lib/assignments-api";

// Teacher-facing page; students are redirected away at the route level (the
// backend enforces the same gate with 403).
const ALLOWED_ROLES = new Set(["admin", "teacher"]);

export default function AssignmentsPage() {
  const router = useRouter();
  const { t } = useTranslation();

  const [rosters, setRosters] = useState<ClassRoster[]>([]);
  const [classId, setClassId] = useState("");
  const [books, setBooks] = useState<{ book_id: string; name: string }[]>([]);
  const [bookId, setBookId] = useState("");
  const [kps, setKps] = useState<KpQuestionOption[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [title, setTitle] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [assignments, setAssignments] = useState<TeacherAssignment[]>([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadAssignments = useCallback(async (cid: string) => {
    try {
      const data = await fetchTeacherAssignments(cid || undefined);
      setAssignments(data.assignments);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Failed to load assignments"));
    }
  }, [t]);

  useEffect(() => {
    fetchAuthStatus().then((status) => {
      if (!status?.authenticated) {
        router.replace("/login");
        return;
      }
      if (!ALLOWED_ROLES.has(status.role ?? "")) {
        router.replace("/");
        return;
      }
      fetchClassRosters()
        .then((r) => setRosters(r.classes))
        .catch(() => setRosters([]));
      fetchAllProgress()
        .then((r) => setBooks(r.summaries))
        .catch(() => setBooks([]));
      void loadAssignments("");
    });
  }, [router, loadAssignments]);

  const loadKps = useCallback(
    async (bid: string) => {
      setKps([]);
      setSelected(new Set());
      if (!bid) return;
      try {
        const data = await fetchKpQuestions(bid);
        setKps(data.kps);
      } catch (e) {
        setError(e instanceof Error ? e.message : t("Failed to load knowledge points"));
      }
    },
    [t],
  );

  const toggleKp = (kpId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(kpId)) next.delete(kpId);
      else next.add(kpId);
      return next;
    });
  };

  const submit = async () => {
    setError("");
    setNotice("");
    if (!classId) {
      setError(t("Select a class first"));
      return;
    }
    if (!bookId) {
      setError(t("Select a book first"));
      return;
    }
    if (!title.trim() || selected.size === 0) {
      setError(t("Enter a title and select at least one knowledge point"));
      return;
    }
    setCreating(true);
    try {
      const result = await createAssignment({
        class_id: classId,
        book_id: bookId,
        title: title.trim(),
        kp_ids: [...selected],
        due_at: dueAt || undefined,
      });
      const skipped = result.skipped.length
        ? ` (${t("Skipped {{count}} knowledge points without an assignable question", {
            count: result.skipped.length,
          })})`
        : "";
      setNotice(`${t("Assignment created")}${skipped}`);
      setTitle("");
      setSelected(new Set());
      await loadAssignments(classId);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Failed to create assignment"));
    } finally {
      setCreating(false);
    }
  };

  const assignedCount = kps.filter((kp) => kp.has_question).length;

  return (
    <div className="h-screen overflow-y-auto bg-[var(--background)] px-4 py-10 [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-4xl">
        <div className="mb-8">
          <Link
            href="/"
            className="mb-4 inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
          >
            <ArrowLeft size={16} />
            {t("Back")}
          </Link>
          <h1 className="font-serif text-xl font-semibold text-[var(--foreground)]">
            {t("Assignments")}
          </h1>
          <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
            {t("Assign homework from your question bank and review class results")}
          </p>
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        )}
        {notice && (
          <div className="mb-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-600 dark:text-emerald-400">
            {notice}
          </div>
        )}

        {/* 布置表单: 班级 → 书 → KP 多选 → 布置 */}
        <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
          <h2 className="font-serif text-base font-semibold text-[var(--foreground)]">
            {t("New assignment")}
          </h2>

          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">
                {t("Class")}
              </span>
              <select
                value={classId}
                onChange={(e) => {
                  setClassId(e.target.value);
                  void loadAssignments(e.target.value);
                }}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)] outline-none transition-colors hover:border-teal-500/40 focus:border-teal-500/60"
              >
                <option value="">{t("Select a class")}</option>
                {rosters.map((roster) => (
                  <option key={roster.id} value={roster.id}>
                    {roster.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">
                {t("Book")}
              </span>
              <select
                value={bookId}
                onChange={(e) => {
                  setBookId(e.target.value);
                  void loadKps(e.target.value);
                }}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)] outline-none transition-colors hover:border-teal-500/40 focus:border-teal-500/60"
              >
                <option value="">{t("Select a book")}</option>
                {books.map((book) => (
                  <option key={book.book_id} value={book.book_id}>
                    {book.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">
                {t("Due date (optional)")}
              </span>
              <input
                type="date"
                value={dueAt}
                onChange={(e) => setDueAt(e.target.value)}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)] outline-none transition-colors hover:border-teal-500/40 focus:border-teal-500/60"
              />
            </label>
          </div>

          {bookId && (
            <div className="mt-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-medium text-[var(--muted-foreground)]">
                  {t("Knowledge points")}
                </span>
                <span className="text-xs text-[var(--muted-foreground)]">
                  {t("{{count}} selectable", { count: assignedCount })}
                </span>
              </div>
              {kps.length === 0 ? (
                <p className="text-sm text-[var(--muted-foreground)]">
                  {t("No knowledge points in this book yet")}
                </p>
              ) : (
                <ul className="max-h-64 space-y-1 overflow-y-auto rounded-lg border border-[var(--border)] p-2">
                  {kps.map((kp) => (
                    <li key={kp.kp_id}>
                      <label
                        className={`flex cursor-pointer items-start gap-2 rounded-lg px-2 py-1.5 transition-colors hover:bg-[var(--background)] ${
                          kp.has_question ? "" : "opacity-50"
                        }`}
                      >
                        <input
                          type="checkbox"
                          className="mt-1 accent-teal-600"
                          disabled={!kp.has_question}
                          checked={selected.has(kp.kp_id)}
                          onChange={() => toggleKp(kp.kp_id)}
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium text-[var(--foreground)]">
                            {kp.name}
                          </span>
                          {kp.preview && (
                            <span className="mt-0.5 block truncate text-xs text-[var(--muted-foreground)]">
                              {kp.preview.stem}
                              {kp.preview.options.length > 0 &&
                                ` · ${kp.preview.options.join(" / ")}`}
                            </span>
                          )}
                          {!kp.has_question && (
                            <span className="mt-0.5 block text-xs text-[var(--muted-foreground)]">
                              {t("No choice question bound")}
                            </span>
                          )}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-end gap-3">
            <label className="min-w-48 flex-1">
              <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">
                {t("Title")}
              </span>
              <input
                type="text"
                value={title}
                maxLength={200}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={t("Assignment title")}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)] outline-none transition-colors hover:border-teal-500/40 focus:border-teal-500/60"
              />
            </label>
            <button
              onClick={submit}
              disabled={creating}
              className="flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-4 py-2 text-sm font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              <Send size={14} />
              {creating ? t("Creating…") : t("Assign")}
            </button>
          </div>
        </section>

        {/* 作业列表 + 统计 */}
        <section className="mt-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-serif text-base font-semibold text-[var(--foreground)]">
              {t("Assigned homework")}
            </h2>
            <button
              onClick={() => loadAssignments(classId)}
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm border border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--card)] transition-colors"
            >
              <RefreshCw size={14} />
              {t("Refresh")}
            </button>
          </div>

          {assignments.length === 0 ? (
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] px-6 py-14 text-center shadow-sm">
              <ClipboardList
                size={28}
                strokeWidth={1.5}
                className="mx-auto text-[var(--muted-foreground)]/50"
              />
              <p className="mt-3 text-sm font-medium text-[var(--foreground)]">
                {t("No assignments yet")}
              </p>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                {t("Assignments you create will appear here with class statistics.")}
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {assignments.map((assignment) => (
                <div
                  key={assignment.assignment_id}
                  className="rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] px-5 py-3">
                    <div>
                      <h3 className="text-sm font-semibold text-[var(--foreground)]">
                        {assignment.title}
                      </h3>
                      <p className="text-xs text-[var(--muted-foreground)]">
                        {t("{{count}} questions", { count: assignment.item_count })}
                        {assignment.due_at
                          ? ` · ${t("Due {{date}}", { date: assignment.due_at.slice(0, 10) })}`
                          : ""}
                      </p>
                    </div>
                    <span className="text-xs text-[var(--muted-foreground)]">
                      {t("{{submitted}}/{{total}} submitted", {
                        submitted: assignment.students.filter((s) => s.submitted).length,
                        total: assignment.students.length,
                      })}
                    </span>
                  </div>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs uppercase tracking-wider text-[var(--muted-foreground)]">
                        <th className="px-5 py-2 font-medium">{t("Student")}</th>
                        <th className="px-5 py-2 font-medium">{t("Status")}</th>
                        <th className="px-5 py-2 font-medium">{t("Correct")}</th>
                        <th className="px-5 py-2 font-medium">
                          {t("Per knowledge point")}
                        </th>
                        <th className="px-5 py-2 font-medium">
                          {t("Per question type")}
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border)]">
                      {assignment.students.map((student) => (
                        <tr
                          key={student.username}
                          className="hover:bg-[var(--background)]/50 transition-colors"
                        >
                          <td className="px-5 py-2.5 font-medium text-[var(--foreground)]">
                            {student.username}
                          </td>
                          <td className="px-5 py-2.5">
                            {student.submitted ? (
                              <span className="text-emerald-600 dark:text-emerald-400">
                                {t("Submitted")}
                              </span>
                            ) : (
                              <span className="text-[var(--muted-foreground)]">
                                {t("Not submitted")}
                              </span>
                            )}
                          </td>
                          <td className="px-5 py-2.5 tabular-nums text-[var(--foreground)]">
                            {student.submitted
                              ? `${student.correct}/${student.total}`
                              : "—"}
                          </td>
                          <td className="px-5 py-2.5">
                            <div className="flex flex-wrap gap-1">
                              {student.per_kp.map((kp) => (
                                <span
                                  key={kp.kp_id}
                                  className="inline-flex items-center rounded-full bg-[var(--muted)]/60 px-2 py-0.5 text-xs tabular-nums text-[var(--muted-foreground)]"
                                >
                                  {kp.correct}/{kp.total}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td className="px-5 py-2.5">
                            <div className="flex flex-wrap gap-1">
                              {student.per_type.map((byType) => (
                                <span
                                  key={byType.type}
                                  className="inline-flex items-center gap-1 rounded-full bg-[var(--muted)]/60 px-2 py-0.5 text-xs tabular-nums text-[var(--muted-foreground)]"
                                >
                                  {byType.type === "short"
                                    ? t("Short answer")
                                    : t("Choice")}
                                  {byType.correct}/{byType.total}
                                </span>
                              ))}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
