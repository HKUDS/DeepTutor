"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { ArrowLeft, GraduationCap, RefreshCw, Users } from "lucide-react";
import { fetchAuthStatus } from "@/lib/auth";
import {
  fetchClassInsights,
  fetchClassRosters,
  type ClassInsightsOverview,
  type ClassRoster,
} from "@/lib/class-insights-api";
import { formatDate as formatLocaleDate, type Language } from "@/lib/datetime";

// Teacher-facing roles for the class insights page; students are redirected
// away at the route level (the backend enforces the same gate with 403).
const ALLOWED_ROLES = new Set(["admin", "teacher"]);

type Tier = "good" | "warn" | "bad";

/** 悦学 红绿表: ≥0.9 green, 0.6–0.9 yellow, <0.6 red. */
function tierOf(avgMasteryPct: number): Tier {
  if (avgMasteryPct >= 90) return "good";
  if (avgMasteryPct >= 60) return "warn";
  return "bad";
}

const TIER_BAR: Record<Tier, string> = {
  good: "bg-emerald-500",
  warn: "bg-amber-500",
  bad: "bg-red-500",
};

const TIER_TEXT: Record<Tier, string> = {
  good: "text-emerald-600 dark:text-emerald-400",
  warn: "text-amber-600 dark:text-amber-400",
  bad: "text-red-600 dark:text-red-400",
};

function formatActive(iso: string | null, lang: Language): string {
  if (!iso) return "—";
  try {
    return formatLocaleDate(new Date(iso), lang);
  } catch {
    return "—";
  }
}

