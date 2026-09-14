"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Home, RefreshCw, Users } from "lucide-react";
import { fetchAuthStatus } from "@/lib/auth";
import {
  fetchMyChildren,
  type ClassInsightsOverview,
} from "@/lib/class-insights-api";
import { formatDate as formatLocaleDate, type Language } from "@/lib/datetime";

// 家庭视图：家长（children 白名单）与 admin（全体，运维复用）。学生/教师 403，
// 与后端 /class-insights/my-children 门禁一致。
const ALLOWED_ROLES = new Set(["admin", "parent"]);

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

export default function FamilyInsightsPage() {
  const router = useRouter();
  const { t, i18n } = useTranslation();
  const lang: Language = i18n.language?.startsWith("zh") ? "zh" : "en";
  const [overview, setOverview] = useState<ClassInsightsOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setOverview(await fetchMyChildren());
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Failed to load family insights"));
    } finally {
      setLoading(false);
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
      void load();
    });
  }, [router, load]);

  const children = overview?.students ?? [];
  const sorted = [...children].sort(
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
                {t("My Children")}
              </h1>
              <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
                {t("Per-child mastery overview")}
              </p>
            </div>
            <button
              onClick={load}
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

        {error && (
          <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        )}

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] overflow-hidden shadow-sm">
          {loading ? (
            <div className="divide-y divide-[var(--border)]" aria-hidden>
              {[0, 1].map((row) => (
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
              <Home
                size={28}
                strokeWidth={1.5}
                className="text-[var(--muted-foreground)]/50"
              />
              <p className="mt-3 text-sm font-medium text-[var(--foreground)]">
                {t("No children linked yet")}
              </p>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                {t("Children linked to your account will appear here.")}
              </p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--muted-foreground)] uppercase tracking-wider">
                  <th className="px-5 py-3 font-medium">{t("Child")}</th>
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
                {sorted.map((child) => {
                  const tier = tierOf(child.avg_mastery_pct);
                  return (
                    <tr
                      key={child.username}
                      className="group hover:bg-[var(--background)]/50 transition-colors"
                    >
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-3">
                          <span
                            className={`h-2.5 w-2.5 shrink-0 rounded-full ${TIER_BAR[tier]}`}
                            aria-hidden
                          />
                          <span className="min-w-0 truncate font-medium text-[var(--foreground)]">
                            {child.username}
                          </span>
                        </div>
                      </td>
                      <td className="px-5 py-3 text-center text-[var(--muted-foreground)]">
                        {child.no_data ? (
                          <span className="inline-flex items-center rounded-full bg-[var(--muted)]/60 px-2 py-0.5 text-xs text-[var(--muted-foreground)]">
                            {t("No learning data yet")}
                          </span>
                        ) : (
                          child.kp_total
                        )}
                      </td>
                      <td className="px-5 py-3">
                        {child.no_data ? (
                          <span className="text-xs text-[var(--muted-foreground)]">—</span>
                        ) : (
                          <div className="flex items-center gap-2">
                            <div className="h-2 w-28 overflow-hidden rounded-full bg-[var(--muted)]/50">
                              <div
                                className={`h-full rounded-full ${TIER_BAR[tier]}`}
                                style={{
                                  width: `${Math.min(100, child.avg_mastery_pct)}%`,
                                }}
                              />
                            </div>
                            <span
                              className={`w-10 shrink-0 text-xs font-medium tabular-nums ${TIER_TEXT[tier]}`}
                            >
                              {child.avg_mastery_pct}%
                            </span>
                          </div>
                        )}
                      </td>
                      <td className="px-5 py-3">
                        {child.no_data || child.weak.length === 0 ? (
                          <span className="text-xs text-[var(--muted-foreground)]">
                            {child.no_data
                              ? t("No learning data yet")
                              : t("No weak knowledge points")}
                          </span>
                        ) : (
                          <div className="flex max-w-xs flex-wrap gap-1">
                            {child.weak.slice(0, 5).map((kp) => (
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
                            {child.weak.length > 5 && (
                              <span className="text-xs text-[var(--muted-foreground)]">
                                +{child.weak.length - 5}
                              </span>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="px-5 py-3 text-[var(--muted-foreground)]">
                        {formatActive(child.last_active, lang)}
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
            <Users size={13} />
            {t("Generated at {{time}}", {
              time: formatActive(overview.generated_at, lang),
            })}
          </p>
        )}
      </div>
    </div>
  );
}
