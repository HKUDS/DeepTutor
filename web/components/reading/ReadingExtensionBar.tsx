"use client";

import type { LLMSelection } from "@/features/chat/model/protocol";

import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Square, Volume2, X } from "lucide-react";
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
  selection,
  selectionLocator,
  navigationVersion = 0,
  llmSelection,
  onError,
}: {
  materialId: string;
  locator: number;
  selection?: string;
  selectionLocator?: number;
  navigationVersion?: number;
  llmSelection?: LLMSelection | null;
  onError: (message: string) => void;
}) {
  const { i18n, t } = useTranslation();
  const [extensions, setExtensions] = useState<ReadingExtensionManifest[]>([]);
  const [catalogError, setCatalogError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [hint, setHint] = useState("");
  const [actionError, setActionError] = useState("");
  const [moreOpen, setMoreOpen] = useState(false);
  const requestVersion = useRef(0);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState<ReadingExtensionResult | null>(null);
  const [speaking, setSpeaking] = useState(false);

  function stopSpeaking() {
    window.speechSynthesis?.cancel();
    setSpeaking(false);
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    setCatalogError(false);
    void listReadingExtensions()
      .then((rows) => {
        if (active) setExtensions(rows);
      })
      .catch(() => {
        if (active) setCatalogError(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reload]);

  useEffect(() => {
    setResult(null);
    setHint("");
    setActionError("");
    setBusy("");
    setMoreOpen(false);
    return () => {
      requestVersion.current += 1;
      window.speechSynthesis?.cancel();
      setSpeaking(false);
    };
  }, [locator, materialId, navigationVersion]);

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
    if (action.requires.includes("selection") && !selection?.trim()) {
      setHint(t("Select a word or passage first."));
      return;
    }
    setHint("");
    setActionError("");
    setMoreOpen(false);
    const version = ++requestVersion.current;
    const key = `${extension.id}:${action.id}`;
    setBusy(key);
    try {
      const next = await runReadingExtension(
        materialId,
        extension.id,
        action.id,
        {
          locator: action.requires.includes("selection")
            ? (selectionLocator ?? locator)
            : locator,
          ...(llmSelection ? { llm_selection: llmSelection } : {}),
          selection: selection || "",
          locale: i18n.language,
        },
      );
      if (version !== requestVersion.current) return;
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
      if (version === requestVersion.current) {
        const code =
          error && typeof error === "object" && "code" in error
            ? String(error.code)
            : "";
        // Action-only copy is loaded on failure, outside the shared app shell.
        const messages: Record<string, string> = i18n.language.startsWith("zh")
          ? (await import("@/locales/zh/reading-errors.json")).default
          : (await import("@/locales/en/reading-errors.json")).default;
        if (version !== requestVersion.current) return;
        const message =
          messages[code] ||
          (error instanceof Error ? error.message : String(error));
        setActionError(message);
        onError(message);
      }
    } finally {
      if (version === requestVersion.current) setBusy("");
    }
  }

  const primaryKeys = ["read_aloud:read", "vocabulary:explain", "quiz:start"];
  const primary = primaryKeys.flatMap((key) =>
    actions.filter(
      ({ extension, action }) => `${extension.id}:${action.id}` === key,
    ),
  );
  const secondary = actions.filter(
    ({ extension, action }) =>
      !primaryKeys.includes(`${extension.id}:${action.id}`),
  );

  function actionButton({ extension, action }: (typeof actions)[number]) {
    const key = `${extension.id}:${action.id}`;
    const builtInLabel = builtInActionLabel(extension.id, action.id);
    return (
      <button
        key={key}
        type="button"
        disabled={Boolean(busy)}
        onClick={() => void run(extension, action)}
        className="inline-flex min-h-8 min-w-0 flex-1 items-center justify-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-xs font-medium text-[var(--foreground)] transition hover:bg-[var(--muted)] disabled:opacity-50"
      >
        {busy === key ? (
          <Loader2 size={14} className="shrink-0 animate-spin" />
        ) : null}
        <span>{builtInLabel ? t(builtInLabel) : action.label}</span>
      </button>
    );
  }

  if (loading)
    return (
      <div role="status" className="shrink-0 px-3 py-2 text-xs">
        {t("Loading reading actions…")}
      </div>
    );
  if (catalogError)
    return (
      <div
        role="alert"
        className="shrink-0 border-b border-[var(--border)] px-3 py-2 text-xs"
      >
        {t("Could not load reading actions.")}
        <button
          type="button"
          className="ml-2 underline"
          onClick={() => setReload((value) => value + 1)}
        >
          {t("Retry")}
        </button>
      </div>
    );
  if (actions.length === 0) return null;
  return (
    <>
      {actionError ? (
        <div
          role="alert"
          className="border-b border-[var(--border)] px-3 py-2 text-xs"
        >
          {actionError}
        </div>
      ) : null}
      <div
        data-reading-actions
        role="toolbar"
        aria-label={t("Reading actions")}
        className="relative flex shrink-0 gap-1.5 border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--muted)_25%,transparent)] px-2.5 py-2"
      >
        {primary.map(actionButton)}
        {secondary.length > 0 ? (
          <>
            <button
              type="button"
              aria-expanded={moreOpen}
              onClick={() => setMoreOpen((open) => !open)}
              className="shrink-0 rounded-lg border border-[var(--border)] px-2 text-xs"
            >
              {t("More")}
            </button>
            {moreOpen ? (
              <div
                onKeyDown={(event) => {
                  if (event.key === "Escape") setMoreOpen(false);
                }}
                className="absolute right-2 top-full z-40 flex w-56 flex-col gap-1 rounded-lg border border-[var(--border)] bg-[var(--card)] p-2 shadow-lg"
              >
                {secondary.map(actionButton)}
              </div>
            ) : null}
          </>
        ) : null}
      </div>
      {hint ? (
        <p role="status" className="shrink-0 px-3 py-2 text-xs">
          {hint}
        </p>
      ) : null}
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
          key={requestVersion.current}
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
    return "Look up word";
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
