"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Sparkles, Square, Volume2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  listReadingExtensions,
  runReadingExtension,
  type ReadingExtensionManifest,
  type ReadingExtensionResult,
} from "@/lib/reading-api";

type VocabularyTerm = {
  term: string;
  meaning: string;
  usage: string;
};

type QuizQuestion = {
  id?: string;
  prompt: string;
  choices: string[];
  correct_choice_index?: number;
};

type TranslationResult = {
  translation: string;
  alternatives: string[];
  note: string;
};

export function ReadingExtensionBar({
  materialId,
  locator,
  selectionLocator,
  selection,
  onError,
}: {
  materialId: string;
  locator: number;
  /**
   * The unit the selection was made in, when there is one.
   *
   * `locator` is the *viewport* locator and drifts as the reader scrolls. The
   * server verifies the quote against the text of the unit it is told about
   * and 400s when they disagree, so a selection has to travel with its own.
   */
  selectionLocator?: number;
  selection?: string;
  onError: (message: string) => void;
}) {
  const { i18n, t } = useTranslation();
  const [extensions, setExtensions] = useState<ReadingExtensionManifest[]>([]);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState<ReadingExtensionResult | null>(null);
  const [speaking, setSpeaking] = useState(false);

  function stopSpeaking() {
    window.speechSynthesis?.cancel();
    setSpeaking(false);
  }

  useEffect(() => {
    let active = true;
    void listReadingExtensions()
      .then((rows) => {
        if (active) setExtensions(rows);
      })
      .catch((error) => {
        if (active)
          onError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      active = false;
    };
  }, [onError]);

  // Two effects, because the two things they clean up move on different
  // clocks. A result belongs to the document: keyed on `locator` as well, an
  // ordinary scroll erased a card the reader was still reading, since
  // `locator` is the scroll-derived *viewport* locator.
  useEffect(() => {
    setResult(null);
  }, [materialId]);

  // Speech, on the other hand, must stop the moment the reader navigates
  // away from the passage being read aloud — so this one keeps both keys.
  useEffect(() => {
    return () => {
      window.speechSynthesis?.cancel();
      setSpeaking(false);
    };
  }, [locator, materialId]);

  const actions = useMemo(
    () =>
      extensions.flatMap((extension) =>
        extension.actions.map((action) => ({ extension, action })),
      ),
    [extensions],
  );

  async function run(
    extension: ReadingExtensionManifest,
    action: ReadingExtensionManifest["actions"][number],
  ) {
    const key = `${extension.id}:${action.id}`;
    setBusy(key);
    try {
      const next = await runReadingExtension(
        materialId,
        extension.id,
        action.id,
        {
          locator: selection?.trim() ? (selectionLocator ?? locator) : locator,
          selection: selection || "",
          locale: i18n.language,
        },
      );
      setResult(next);
      if (next.type === "browser_speech") {
        const text = String(next.payload.text || "");
        if (!("speechSynthesis" in window) || !text) {
          onError(t("No speech voice is available in this browser."));
          return;
        }
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = String(next.payload.locale || i18n.language);
        utterance.onend = () => setSpeaking(false);
        utterance.onerror = () => setSpeaking(false);
        window.speechSynthesis.speak(utterance);
        setSpeaking(true);
      }
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy("");
    }
  }

  if (actions.length === 0) return null;
  return (
    <>
      <div className="flex shrink-0 gap-1.5 overflow-x-auto border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--muted)_25%,transparent)] px-2.5 py-2">
        {actions.map(({ extension, action }) => {
          const key = `${extension.id}:${action.id}`;
          const needsSelection =
            action.requires.includes("selection") && !selection?.trim();
          // `busy === key`, not `Boolean(busy)`: an action can take the full
          // 30s server timeout, and disabling all six meanwhile is
          // indistinguishable from the toolbar being broken.
          const disabled = busy === key || needsSelection;
          const builtInLabel = builtInActionLabel(extension.id, action.id);
          return (
            <button
              key={key}
              type="button"
              disabled={disabled}
              title={
                needsSelection
                  ? t("Select text in the document first.")
                  : undefined
              }
              onClick={() => void run(extension, action)}
              className="inline-flex h-8 min-w-[88px] flex-1 items-center justify-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 text-xs font-medium text-[var(--foreground)] transition hover:bg-[var(--muted)] disabled:opacity-50"
            >
              {busy === key ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Sparkles size={14} />
              )}
              <span className="truncate">
                {builtInLabel ? t(builtInLabel) : action.label}
              </span>
            </button>
          );
        })}
      </div>
      {speaking ? (
        <div
          role="status"
          className="flex shrink-0 items-center gap-2 border-b border-[var(--border)] bg-[var(--card)] px-3 py-2 text-xs text-[var(--muted-foreground)]"
        >
          <Volume2 size={14} />
          <span>{t("Reading aloud")}</span>
          <button
            type="button"
            aria-label={t("Stop reading aloud")}
            title={t("Stop reading aloud")}
            onClick={stopSpeaking}
            className="ml-auto inline-flex h-7 w-7 items-center justify-center rounded-md text-[var(--foreground)] transition hover:bg-[var(--muted)]"
          >
            <Square size={12} fill="currentColor" />
          </button>
        </div>
      ) : null}
      {result && result.type !== "browser_speech" ? (
        <ExtensionResult
          result={result}
          closeLabel={t("Close")}
          onClose={() => setResult(null)}
        />
      ) : null}
    </>
  );
}

