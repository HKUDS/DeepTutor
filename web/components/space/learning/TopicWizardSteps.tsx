"use client";

import {
  AlertCircle,
  Brain,
  BookOpen,
  Check,
  Compass,
  Database,
  FlaskConical,
  Loader2,
  Mountain,
  Notebook,
  Orbit,
  Ruler,
  Sprout,
  Telescope,
} from "lucide-react";

import type {
  SourceCandidate,
  SourceLibrary,
} from "@/hooks/useTopicSourceLibrary";

import type { Translate } from "./format";
import { useTranslation } from "react-i18next";

/**
 * The stored value is still the emoji each icon replaces — only how it's
 * *offered* changes. A raw system emoji renders at whatever the OS font
 * decides and reads as clip art (see ProgressRing's own note on why the
 * topic card dropped this); a line icon in the app's own visual language
 * reads as considered instead of decorative, and stays identical across
 * platforms and themes.
 */
const EMBLEMS: { value: string; Icon: typeof Compass }[] = [
  { value: "🧭", Icon: Compass },
  { value: "🏔️", Icon: Mountain },
  { value: "🌿", Icon: Sprout },
  { value: "🔭", Icon: Telescope },
  { value: "🧪", Icon: FlaskConical },
  { value: "🧠", Icon: Brain },
  { value: "📐", Icon: Ruler },
  { value: "🌌", Icon: Orbit },
];

export function GoalStep({
  name,
  goal,
  emoji,
  onName,
  onGoal,
  onEmoji,
}: {
  name: string;
  goal: string;
  emoji: string;
  onName: (value: string) => void;
  onGoal: (value: string) => void;
  onEmoji: (value: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="mx-auto max-w-xl">
      <h3 className="text-lg font-semibold text-[var(--foreground)]">
        {t("What do you want to learn?")}
      </h3>
      <p className="mt-1 text-sm leading-6 text-[var(--muted-foreground)]">
        {t(
          "The more specific the goal, the closer each knowledge point lands to the ability you actually want.",
        )}
      </p>
      <label className="mt-6 block text-xs font-medium text-[var(--foreground)]">
        {t("Topic name")}
        <input
          autoFocus
          data-modal-initial-focus
          value={name}
          onChange={(event) => onName(event.target.value)}
          maxLength={120}
          placeholder={t("e.g. Linear algebra")}
          className="mt-2 h-9 w-full rounded-lg border border-[var(--input)] bg-[var(--background)] px-3.5 text-sm outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/15"
        />
      </label>
      <label className="mt-5 block text-xs font-medium text-[var(--foreground)]">
        {t("Learning goal")}
        <textarea
          value={goal}
          onChange={(event) => onGoal(event.target.value)}
          maxLength={2000}
          rows={5}
          placeholder={t(
            "I want to build geometric intuition for vector spaces and transformations, then solve eigenvalue problems independently.",
          )}
          className="mt-2 w-full resize-none rounded-lg border border-[var(--input)] bg-[var(--background)] px-3.5 py-3 text-sm leading-6 outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/15"
        />
      </label>
      <fieldset className="mt-5">
        <legend className="text-xs font-medium text-[var(--foreground)]">
          {t("Map emblem")}
        </legend>
        <div className="mt-2 flex flex-wrap gap-2">
          {EMBLEMS.map(({ value, Icon }) => (
            <button
              key={value}
              type="button"
              onClick={() => onEmoji(value)}
              aria-pressed={emoji === value}
              aria-label={t("Choose map emblem {{emblem}}", { emblem: value })}
              className={`flex h-10 w-10 items-center justify-center rounded-xl border transition ${
                emoji === value
                  ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]"
                  : "border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
              }`}
            >
              <Icon size={18} strokeWidth={1.75} aria-hidden="true" />
            </button>
          ))}
        </div>
      </fieldset>
    </div>
  );
}

export function SourcesStep({
  library,
  loading,
  selected,
  onToggle,
}: {
  library: SourceLibrary;
  loading: boolean;
  selected: Set<string>;
  onToggle: (key: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <h3 className="text-lg font-semibold text-[var(--foreground)]">
        {t("Which materials should it draw on?")}
      </h3>
      <p className="mt-1 text-sm leading-6 text-[var(--muted-foreground)]">
        {t(
          "Mix as many sources as useful. Your goal is always included; the rest grounds the outline in your own material.",
        )}
      </p>
      {loading ? (
        <div className="flex items-center justify-center py-20 text-[var(--muted-foreground)]">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : (
        <div className="mt-6 space-y-6">
          <SourceSection
            icon={BookOpen}
            title={t("Books")}
            empty={t("No books are available yet")}
            items={library.books}
            selected={selected}
            onToggle={onToggle}
          />
          <SourceSection
            icon={Notebook}
            title={t("Notebooks")}
            empty={t("No saved notebooks yet")}
            items={library.notebooks}
            selected={selected}
            onToggle={onToggle}
          />
          <SourceSection
            icon={Database}
            title={t("Knowledge bases")}
            empty={t("No retrievable knowledge bases yet")}
            items={library.knowledgeBases}
            selected={selected}
            onToggle={onToggle}
          />
          {library.failures.length > 0 && (
            <p className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
              <AlertCircle className="h-3.5 w-3.5" />
              {t(
                "{{sources}} could not be loaded; you can still generate from the available sources.",
                { sources: library.failures.join(t("source list separator")) },
              )}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function SourceSection({
  icon: Icon,
  title,
  empty,
  items,
  selected,
  onToggle,
}: {
  icon: typeof BookOpen;
  title: string;
  empty: string;
  items: SourceCandidate[];
  selected: Set<string>;
  onToggle: (key: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <section>
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.13em] text-[var(--muted-foreground)]">
        <Icon className="h-3.5 w-3.5" /> {title}
      </div>
      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--border)] px-3 py-4 text-xs text-[var(--muted-foreground)]">
          {empty}
        </div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {items.map((item) => {
            const active = selected.has(item.key);
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => onToggle(item.key)}
                aria-pressed={active}
                disabled={!item.available}
                className={`flex min-h-16 items-center gap-3 rounded-xl border p-3 text-left transition disabled:cursor-not-allowed disabled:opacity-55 ${
                  active
                    ? "border-[var(--primary)] bg-[var(--primary)]/[0.06]"
                    : "border-[var(--border)] hover:bg-[var(--accent)]/60"
                }`}
              >
                <span
                  className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border ${
                    active
                      ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "border-[var(--input)]"
                  }`}
                >
                  {active && <Check className="h-3 w-3" />}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-[var(--foreground)]">
                    {item.label}
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-[var(--muted-foreground)]">
                    {item.available ? item.detail : t("Currently unavailable")}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
