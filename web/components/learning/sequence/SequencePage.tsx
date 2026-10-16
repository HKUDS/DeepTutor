"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import InlineMarkdown from "@/components/common/InlineMarkdown";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { LearningShell } from "@/components/learning/LearningShell";
import { SequenceModules } from "@/components/learning/sequence/SequenceModules";
import { selectClass, selectOptionClass } from "@/components/settings/shared";
import { listKnowledgeBases, type KnowledgeBaseSummary } from "@/features/knowledge/api/client";
import { knowledgeBaseRef } from "@/lib/knowledge-helpers";
import {
  checkSequenceAnswer,
  createSequenceProblem,
  explainSequenceStep,
  getSequenceOutline,
  rebuildSequenceOutline,
  requestSequenceHint,
  type SequenceOutline,
  type SequenceProblem,
  type SequenceStep,
} from "@/lib/sequence-api";

type StepStyle = "word" | "symbol";
type StepMark = "correct" | "incorrect";
type OutlinePhase = "idle" | "loading" | "reading" | "ready" | "error";

function stepText(step: SequenceStep, style: StepStyle): string {
  if (style === "symbol") return step.math;
  return `${step.explanation} ${step.math}`;
}

function placedClass(mark: StepMark | undefined): string {
  if (mark === "correct") return "border-[var(--success)] bg-[var(--success-surface)]";
  if (mark === "incorrect") {
    return "border-[var(--destructive)] bg-[color-mix(in_srgb,var(--destructive)_14%,var(--background))]";
  }
  return "border-[var(--border)] bg-[var(--background)]";
}