export default function AdminClassInsightsPage() {
  const router = useRouter();
  const { t, i18n } = useTranslation();
  const lang: Language = i18n.language?.startsWith("zh") ? "zh" : "en";
  const [overview, setOverview] = useState<ClassInsightsOverview | null>(null);
  const [rosters, setRosters] = useState<ClassRoster[]>([]);
  const [selectedClass, setSelectedClass] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(
    async (classId: string = "") => {
      setLoading(true);
      setError("");
      try {
        setOverview(await fetchClassInsights(classId || undefined));
      } catch (e) {
        setError(e instanceof Error ? e.message : t("Failed to load class insights"));
      } finally {
        setLoading(false);
      }
    },
    [t],
  );

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
      // K12 班级过滤：rosters load failure must not block the flat view.
      fetchClassRosters()
        .then((r) => setRosters(r.classes))
        .catch(() => setRosters([]));
      void load();
    });
  }, [router, load]);

  const selectClass = (classId: string) => {
    setSelectedClass(classId);
    void load(classId);
  };

  const students = overview?.students ?? [];
  const sorted = [...students].sort(
    (a, b) => a.avg_mastery_pct - b.avg_mastery_pct,
  );

  return (
    <div className="h-screen overflow-y-auto bg-[var(--background)] px-4 py-10 [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-4xl">
        {/* Header */}
        <div className="mb-8">
          <Link
            href="/"
            className="mb-4 inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
          >
            <ArrowLeft size={16} />
            {t("Back")}
          </Link>
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="font-serif text-xl font-semibold text-[var(--foreground)]">
                {t("Class Insights")}
              </h1>
              <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
                {overview?.class?.name ?? t("Per-student mastery overview")}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {rosters.length > 0 && (
                <select
                  value={selectedClass}
                  onChange={(e) => selectClass(e.target.value)}
                  className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-2.5 py-1.5
                             text-sm text-[var(--foreground)] outline-none transition-colors
                             hover:border-teal-500/40 focus:border-teal-500/60"
                  aria-label={t("Filter by class")}
                >
                  <option value="">{t("All students")}</option>
                  {rosters.map((roster) => (
                    <option key={roster.id} value={roster.id}>
                      {roster.name}
                    </option>
                  ))}
                </select>
              )}
              <button
                onClick={() => load(selectedClass)}
                disabled={loading}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm
                           border border-[var(--border)] text-[var(--muted-foreground)]
                           hover:text-[var(--foreground)] hover:bg-[var(--card)]
                           disabled:opacity-50 transition-colors"
              >
                <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
                {t("Refresh")}
              </button>
            </div>
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        )}

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] overflow-hidden shadow-sm">
          {loading ? (
            <div className="divide-y divide-[var(--border)]" aria-hidden>
              {[0, 1, 2].map((row) => (
                <div
                  key={row}
                  className="flex animate-pulse items-center gap-3 px-5 py-4"
                >
                  <div className="h-8 w-8 rounded-full bg-[var(--muted)]/60" />
                  <div className="flex-1 space-y-2">
                    <div className="h-3 w-36 rounded bg-[var(--muted)]/60" />
                    <div className="h-2.5 w-24 rounded bg-[var(--muted)]/40" />
                  </div>
                </div>
              ))}
            </div>
          ) : !error && sorted.length === 0 ? (
            <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
              <Users
                size={28}
                strokeWidth={1.5}
                className="text-[var(--muted-foreground)]/50"
              />
              <p className="mt-3 text-sm font-medium text-[var(--foreground)]">
                {t("No students yet")}
              </p>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                {t("Students with learning progress will appear here.")}
              </p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--muted-foreground)] uppercase tracking-wider">
                  <th className="px-5 py-3 font-medium">{t("Student")}</th>
                  <th className="px-5 py-3 font-medium text-center">
                    {t("KP Total")}
                  </th>
                  <th className="px-5 py-3 font-medium">
                    {t("Average Mastery")}
                  </th>
                  <th className="px-5 py-3 font-medium">
                    {t("Weak Knowledge Points")}
                  </th>
                  <th className="px-5 py-3 font-medium">{t("Last Active")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {sorted.map((student) => {
                  const tier = tierOf(student.avg_mastery_pct);
                  return (
                    <tr
                      key={student.username}
                      className="group hover:bg-[var(--background)]/50 transition-colors"
                    >
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-3">
                          <span
                            className={`h-2.5 w-2.5 shrink-0 rounded-full ${TIER_BAR[tier]}`}
                            aria-hidden
                          />
                          <span className="min-w-0 truncate font-medium text-[var(--foreground)]">
                            {student.username}
                          </span>
                        </div>
                      </td>
                      <td className="px-5 py-3 text-center text-[var(--muted-foreground)]">
                        {student.no_data ? (
                          <span
                            className="inline-flex items-center rounded-full bg-[var(--muted)]/60 px-2 py-0.5 text-xs text-[var(--muted-foreground)]"
                          >
                            {t("No learning data yet")}
                          </span>
                        ) : (
                          student.kp_total
                        )}
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-2">
                          <div className="h-2 w-28 overflow-hidden rounded-full bg-[var(--muted)]/50">
                            <div
                              className={`h-full rounded-full ${TIER_BAR[tier]}`}
                              style={{
                                width: `${Math.min(100, student.avg_mastery_pct)}%`,
                              }}
                            />
                          </div>
                          <span
                            className={`w-10 shrink-0 text-xs font-medium tabular-nums ${TIER_TEXT[tier]}`}
                          >
                            {student.avg_mastery_pct}%
                          </span>
                        </div>
                      </td>
                      <td className="px-5 py-3">
                        {student.weak.length === 0 ? (
                          <span className="text-xs text-[var(--muted-foreground)]">
                            {t("No weak knowledge points")}
                          </span>
                        ) : (
                          <div className="flex max-w-xs flex-wrap gap-1">
                            {student.weak.slice(0, 5).map((kp) => (
                              <span
                                key={kp.kp_id}
                                title={kp.name}
                                className="inline-flex max-w-full items-center gap-1 rounded-full
                                           bg-red-500/10 px-2 py-0.5 text-xs text-red-600
                                           dark:text-red-400"
                              >
                                <span className="truncate">{kp.name}</span>
                                <span className="shrink-0 opacity-70">
                                  {Math.round(kp.mastery * 100)}%
                                </span>
                              </span>
                            ))}
                            {student.weak.length > 5 && (
                              <span className="text-xs text-[var(--muted-foreground)]">
                                +{student.weak.length - 5}
                              </span>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="px-5 py-3 text-[var(--muted-foreground)]">
                        {formatActive(student.last_active, lang)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {overview && (
          <p className="mt-4 flex items-center justify-center gap-1.5 text-xs text-[var(--muted-foreground)]">
            <GraduationCap size={13} />
            {t("Generated at {{time}}", {
              time: formatActive(overview.generated_at, lang),
            })}
          </p>
        )}
      </div>
    </div>
  );
}
