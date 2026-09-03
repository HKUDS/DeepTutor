"use client";

import { useState, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Check,
  Loader2,
  Sparkles,
  X,
} from "lucide-react";

import { useModalDialog } from "@/hooks/useModalDialog";
import {
  hydrateTopicSource,
  toggleSourceSelection,
  useTopicSourceLibrary,
} from "@/hooks/useTopicSourceLibrary";
import {
  createMasteryTopic,
  generateMasteryTopicDraft,
  type CreateTopicInput,
  type MasteryTopic,
  type TopicDraft,
  type TopicSourceInput,
} from "@/lib/learning-api";

import type { Translate } from "./format";
import { CoverageNotice } from "./CoverageNotice";
import { RouteDraftEditor } from "./RouteDraftEditor";
import { isRouteDraftValid } from "./route-draft";
import { GoalStep, SourcesStep } from "./TopicWizardSteps";

export function CreateTopicWizard({
  onClose,
  onCreated,
  returnFocusRef,
}: {
  onClose: () => void;
  onCreated: (topic: MasteryTopic) => void;
  returnFocusRef: RefObject<HTMLElement | null>;
}) {
  const { t } = useTranslation();
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [emoji, setEmoji] = useState("🧭");
  const {
    library,
    loading: libraryLoading,
    candidates,
    files,
    loadKnowledgeBaseFiles,
  } = useTopicSourceLibrary(t);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [draft, setDraft] = useState<TopicDraft | null>(null);
  const [sources, setSources] = useState<TopicSourceInput[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useModalDialog(onClose, busy, returnFocusRef);

  const toggleSource = (key: string) => {
    setSelected((previous) => toggleSourceSelection(previous, key, candidates));
  };

  const generate = async (mustCover: string[] = []) => {
    setBusy(true);
    setError(null);
    try {
      const chosen = candidates.filter((candidate) =>
        selected.has(candidate.key),
      );
      const hydrated = await Promise.all(chosen.map(hydrateTopicSource));
      const nextSources: TopicSourceInput[] = [
        {
          kind: "goal",
          label: t("Learning goal"),
          excerpt: goal.trim(),
        },
        ...hydrated,
      ];
      const nextDraft = await generateMasteryTopicDraft({
        name: name.trim(),
        goal: goal.trim(),
        sources: nextSources,
        ...(mustCover.length ? { must_cover: mustCover } : {}),
      });
      setSources(nextDraft.sources ?? nextSources);
      setDraft(nextDraft);
      setStep(3);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t("Could not generate the outline. Please retry."),
      );
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!draft || !isRouteDraftValid(draft)) return;
    setBusy(true);
    setError(null);
    try {
      const payload: CreateTopicInput = {
        name: name.trim(),
        goal: goal.trim(),
        description: draft.description.trim(),
        emoji,
        sources,
        modules: draft.modules,
      };
      onCreated(await createMasteryTopic(payload));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t("Creation failed. Please retry."),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-[var(--overlay)] p-0 backdrop-blur-[2px] sm:items-center sm:p-6"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-topic-title"
        tabIndex={-1}
        className="flex max-h-[94dvh] w-full max-w-3xl flex-col overflow-hidden rounded-t-[26px] border border-[var(--border)] bg-[var(--card)] shadow-2xl outline-none sm:max-h-[88dvh] sm:rounded-xl"
      >
        <header className="flex items-start justify-between border-b border-[var(--border)] px-5 py-4 sm:px-7 sm:py-5">
          <div>
            <div className="flex items-center gap-2 text-xs font-medium text-[var(--primary)]">
              <Sparkles className="h-3.5 w-3.5" />
              {t("New topic")}
            </div>
            <h2
              id="create-topic-title"
              className="mt-1 text-xl font-semibold tracking-tight text-[var(--foreground)]"
            >
              {t("Plan the modules")}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label={t("Close")}
            className="rounded-lg p-2 text-[var(--muted-foreground)] hover:bg-[var(--accent)] disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="border-b border-[var(--border)] px-5 py-3 sm:px-7">
          <ol
            className="grid grid-cols-3 gap-2"
            aria-label={t("Creation steps")}
          >
            {[t("Goal"), t("Materials"), t("Outline")].map((label, index) => {
              const number = index + 1;
              const active = number === step;
              const done = number < step;
              return (
                <li key={label} className="flex items-center gap-2">
                  <span
                    className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold ${
                      active
                        ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                        : done
                          ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                          : "bg-[var(--muted)] text-[var(--muted-foreground)]"
                    }`}
                  >
                    {done ? <Check className="h-3 w-3" /> : number}
                  </span>
                  <span
                    className={`hidden text-xs sm:inline ${
                      active
                        ? "font-medium text-[var(--foreground)]"
                        : "text-[var(--muted-foreground)]"
                    }`}
                  >
                    {label}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-6 sm:px-7">
          {step === 1 && (
            <GoalStep
              name={name}
              goal={goal}
              emoji={emoji}
              onName={setName}
              onGoal={setGoal}
              onEmoji={setEmoji}
            />
          )}
          {step === 2 && (
            <SourcesStep
              library={library}
              loading={libraryLoading}
              selected={selected}
              onToggle={toggleSource}
              files={files}
              onExpand={loadKnowledgeBaseFiles}
            />
          )}
          {step === 3 && draft && (
            <>
              <CoverageNotice
                coverage={draft.coverage}
                busy={busy}
                onCover={(documents) => void generate(documents)}
              />
              <RouteDraftEditor
                draft={draft}
                onChange={setDraft}
                moduleLimit={draft.module_limit}
              />
            </>
          )}
          {error && (
            <div className="mt-5 flex items-start gap-2 rounded-xl border border-red-500/20 bg-red-500/[0.06] p-3 text-xs leading-5 text-red-700 dark:text-red-300">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {error}
            </div>
          )}
        </div>

        <footer className="flex items-center justify-between border-t border-[var(--border)] px-5 py-4 sm:px-7">
          <button
            type="button"
            onClick={() => setStep((current) => Math.max(1, current - 1))}
            disabled={step === 1 || busy}
            className="inline-flex h-10 items-center gap-2 rounded-xl px-3 text-sm text-[var(--muted-foreground)] hover:bg-[var(--accent)] disabled:invisible"
          >
            <ArrowLeft className="h-4 w-4" />
            {t("Back")}
          </button>
          {step === 1 ? (
            <button
              type="button"
              onClick={() => setStep(2)}
              disabled={!name.trim() || !goal.trim()}
              className="inline-flex h-10 items-center gap-2 rounded-xl bg-[var(--primary)] px-4 text-sm font-medium text-[var(--primary-foreground)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {t("Choose sources")}
              <ArrowRight className="h-4 w-4" />
            </button>
          ) : step === 2 ? (
            <button
              type="button"
              onClick={() => void generate()}
              disabled={busy}
              className="inline-flex h-10 items-center gap-2 rounded-xl bg-[var(--primary)] px-4 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-50"
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              {busy ? t("Charting…") : t("Generate outline")}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void confirm()}
              disabled={busy || !draft || !isRouteDraftValid(draft)}
              className="inline-flex h-10 items-center gap-2 rounded-xl bg-[var(--primary)] px-4 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-50"
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Check className="h-4 w-4" />
              )}
              {busy ? t("Saving map…") : t("Start learning")}
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