export function SequencePage() {
  const { t } = useTranslation();
  const outlineRequest = useRef(0);
  const writingRef = useRef(false);
  const view = useRef(0);
  const [bases, setBases] = useState<KnowledgeBaseSummary[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [knowledgeBase, setKnowledgeBase] = useState("");
  const [customTopic, setCustomTopic] = useState("");
  const [activeTopic, setActiveTopic] = useState("");
  const [outline, setOutline] = useState<SequenceOutline | null>(null);
  const [outlinePhase, setOutlinePhase] = useState<OutlinePhase>("idle");
  const [problem, setProblem] = useState<SequenceProblem | null>(null);
  const [assembled, setAssembled] = useState<string[]>([]);
  const [marks, setMarks] = useState<StepMark[] | null>(null);
  const [banner, setBanner] = useState<StepMark | null>(null);
  const [writing, setWriting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [style, setStyle] = useState<StepStyle>("word");
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

  useEffect(() => {
    view.current += 1;
    writingRef.current = false;
    setWriting(false);
    if (!knowledgeBase) {
      setOutline(null);
      setOutlinePhase("idle");
      return;
    }
    const id = ++outlineRequest.current;
    let cancelled = false;
    setOutline(null);
    setOutlinePhase("loading");
    setProblem(null);
    setAssembled([]);
    setMarks(null);
    setBanner(null);
    setMessage("");

    void (async () => {
      const current = () => !cancelled && outlineRequest.current === id;
      try {
        const saved = await getSequenceOutline(knowledgeBase);
        if (!current()) return;
        if (saved) {
          setOutline(saved);
          setOutlinePhase("ready");
          return;
        }
        setOutlinePhase("reading");
        const built = await rebuildSequenceOutline(knowledgeBase);
        if (!current()) return;
        setOutline(built);
        setOutlinePhase("ready");
      } catch {
        if (current()) setOutlinePhase("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [knowledgeBase]);

  const byId = useMemo(() => {
    const map = new Map<string, SequenceStep>();
    problem?.steps.forEach(step => map.set(step.id, step));
    return map;
  }, [problem]);

  async function readAgain() {
    if (!knowledgeBase || outlinePhase === "loading" || outlinePhase === "reading") return;
    const id = ++outlineRequest.current;
    setOutlinePhase("reading");
    try {
      const built = await rebuildSequenceOutline(knowledgeBase);
      if (outlineRequest.current !== id) return;
      setOutline(built);
      setOutlinePhase("ready");
    } catch {
      if (outlineRequest.current === id) setOutlinePhase("error");
    }
  }

  async function startTopic(nextTopic: string) {
    const topic = nextTopic.trim();
    if (!knowledgeBase) {
      setMessage(t("Select a knowledge base first."));
      return;
    }
    if (!topic) {
      setMessage(t("Enter a topic first."));
      return;
    }
    if (writingRef.current) return;
    const viewId = ++view.current;
    writingRef.current = true;
    setWriting(true);
    setMessage("");
    try {
      const next = await createSequenceProblem(knowledgeBase, topic);
      if (view.current !== viewId) return;
      setActiveTopic(topic);
      setProblem(next);
      setAssembled([]);
      setMarks(null);
      setBanner(null);
    } catch (error) {
      if (view.current !== viewId) return;
      // The server answers with fixed English sentences that double as i18n
      // keys; a model-authored detail has no key and passes through as-is.
      setMessage(
        error instanceof Error && error.message
          ? t(error.message)
          : t("Could not write a problem from that material. Try a more specific topic."),
      );
    } finally {
      if (view.current === viewId) {
        writingRef.current = false;
        setWriting(false);
      }
    }
  }

  function clearVerdict() {
    setMarks(null);
    setBanner(null);
  }

  function addStep(stepId: string) {
    if (!problem || problem.solved || busy) return;
    setAssembled(ids => (ids.includes(stepId) ? ids : [...ids, stepId]));
    clearVerdict();
  }

  function removePlaced(stepId: string) {
    if (!problem || problem.solved || busy) return;
    setAssembled(ids => ids.filter(id => id !== stepId));
    clearVerdict();
  }

  function leaveProblem() {
    view.current += 1;
    writingRef.current = false;
    setWriting(false);
    setProblem(null);
    setAssembled([]);
    setMarks(null);
    setBanner(null);
    setMessage("");
    setDialog(null);
  }

  async function checkAnswer() {
    if (!problem || problem.solved || busy || assembled.length === 0) return;
    const viewId = view.current;
    setBusy(true);
    setMessage("");
    try {
      const result = await checkSequenceAnswer(problem.problem_id, assembled);
      if (view.current !== viewId) return;
      const solved = result.solved || result.problem.solved;
      setProblem({ ...result.problem, solved });
      setMarks(result.marks);
      setBanner(solved ? "correct" : "incorrect");
      if (solved) {
        setOutline(current =>
          current && {
            ...current,
            modules: current.modules.map(module =>
              module.topic.trim() === activeTopic.trim()
                ? {
                    ...module,
                    solved: result.problem.progress.solved,
                    goal: result.problem.progress.goal,
                  }
                : module,
            ),
          },
        );
      }
    } catch (error) {
      if (view.current !== viewId) return;
      setMessage(
        error instanceof Error && error.message ? t(error.message) : t("Could not check that step."),
      );
    } finally {
      setBusy(false);
    }
  }

  async function showHint() {
    if (!problem || busy) return;
    const viewId = view.current;
    setDialog({ title: t("Hint"), body: "" });
    try {
      const result = await requestSequenceHint(problem.problem_id, assembled);
      if (view.current !== viewId) return;
      setDialog({ title: t("Hint"), body: result.hint });
    } catch {
      if (view.current !== viewId) return;
      setDialog({ title: t("Hint"), body: t("Could not get a hint.") });
    }
  }

  async function showWhy(stepId: string) {
    if (!problem?.solved) return;
    const viewId = view.current;
    setDialog({ title: t("Why this step"), body: "" });
    try {
      const result = await explainSequenceStep(problem.problem_id, stepId);
      if (view.current !== viewId) return;
      setDialog({ title: t("Why this step"), body: result.explanation });
    } catch {
      if (view.current !== viewId) return;
      setDialog({ title: t("Why this step"), body: t("Could not explain this step.") });
    }
  }

  const bank = problem?.steps.filter(step => !assembled.includes(step.id)) ?? [];
  const placed = assembled
    .map((id, index) => {
      const step = byId.get(id);
      return step ? { step, mark: marks?.[index] } : null;
    })
    .filter((item): item is { step: SequenceStep; mark: StepMark | undefined } => !!item);
  const showOutline =
    !problem &&
    outlinePhase !== "idle" &&
    outlinePhase !== "loading" &&
    !(outlinePhase === "reading" && outline === null);

  return (
    <LearningShell
      title={t("Guided practice")}
      subtitle={t(
        "Choose a knowledge base. DeepTutor reads its modules, then you rebuild one worked solution and check every step.",
      )}
    >
      <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-end">
        <label className="grid min-w-0 flex-1 gap-1 text-sm">
          <span>{t("Knowledge base")}</span>
          <select
            className={selectClass}
            value={knowledgeBase}
            onChange={event => setKnowledgeBase(event.target.value)}
            disabled={!bases}
          >
            <option className={selectOptionClass} value="">
              {bases ? t("Knowledge base") : t("Loading knowledge bases…")}
            </option>
            {(bases ?? []).map(base => (
              <option key={knowledgeBaseRef(base)} className={selectOptionClass} value={knowledgeBaseRef(base)}>
                {base.name}
              </option>
            ))}
          </select>
        </label>
        {knowledgeBase && outlinePhase !== "idle" && (
          <button
            type="button"
            className="min-h-10 rounded-lg border border-[var(--border)] bg-[var(--background)] px-4 text-sm text-[var(--foreground)] disabled:opacity-60"
            onClick={() => void readAgain()}
            disabled={outlinePhase === "loading" || outlinePhase === "reading"}
          >
            {t("Read again")}
          </button>
        )}
      </div>

      {loadError && (
        <p role="alert" className="mb-4 text-sm text-[var(--destructive)]">
          {loadError}
        </p>
      )}
      {bases && bases.length === 0 && (
        <p className="mb-4 text-sm text-[var(--muted-foreground)]">
          {t("No knowledge base is ready. Add one in Knowledge, then come back.")}
        </p>
      )}
      {outlinePhase === "reading" && (
        <p role="status" className="mb-4 text-sm text-[var(--muted-foreground)]">
          {t("Reading the modules in this knowledge base…")}
        </p>
      )}
      {outlinePhase === "error" && (
        <p role="alert" className="mb-4 text-sm text-[var(--destructive)]">
          {t("Could not read the modules in that knowledge base.")}
        </p>
      )}
      {writing && (
        <p role="status" className="mb-4 text-sm text-[var(--muted-foreground)]">
          {t("Reading your knowledge base and writing a problem…")}
        </p>
      )}
      {message && (
        <p role="status" className="mb-4 text-sm">
          {message}
        </p>
      )}

      {showOutline && (
        <SequenceModules
          modules={outline?.modules ?? []}
          topic={customTopic}
          disabled={writing || outlinePhase === "reading"}
          onTopicChange={setCustomTopic}
          onSelect={topic => void startTopic(topic)}
          onCreate={() => void startTopic(customTopic)}
        />
      )}

      {problem && (
        <div className="space-y-5">
          <button type="button" className="text-sm text-[var(--muted-foreground)] underline" onClick={leaveProblem}>
            {t("Go back")}
          </button>
          <section className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-5">
            {activeTopic && <p className="mb-2 text-sm font-semibold text-[var(--primary)]">{activeTopic}</p>}
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

          <div className="flex justify-end">
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
            <section className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-4">
              <h2 className="mb-3 text-center text-sm font-semibold">{t("Your solution")}</h2>
              {placed.length === 0 && (
                <p className="py-8 text-center text-sm text-[var(--muted-foreground)]">
                  {t("Click a step to add it. A step that does not belong stays until you remove it.")}
                </p>
              )}
              <ol className="space-y-2">
                {placed.map(({ step, mark }) => (
                  <li key={step.id} className={`flex items-start gap-2 rounded-lg border p-3 ${placedClass(mark)}`}>
                    <div className="min-w-0 flex-1">
                      <InlineMarkdown content={stepText(step, style)} />
                    </div>
                    {problem.solved ? (
                      <button
                        type="button"
                        className="text-xs underline"
                        onClick={() => void showWhy(step.id)}
                        disabled={busy}
                      >
                        {t("Why this step")}
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="text-xs underline"
                        onClick={() => removePlaced(step.id)}
                        disabled={busy}
                      >
                        {t("Remove this step")}
                      </button>
                    )}
                  </li>
                ))}
              </ol>
            </section>
            <section className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-4">
              <h2 className="mb-3 text-center text-sm font-semibold">{t("Available steps")}</h2>
              <ul className="space-y-2">
                {bank.map(step => (
                  <li key={step.id}>
                    <button
                      type="button"
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] p-3 text-left hover:bg-[var(--muted)] disabled:opacity-60"
                      onClick={() => addStep(step.id)}
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

          {banner && (
            <p
              role="status"
              className={`rounded-lg border px-4 py-3 text-sm font-semibold ${
                banner === "correct"
                  ? "border-[var(--success)] bg-[var(--success-surface)] text-[var(--foreground)]"
                  : "border-[var(--destructive)] bg-[color-mix(in_srgb,var(--destructive)_14%,var(--background))] text-[var(--foreground)]"
              }`}
            >
              {banner === "correct" ? t("Correct. Well done.") : t("Not quite. Try again.")}
            </p>
          )}

          <div className="flex flex-wrap justify-end gap-3">
            {!problem.solved && (
              <button
                type="button"
                className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-4 py-2 text-sm"
                onClick={() => void showHint()}
                disabled={busy}
              >
                {t("Get a hint")}
              </button>
            )}
            {!problem.solved && (
              <button
                type="button"
                className="rounded-lg bg-[var(--primary)] px-4 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-60"
                onClick={() => void checkAnswer()}
                disabled={busy || assembled.length === 0}
              >
                {t("Check answer")}
              </button>
            )}
            {problem.solved && (
              <button
                type="button"
                className="rounded-lg bg-[var(--primary)] px-4 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-60"
                onClick={() => void startTopic(activeTopic)}
                disabled={writing}
              >
                {t("Next problem")}
              </button>
            )}
          </div>

          {problem.solved && problem.explanation && (
            <section className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-5">
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
