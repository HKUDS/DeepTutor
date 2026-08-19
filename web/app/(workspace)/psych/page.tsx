"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Activity, Loader2 } from "lucide-react";
import {
  fetchPsychDashboard,
  observeDebriefHref,
  psychSessionHref,
  type PsychDashboardSummary,
  type PsychSessionKind,
} from "@/lib/psych-dashboard";

const SESSION_LABELS: Record<PsychSessionKind, string> = {
  counsel: "Counsel",
  sim: "Sim",
  dual: "Dual",
  whisper: "Whisper",
  intake: "Intake",
};

function SessionList({
  kind,
  rows,
}: {
  kind: PsychSessionKind;
  rows: PsychDashboardSummary["sessions"][PsychSessionKind];
}) {
  if (rows.length === 0) {
    return (
      <p className="text-xs text-[var(--muted-foreground)]">
        No recent {SESSION_LABELS[kind].toLowerCase()} sessions yet.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {rows.map((row) => (
        <li
          key={row.id}
          className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-xs"
        >
          <div className="min-w-0">
            <code className="font-mono text-[11px] text-[var(--foreground)]">
              {row.id}
            </code>
            <div className="mt-0.5 text-[10px] text-[var(--muted-foreground)]">
              {row.closed ? "closed" : "open"}
              {row.safety ? ` · safety ${row.safety}` : ""}
              {row.scenario_id ? ` · ${row.scenario_id}` : ""}
              {typeof row.turns_done === "number"
                ? ` · ${row.turns_done} turn(s)`
                : typeof row.turns === "number"
                  ? ` · ${row.turns} line(s)`
                  : ""}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              href={psychSessionHref(kind, row.id)}
              className="rounded-lg border border-[var(--border)] px-2 py-1 font-medium text-[var(--foreground)] transition-colors hover:border-[var(--ring)]"
            >
              Open
            </Link>
            {kind === "counsel" && row.closed ? (
              <Link
                href={observeDebriefHref(row.id)}
                className="rounded-lg border border-violet-500/40 px-2 py-1 font-medium text-violet-700 transition-colors hover:border-violet-500 dark:text-violet-300"
              >
                Observe
              </Link>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function PsychPage() {
  const [data, setData] = useState<PsychDashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const summary = await fetchPsychDashboard();
        if (!cancelled) {
          setData(summary);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setData(null);
          setError(
            err instanceof Error ? err.message : "Failed to load psych dashboard.",
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-[var(--border)] px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
          <Activity className="h-4 w-4 text-[var(--primary)]" aria-hidden />
          Psych
        </div>
        <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
          Read-only trainee dashboard — emotion timeline, open plans, recent sessions
        </p>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto w-full max-w-3xl space-y-6">
          {data === null && !error && (
            <div className="inline-flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Loading dashboard…
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-700 dark:text-red-200"
            >
              {error}
              <p className="mt-2 opacity-80">
                Ensure psych-academy is registered (
                <span className="font-mono">psych-academy serve</span>).
              </p>
            </div>
          )}

          {data && (
            <>
              <section>
                <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                  Recent emotion
                </h2>
                {data.emotions.length === 0 ? (
                  <p className="text-xs text-[var(--muted-foreground)]">
                    No emotion events logged yet.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {data.emotions.map((event) => (
                      <li
                        key={`${event.ts}-${event.session_id}`}
                        className="rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-xs"
                      >
                        <div className="font-medium text-[var(--foreground)]">
                          {event.labels.join(", ") || "—"} · intensity {event.intensity}
                        </div>
                        <div className="mt-0.5 text-[10px] text-[var(--muted-foreground)]">
                          {event.surface} · {event.session_id} · {event.trigger}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section>
                <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                  Open action plans
                </h2>
                {data.open_plans.length === 0 ? (
                  <p className="text-xs text-[var(--muted-foreground)]">
                    No open plans — nice work.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {data.open_plans.map((plan) => (
                      <li
                        key={plan.id}
                        className="rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-xs"
                      >
                        <div className="font-medium text-[var(--foreground)]">
                          {plan.type || "plan"}{" "}
                          <span className="font-mono text-[10px] opacity-70">
                            {plan.id}
                          </span>
                        </div>
                        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[var(--muted-foreground)]">
                          {plan.steps
                            .filter((step) => !step.done)
                            .map((step, index) => (
                              <li key={`${plan.id}-${index}`}>{step.text}</li>
                            ))}
                        </ul>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {(Object.keys(SESSION_LABELS) as PsychSessionKind[]).map((kind) => (
                <section key={kind}>
                  <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                    Recent {SESSION_LABELS[kind]}
                  </h2>
                  <SessionList kind={kind} rows={data.sessions[kind]} />
                </section>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