function builtInActionLabel(extensionId: string, actionId: string) {
  if (extensionId === "read_aloud" && actionId === "read") {
    return "Read aloud";
  }
  if (extensionId === "guided_learning" && actionId === "guide") {
    return "Guide me";
  }
  if (extensionId === "vocabulary" && actionId === "explain") {
    return "Explain vocabulary";
  }
  if (extensionId === "quiz" && actionId === "start") {
    return "Quiz me";
  }
  if (extensionId === "translation" && actionId === "translate_en") {
    return "Translate to English";
  }
  if (extensionId === "translation" && actionId === "translate_zh") {
    return "Translate to Chinese";
  }
  return "";
}

function ExtensionResult({
  result,
  closeLabel,
  onClose,
}: {
  result: ReadingExtensionResult;
  closeLabel: string;
  onClose: () => void;
}) {
  const questions = Array.isArray(result.payload.questions)
    ? (result.payload.questions as QuizQuestion[])
    : [];
  const items = Array.isArray(result.payload.items)
    ? result.payload.items.map(String)
    : [];
  const steps = Array.isArray(result.payload.steps)
    ? result.payload.steps.map(String)
    : [];
  const terms: VocabularyTerm[] = Array.isArray(result.payload.terms)
    ? result.payload.terms
        .map((row) => {
          if (typeof row !== "object" || row === null) return null;
          const term = row as Partial<VocabularyTerm>;
          return {
            term: String(term.term || ""),
            meaning: String(term.meaning || ""),
            usage: String(term.usage || ""),
          };
        })
        .filter((row): row is VocabularyTerm => row !== null)
    : [];
  const translation: TranslationResult = {
    translation: String(result.payload.translation || ""),
    alternatives: Array.isArray(result.payload.alternatives)
      ? result.payload.alternatives.map(String)
      : [],
    note: String(result.payload.note || ""),
  };
  const body = String(result.payload.body || result.payload.overview || "");
  return (
    <section className="relative shrink-0 border-b border-[var(--border)] bg-[var(--card)] px-3 py-3 text-xs text-[var(--foreground)]">
      <button
        type="button"
        onClick={onClose}
        aria-label={closeLabel}
        className="absolute right-2 top-2 text-[var(--muted-foreground)]"
      >
        <X size={14} />
      </button>
      <h3 className="pr-6 font-semibold">{result.title}</h3>
      {result.message ? (
        <p className="mt-1 text-[var(--muted-foreground)]">{result.message}</p>
      ) : null}
      {body ? <p className="mt-2 whitespace-pre-wrap">{body}</p> : null}
      {translation.translation ? (
        <p className="mt-2 whitespace-pre-wrap font-medium">
          {translation.translation}
        </p>
      ) : null}
      {translation.note ? (
        <p className="mt-1 text-[var(--muted-foreground)]">
          {translation.note}
        </p>
      ) : null}
      {translation.alternatives.length ? (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-[var(--muted-foreground)]">
          {translation.alternatives.map((alternative, index) => (
            <li key={`${index}-${alternative}`}>{alternative}</li>
          ))}
        </ul>
      ) : null}
      {items.length ? (
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {items.map((item, index) => (
            <li key={`${index}-${item}`}>{item}</li>
          ))}
        </ul>
      ) : null}
      {steps.length ? (
        <ol className="mt-2 list-decimal space-y-1 pl-5">
          {steps.map((step, index) => (
            <li key={`${index}-${step}`}>{step}</li>
          ))}
        </ol>
      ) : null}
      {terms.length ? (
        <dl className="mt-2 space-y-2">
          {terms.map((term, index) => (
            <div
              key={`${index}-${term.term}`}
              className="border-t border-[var(--border)] pt-2 first:border-t-0 first:pt-0"
            >
              <dt className="font-medium">{term.term}</dt>
              <dd className="mt-1 text-[var(--muted-foreground)]">
                {term.meaning}
              </dd>
              <dd className="mt-1 text-[var(--muted-foreground)]">
                {term.usage}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {questions.length ? <QuizQuestions questions={questions} /> : null}
    </section>
  );
}

function QuizQuestions({ questions }: { questions: QuizQuestion[] }) {
  const { t } = useTranslation();
  const [answers, setAnswers] = useState<Record<string, number>>({});

  return questions.map((question, index) => {
    const key = question.id || String(index);
    const selected = answers[key];
    const correctChoiceIndex = Number.isInteger(question.correct_choice_index)
      ? Number(question.correct_choice_index)
      : -1;
    const canGrade =
      correctChoiceIndex >= 0 && correctChoiceIndex < question.choices.length;
    if (!canGrade) {
      return (
        <div key={key} className="mt-3">
          <p className="font-medium">{question.prompt}</p>
          <ol className="mt-1 list-inside list-[upper-alpha] space-y-0.5 text-[var(--muted-foreground)]">
            {question.choices.map((choice) => (
              <li key={choice}>{choice}</li>
            ))}
          </ol>
        </div>
      );
    }
    return (
      <fieldset key={key} className="mt-3">
        <legend className="font-medium">{question.prompt}</legend>
        <div className="mt-1 grid gap-1">
          {question.choices.map((choice, choiceIndex) => (
            <button
              key={choice}
              type="button"
              aria-pressed={selected === choiceIndex}
              onClick={() =>
                setAnswers((current) => ({ ...current, [key]: choiceIndex }))
              }
              className="rounded-md border border-[var(--border)] px-2 py-1.5 text-left text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] aria-pressed:bg-[var(--muted)] aria-pressed:text-[var(--foreground)]"
            >
              {String.fromCharCode(65 + choiceIndex)}. {choice}
            </button>
          ))}
        </div>
        {selected !== undefined ? (
          <p
            role="status"
            className={`mt-1 font-medium ${
              selected === correctChoiceIndex
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-amber-600 dark:text-amber-400"
            }`}
          >
            {selected === correctChoiceIndex ? t("Correct") : t("Incorrect")}
          </p>
        ) : null}
      </fieldset>
    );
  });
}
