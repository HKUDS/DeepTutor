"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Dumbbell, Loader2 } from "lucide-react";
import { listSkills, type SkillInfo } from "@/lib/skills-api";
import { newPsychSkillTrainUrl } from "@/lib/chat-launch-intent";

function isPsychSkill(skill: SkillInfo): boolean {
  return skill.tags.some((tag) => tag === "psych");
}

export default function TrainPage() {
  const router = useRouter();
  const [skills, setSkills] = useState<SkillInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const all = await listSkills({ force: true });
        if (!cancelled) {
          setSkills(all);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setSkills([]);
          setError(err instanceof Error ? err.message : "Failed to load skills.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const psychSkills = useMemo(
    () => (skills || []).filter(isPsychSkill).sort((a, b) => a.name.localeCompare(b.name)),
    [skills],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-[var(--border)] px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
          <Dumbbell className="h-4 w-4 text-[var(--primary)]" aria-hidden />
          Train
        </div>
        <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
          Start Guided Learning from a psych counseling skill
        </p>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto w-full max-w-3xl space-y-3">
          {skills === null && (
            <div className="inline-flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Loading skills…
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-700 dark:text-red-200"
            >
              {error}
            </div>
          )}

          {skills !== null && !error && psychSkills.length === 0 && (
            <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--background)]/50 p-4 text-xs leading-6 text-[var(--muted-foreground)]">
              <p className="mb-2 font-medium text-[var(--foreground)]">
                No psych skills installed yet
              </p>
              <ol className="list-decimal space-y-1.5 pl-4">
                <li>
                  Run{" "}
                  <span className="font-mono">psych-academy install-skills</span>{" "}
                  (or distill a skill on{" "}
                  <Link href="/distill" className="underline">
                    /distill
                  </Link>
                  ).
                </li>
                <li>Return here and Start Guided Learning for a skill.</li>
              </ol>
            </div>
          )}

          {psychSkills.map((skill) => (
            <div
              key={skill.name}
              className="rounded-2xl border border-[var(--border)] bg-[var(--card)] px-4 py-3"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-mono text-sm text-[var(--foreground)]">
                    {skill.name}
                  </div>
                  <p className="mt-1 text-xs leading-5 text-[var(--muted-foreground)]">
                    {skill.description || "No description"}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => router.push(newPsychSkillTrainUrl(skill.name))}
                  className="shrink-0 rounded-xl bg-[var(--primary)] px-3 py-1.5 text-xs font-medium text-[var(--primary-foreground)]"
                >
                  Start
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
