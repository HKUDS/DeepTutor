"use client";

import { useState } from "react";
import {
  AlertCircle,
  Brain,
  BookOpen,
  Check,
  ChevronDown,
  FileText,
  Compass,
  Database,
  FlaskConical,
  ListChecks,
  Loader2,
  MessagesSquare,
  Mountain,
  Notebook,
  Orbit,
  PenLine,
  Ruler,
  Sprout,
  Telescope,
  Users,
} from "lucide-react";

import type {
  SourceChildren,
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
  goal,
  emoji,
  onGoal,
  onEmoji,
}: {
  goal: string;
  emoji: string;
  onGoal: (value: string) => void;
  onEmoji: (value: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="mx-auto max-w-xl">
      <h3 className="text-lg font-semibold text-[var(--foreground)]">
        {t("What do you want to master?")}
      </h3>
      <p className="mt-1 text-sm leading-6 text-[var(--muted-foreground)]">
        {t(
          "Say what you want to be able to do. The tutor reads your materials and designs the outline with you in the first session — you can change it there.",
        )}
      </p>
      <label className="mt-6 block text-xs font-medium text-[var(--foreground)]">
        {t("Learning goal")}
        <textarea
          autoFocus
          data-modal-initial-focus
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
          {t("Goal emblem")}
        </legend>
        <div className="mt-2 flex flex-wrap gap-2">
          {EMBLEMS.map(({ value, Icon }) => (
            <button
              key={value}
              type="button"
              onClick={() => onEmoji(value)}
              aria-pressed={emoji === value}
              aria-label={t("Choose goal emblem {{emblem}}", { emblem: value })}
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
  childLists,
  onExpand,
}: {
  library: SourceLibrary;
  loading: boolean;
  selected: Set<string>;
  onToggle: (key: string) => void;
  /** Child lists per opened row, fetched on demand. */
  childLists: Record<string, SourceChildren>;
  onExpand: (candidate: SourceCandidate) => void;
}) {
  const { t } = useTranslation();
  // Which libraries are open. Local to this step: it is view state, and the
  // documents themselves are cached in the hook that fetched them.
  const [opened, setOpened] = useState<Set<string>>(new Set());
  const toggleOpen = (candidate: SourceCandidate) => {
    setOpened((previous) => {
      const next = new Set(previous);
      if (next.has(candidate.key)) next.delete(candidate.key);
      else {
        next.add(candidate.key);
        onExpand(candidate);
      }
      return next;
    });
  };
  return (
    <div>
      <h3 className="text-lg font-semibold text-[var(--foreground)]">
        {t("Which materials should it draw on?")}
      </h3>
      <p className="mt-1 text-sm leading-6 text-[var(--muted-foreground)]">
        {t(
          "Mix as many sources as useful — your library, and the work you have already done here. Your goal is always included; the rest grounds the outline in your own material.",
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
            hint={t(
              "Take a whole library, or open one and pick just the lessons you mean.",
            )}
            childLists={childLists}
            opened={opened}
            onToggleOpen={toggleOpen}
          />
          <SourceSection
            icon={MessagesSquare}
            title={t("Conversations")}
            empty={t("No conversations yet")}
            items={library.chats}
            selected={selected}
            onToggle={onToggle}
            hint={t(
              "A conversation you have already had shows the tutor where you actually stand.",
            )}
          />
          <SourceSection
            icon={ListChecks}
            title={t("Question bank")}
            empty={t("No question sets yet")}
            items={library.questionSets}
            selected={selected}
            onToggle={onToggle}
            hint={t(
              "Open a set and pick the questions you want the outline built around.",
            )}
            childLists={childLists}
            opened={opened}
            onToggleOpen={toggleOpen}
          />
          <SourceSection
            icon={PenLine}
            title={t("Co-Writer drafts")}
            empty={t("No drafts yet")}
            items={library.drafts}
            selected={selected}
            onToggle={onToggle}
          />
          <SourceSection
            icon={Users}
            title={t("Partners and groups")}
            empty={t("No partner conversations yet")}
            items={library.partners}
            selected={selected}
            onToggle={onToggle}
            hint={t("Open one and pick the conversations you mean.")}
            childLists={childLists}
            opened={opened}
            onToggleOpen={toggleOpen}
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

/**
 * One selectable source: a checkbox, a name, and a line of detail.
 *
 * ``bare`` drops the row's own frame for a row that sits *inside* one — a
 * library heading a document list already has a border around the whole
 * group, and drawing a second one around the heading reads as a card inside
 * a card. The border width is kept and made transparent so selecting a row
 * cannot shift the layout by a pixel.
 */
function SourceRow({
  item,
  active,
  onToggle,
  disabled = false,
  note = "",
  bare = false,
}: {
  item: SourceCandidate;
  active: boolean;
  onToggle: () => void;
  disabled?: boolean;
  note?: string;
  bare?: boolean;
}) {
  const { t } = useTranslation();
  // A container holds no text of its own — a question-bank category, a study
  // partner. Showing it a checkbox would promise a selection the server has no
  // way to honour, so it renders as a plain heading and only opens.
  const selectable = item.selectable !== false;
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={selectable ? active : undefined}
      disabled={disabled || !item.available}
      className={`flex min-h-16 w-full items-center gap-3 border p-3 text-left transition disabled:cursor-not-allowed disabled:opacity-55 ${
        bare ? "border-transparent" : "rounded-xl"
      } ${
        active
          ? `bg-[color-mix(in_srgb,var(--primary)_6%,transparent)] ${bare ? "" : "border-[var(--primary)]"}`
          : `hover:bg-[color-mix(in_srgb,var(--accent)_60%,transparent)] ${bare ? "" : "border-[var(--border)]"}`
      }`}
    >
      {selectable && (
        <span
          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border ${
            active
              ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
              : "border-[var(--input)]"
          }`}
        >
          {active && <Check className="h-3 w-3" />}
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-[var(--foreground)]">
          {item.label}
        </span>
        <span className="mt-0.5 block truncate text-xs text-[var(--muted-foreground)]">
          {note || (item.available ? item.detail : t("Currently unavailable"))}
        </span>
      </span>
    </button>
  );
}

/**
 * What sits inside one opened row: a library's documents, a category's
 * questions, a partner's conversations.
 *
 * Taking the whole container answers "what does this say about my goal?".
 * Picking one child answers "build this around chapter 3" — a different
 * question, and the only one that can be asked by naming the thing itself.
 */
function ChildSourceList({
  parent,
  state,
  selected,
  onToggle,
  parentSelected,
}: {
  parent: SourceCandidate;
  state: SourceChildren | undefined;
  selected: Set<string>;
  onToggle: (key: string) => void;
  parentSelected: boolean;
}) {
  const { t } = useTranslation();
  if (!state || state.loading) {
    return (
      <div className="flex items-center gap-2 px-3 py-3 text-xs text-[var(--muted-foreground)]">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {t("Loading…")}
      </div>
    );
  }
  if (state.error) {
    return (
      <div className="flex items-start gap-2 px-3 py-3 text-xs text-[var(--muted-foreground)]">
        <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        {state.error}
      </div>
    );
  }
  if (state.candidates.length === 0) {
    return (
      <div className="px-3 py-3 text-xs text-[var(--muted-foreground)]">
        {/* A connected external resource keeps its files where they live; the
            whole library is still selectable, one of its documents is not. */}
        {t("Nothing here to pick from.")}
      </div>
    );
  }
  return (
    <div className="max-h-56 space-y-1 overflow-y-auto px-2 pb-2">
      {state.candidates.map((child) => (
        <SourceRow
          key={child.key}
          item={child}
          active={selected.has(child.key)}
          onToggle={() => onToggle(child.key)}
          disabled={parentSelected}
          note={
            parentSelected
              ? t("Already covered by the whole library")
              : `${parent.label} · ${child.path || child.detail}`
          }
        />
      ))}
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
  hint = "",
  childLists,
  opened,
  onToggleOpen,
}: {
  icon: typeof BookOpen;
  title: string;
  empty: string;
  items: SourceCandidate[];
  selected: Set<string>;
  onToggle: (key: string) => void;
  hint?: string;
  /** Present for sections whose rows can be opened up. */
  childLists?: Record<string, SourceChildren>;
  opened?: Set<string>;
  onToggleOpen?: (candidate: SourceCandidate) => void;
}) {
  const { t } = useTranslation();
  const expandable = Boolean(childLists && opened && onToggleOpen);
  return (
    <section>
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.13em] text-[var(--muted-foreground)]">
        <Icon className="h-3.5 w-3.5" /> {title}
      </div>
      {hint && items.length > 0 && (
        <p className="mb-2 text-xs leading-5 text-[var(--muted-foreground)]">
          {hint}
        </p>
      )}
      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--border)] px-3 py-4 text-xs text-[var(--muted-foreground)]">
          {empty}
        </div>
      ) : expandable ? (
        // One column: a document list belongs directly under the library it
        // came from, and a file's path is too long for a half-width card.
        <div className="grid gap-2">
          {items.map((item) => {
            const isOpen = Boolean(opened?.has(item.key));
            const state = childLists?.[item.key];
            const picked = state
              ? state.candidates.filter((file) => selected.has(file.key)).length
              : 0;
            return (
              <div
                key={item.key}
                className={`overflow-hidden rounded-xl border transition-colors ${
                  selected.has(item.key)
                    ? "border-[var(--primary)]"
                    : "border-[var(--border)]"
                }`}
              >
                <div className="flex items-stretch">
                  <div className="min-w-0 flex-1">
                    <SourceRow
                      item={item}
                      active={selected.has(item.key)}
                      onToggle={() =>
                        item.selectable === false
                          ? onToggleOpen?.(item)
                          : onToggle(item.key)
                      }
                      bare
                      note={
                        picked > 0 ? `${picked} ${t("selected inside")}` : ""
                      }
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => onToggleOpen?.(item)}
                    aria-expanded={isOpen}
                    disabled={!item.available}
                    className="flex w-11 shrink-0 items-center justify-center border-l border-[var(--border)] text-[var(--muted-foreground)] transition hover:bg-[color-mix(in_srgb,var(--accent)_60%,transparent)] hover:text-[var(--foreground)] disabled:opacity-40"
                    aria-label={t("Show what is inside")}
                  >
                    <span className="flex flex-col items-center gap-0.5">
                      <FileText className="h-3.5 w-3.5" />
                      <ChevronDown
                        className={`h-3 w-3 transition-transform ${
                          isOpen ? "rotate-180" : ""
                        }`}
                      />
                    </span>
                  </button>
                </div>
                {isOpen && (
                  <div className="border-t border-[var(--border)] bg-[color-mix(in_srgb,var(--muted)_75%,transparent)]">
                    <ChildSourceList
                      parent={item}
                      state={state}
                      selected={selected}
                      onToggle={onToggle}
                      parentSelected={selected.has(item.key)}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {items.map((item) => (
            <SourceRow
              key={item.key}
              item={item}
              active={selected.has(item.key)}
              onToggle={() => onToggle(item.key)}
            />
          ))}
        </div>
      )}
    </section>
  );
}
