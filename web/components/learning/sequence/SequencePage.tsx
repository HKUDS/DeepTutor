"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import InlineMarkdown from "@/components/common/InlineMarkdown";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { LearningShell } from "@/components/learning/LearningShell";
import { listKnowledgeBases, type KnowledgeBaseSummary } from "@/features/knowledge/api/client";
import { knowledgeBaseRef } from "@/lib/knowledge-helpers";
import {
  createSequenceProblem,
  explainSequenceStep,
  placeSequenceStep,
  removeSequenceStep,
  requestSequenceHint,
  type SequenceProblem,
  type SequenceStep,
} from "@/lib/sequence-api";

type StepStyle = "word" | "symbol";

function stepText(step: SequenceStep, style: StepStyle): string {
  if (style === "symbol") return step.math;
  return `${step.explanation} ${step.math}`;
}

export function SequencePage() {
  const { t } = useTranslation();
  const [bases, setBases] = useState<KnowledgeBaseSummary[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [knowledgeBase, setKnowledgeBase] = useState("");
  const [topic, setTopic] = useState("");
  const [problem, setProblem] = useState<SequenceProblem | null>(null);
  const [writing, setWriting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [style, setStyle] = useState<StepStyle>("word");
  const [combo, setCombo] = useState(0);
  const [dialog, setDialog] = useState<{ title: string; body: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    listKnowledgeBases()
      .then(rows => {
        if (cancelled) return;
        setBases(rows);
        if (rows.length === 1) setKnowledgeBase(knowledgeBaseRef(rows[0]));
      })
      .catch(() => {
        if (!cancelled) setLoadError(t("Could not load knowledge bases."));
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const byId = useMemo(() => {
    const map = new Map<string, SequenceStep>();
    problem?.steps.forEach(step => map.set(step.id, step));
    return map;
  }, [problem]);

  async function writeProblem() {
    if (!knowledgeBase) {
      setMessage(t("Select a knowledge base first."));
      return;
    }
    if (!topic.trim()) {
      setMessage(t("Enter a topic first."));
      return;
    }
    setWriting(true);
    setMessage("");
    setProblem(null);
    setCombo(0);
    try {
      setProblem(await createSequenceProblem(knowledgeBase, topic.trim()));
    } catch (error) {
      setMessage(
        error instanceof Error && error.message
          ? error.message
          : t("Could not write a problem from that material. Try a more specific topic."),
      );
    } finally {
      setWriting(false);
    }
  }

  async function addStep(stepId: string) {
    if (!problem || problem.solved || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await placeSequenceStep(problem.problem_id, stepId, problem.placed_ids.length);
      setProblem(result.problem);
      if (result.accepted) setCombo(value => value + 1);
      else {
        setCombo(0);
        setMessage(t("That step does not belong there."));
      }
    } catch {
      setMessage(t("Could not check that step."));
    } finally {
      setBusy(false);
    }
  }

  async function removePlaced(stepId: string) {
    if (!problem || problem.solved || busy) return;
    setBusy(true);
    setCombo(0);
    try {
      setProblem(await removeSequenceStep(problem.problem_id, stepId));
    } catch {
      setMessage(t("Could not check that step."));
    } finally {
      setBusy(false);
    }
  }

  async function showHint() {
    if (!problem || busy) return;
    setDialog({ title: t("Hint"), body: "" });
    try {
      const result = await requestSequenceHint(problem.problem_id);
      setDialog({ title: t("Hint"), body: result.hint });
    } catch {
      setDialog({ title: t("Hint"), body: t("Could not get a hint.") });
    }
  }

  async function showWhy(stepId: string) {
    if (!problem) return;
    setDialog({ title: t("Why this step"), body: "" });
    try {
      const result = await explainSequenceStep(problem.problem_id, stepId);
      setDialog({ title: t("Why this step"), body: result.explanation });
    } catch {
      setDialog({ title: t("Why this step"), body: t("Could not explain this step.") });
    }
  }

  const bank = problem?.steps.filter(step => !problem.placed_ids.includes(step.id)) ?? [];
  const placed = problem?.placed_ids.map(id => byId.get(id)).filter((step): step is SequenceStep => !!step) ?? [];

  return (
    <LearningShell
      title={t("Solution sequence")}
      subtitle={t("Choose a knowledge base and a topic. The steps you see are written from that material.")}
    >
      <form
        className="mb-6 grid gap-4 rounded-xl border border-[var(--border)] p-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto] md:items-end"
        onSubmit={event => {
          event.preventDefault();
          void writeProblem();
        }}
      >
        <label className="grid gap-1 text-sm">
          <span>{t("Knowledge base")}</span>
          <select
            className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
            value={knowledgeBase}
            onChange={event => setKnowledgeBase(event.target.value)}
            disabled={!bases}
          >
            <option value="">{bases ? t("Knowledge base") : t("Loading knowledge bases…")}</option>
            {(bases ?? []).map(base => (
              <option key={knowledgeBaseRef(base)} value={knowledgeBaseRef(base)}>
                {base.name}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm">
          <span>{t("Topic")}</span>
          <input
            className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
            value={topic}
            onChange={event => setTopic(event.target.value)}
            placeholder={t("Chain rule for a product, or the section you just read")}
            maxLength={200}
          />
        </label>
        <button
          type="submit"
          className="rounded-lg bg-[var(--primary)] px-4 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-60"
          disabled={writing}
        >
          {writing ? t("Reading your knowledge base and writing a problem…") : t("New problem")}
        </button>
      </form>

      {loadError && <p className="mb-4 text-sm text-red-600">{loadError}</p>}
      {bases && bases.length === 0 && (
        <p className="mb-4 text-sm text-[var(--muted-foreground)]">
          {t("No knowledge base is ready. Add one in Knowledge, then come back.")}
        </p>
      )}
      {message && (
        <p role="status" className="mb-4 text-sm">
          {message}
        </p>
      )}

      {problem && (
        <div className="space-y-5">
          <section className="rounded-xl border border-[var(--border)] p-5">
            <MarkdownRenderer content={problem.question} enableMath />
            {problem.formulas.length > 0 && (
              <div className="mt-4 border-t border-[var(--border)] pt-3">
                <h2 className="mb-2 text-sm font-semibold">{t("Key formulas")}</h2>
                <ul className="space-y-1">
                  {problem.formulas.map(formula => (
                    <li key={formula}>
                      <InlineMarkdown content={formula} />
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {problem.sources.length > 0 && (
              <p className="mt-3 text-xs text-[var(--muted-foreground)]">
                {t("Sources")}: {problem.sources.map(source => source.title).join(", ")}
              </p>
            )}
            <p className="mt-3 text-sm">
              {t("Solved {{count}} of {{goal}} for this topic", {
                count: problem.progress.solved,
                goal: problem.progress.goal,
              })}
            </p>
          </section>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className={`text-sm font-semibold ${combo > 1 ? "opacity-100" : "opacity-0"}`} aria-hidden={combo < 2}>
              {t("Combo ×{{count}}", { count: combo })}
            </p>
            <div className="flex gap-1 rounded-lg border border-[var(--border)] p-1">
              <button type="button" className={styleButton(style === "word")} onClick={() => setStyle("word")}>
                {t("Word and symbol")}
              </button>
              <button type="button" className={styleButton(style === "symbol")} onClick={() => setStyle("symbol")}>
                {t("Symbol only")}
              </button>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <section className="rounded-xl border border-[var(--border)] p-4">
              <h2 className="mb-3 text-center text-sm font-semibold">{t("Your solution")}</h2>
              {placed.length === 0 && (
                <p className="py-8 text-center text-sm text-[var(--muted-foreground)]">
                  {t("Click a step to add it. A step that does not belong is sent back.")}
                </p>
              )}
              <ol className="space-y-2">
                {placed.map(step => (
                  <li key={step.id} className="flex items-start gap-2 rounded-lg border border-[var(--border)] p-3">
                    <div className="min-w-0 flex-1">
                      <InlineMarkdown content={stepText(step, style)} />
                    </div>
                    {problem.solved && (
                      <button
                        type="button"
                        className="text-xs underline"
                        onClick={() => void showWhy(step.id)}
                        disabled={busy}
                      >
                        {t("Why this step")}
                      </button>
                    )}
                    {!problem.solved && (
                      <button
                        type="button"
                        className="text-xs underline"
                        onClick={() => void removePlaced(step.id)}
                        disabled={busy}
                      >
                        {t("Remove this step")}
                      </button>
                    )}
                  </li>
                ))}
              </ol>
            </section>
            <section className="rounded-xl border border-[var(--border)] p-4">
              <h2 className="mb-3 text-center text-sm font-semibold">{t("Available steps")}</h2>
              <ul className="space-y-2">
                {bank.map(step => (
                  <li key={step.id}>
                    <button
                      type="button"
                      className="w-full rounded-lg border border-[var(--border)] p-3 text-left hover:bg-[var(--muted)] disabled:opacity-60"
                      onClick={() => void addStep(step.id)}
                      disabled={busy || problem.solved}
                    >
                      <InlineMarkdown content={stepText(step, style)} />
                      <span className="sr-only">{t("Add this step to your solution")}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <div className="flex flex-wrap justify-center gap-3">
            {!problem.solved && (
              <button
                type="button"
                className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm"
                onClick={() => void showHint()}
                disabled={busy}
              >
                {t("Get a hint")}
              </button>
            )}
            {problem.solved && (
              <button
                type="button"
                className="rounded-lg bg-[var(--primary)] px-4 py-2 text-sm text-[var(--primary-foreground)]"
                onClick={() => void writeProblem()}
                disabled={writing}
              >
                {t("Next problem")}
              </button>
            )}
          </div>

          {problem.solved && problem.explanation && (
            <section className="rounded-xl border border-[var(--border)] p-5">
              <h2 className="mb-2 text-base font-semibold">{t("Full explanation")}</h2>
              <MarkdownRenderer content={problem.explanation} enableMath />
            </section>
          )}
        </div>
      )}

      {dialog && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onClick={() => setDialog(null)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label={dialog.title}
            className="max-h-[70vh] w-full max-w-lg overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--background)] p-5"
            onClick={event => event.stopPropagation()}
          >
            <h2 className="mb-3 text-lg font-semibold">{dialog.title}</h2>
            {dialog.body ? <MarkdownRenderer content={dialog.body} enableMath /> : <p>{t("One moment.")}</p>}
            <button type="button" className="mt-4 text-sm underline" onClick={() => setDialog(null)}>
              {t("Close")}
            </button>
          </div>
        </div>
      )}
    </LearningShell>
  );
}

function styleButton(active: boolean): string {
  return `rounded-md px-3 py-1 text-sm ${active ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : ""}`;
}
