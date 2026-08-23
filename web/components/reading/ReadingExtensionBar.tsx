"use client";

import { useEffect, useMemo, useState } from "react";
import { AudioLines, ClipboardCheck, Loader2, Sparkles, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { speakBrowserText, stopBrowserSpeech } from "@/lib/browser-speech";
import {
  getUnitText,
  listReadingExtensions,
  runReadingExtension,
  submitReadingInteraction,
  type ReadingExtensionManifest,
  type ReadingExtensionResult,
} from "@/lib/reading-api";

export function ReadingExtensionBar({
  materialId,
  locator,
  selection,
  onError,
}: {
  materialId: string;
  locator: number;
  selection?: { quote: string; sourceAnchor?: string } | null;
  onError: (message: string) => void;
}) {
  const { i18n } = useTranslation();
  const [extensions, setExtensions] = useState<ReadingExtensionManifest[]>([]);
  const [busy, setBusy] = useState("");
  const [activeExtension, setActiveExtension] = useState("");
  const [result, setResult] = useState<ReadingExtensionResult | null>(null);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [speaking, setSpeaking] = useState(false);

  useEffect(() => {
    let alive = true;
    void listReadingExtensions()
      .then((rows) => {
        if (alive) setExtensions(rows);
      })
      .catch((error) => {
        if (alive) onError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      alive = false;
      stopBrowserSpeech();
    };
  }, [materialId, onError]);

  const actions = useMemo(
    () => extensions.flatMap((extension) =>
      extension.actions.map((action) => ({ extension, action }))),
    [extensions],
  );

  async function run(extension: ReadingExtensionManifest, action: { id: string }) {
    if (extension.id === "read_aloud" && speaking) {
      stopBrowserSpeech();
      setSpeaking(false);
      return;
    }
    const key = `${extension.id}:${action.id}`;
    setBusy(key);
    setActiveExtension(extension.id);
    try {
      const unit = await getUnitText(materialId, locator);
      const next = await runReadingExtension(materialId, extension.id, action.id, {
        locator,
        source_anchor: selection?.sourceAnchor || "",
        selection: selection?.quote || "",
        visible_text: unit.text,
        locale: i18n.language,
      });
      setResult(next);
      setAnswers({});
      if (next.type === "browser_speech") {
        const text = String(next.payload.text || "");
        if (!speakBrowserText(text, String(next.payload.locale || i18n.language), {
          onError,
          onEnd: () => setSpeaking(false),
        })) onError("No speech voice is available in this browser.");
        else setSpeaking(true);
      }
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy("");
    }
  }

  async function submit() {
    if (!result?.interaction_id || !activeExtension) return;
    setBusy("submit");
    try {
      setResult(await submitReadingInteraction(
        materialId,
        activeExtension,
        result.interaction_id,
        { answers },
      ));
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy("");
    }
  }

  if (actions.length === 0) return null;
  return (
    <>
      <div className="flex shrink-0 gap-1.5 overflow-x-auto border-b border-[var(--border)] bg-[var(--muted)]/25 px-2.5 py-2">
        {actions.map(({ extension, action }) => {
          const key = `${extension.id}:${action.id}`;
          const Icon = extension.id === "read_aloud"
            ? AudioLines
            : extension.id === "quiz"
              ? ClipboardCheck
              : Sparkles;
          return (
            <button
              key={key}
              type="button"
              disabled={Boolean(busy)}
              onClick={() => void run(extension, action)}
              className="inline-flex h-8 min-w-[88px] flex-1 items-center justify-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 text-xs font-medium text-[var(--foreground)] transition hover:bg-[var(--muted)] disabled:opacity-55"
            >
              {busy === key ? <Loader2 size={14} className="animate-spin" /> : <Icon size={14} />}
              <span className="truncate">{extension.id === "read_aloud" && speaking ? i18n.t("Stop") : action.label}</span>
            </button>
          );
        })}
      </div>
      {result && result.type !== "browser_speech" ? (
        <ExtensionResult
          result={result}
          answers={answers}
          busy={busy === "submit"}
          onAnswer={(id, value) => setAnswers((current) => ({ ...current, [id]: value }))}
          onSubmit={() => void submit()}
          onClose={() => setResult(null)}
          closeLabel={i18n.t("Close")}
        />
      ) : null}
    </>
  );
}

function ExtensionResult({ result, answers, busy, onAnswer, onSubmit, onClose, closeLabel }: {
  result: ReadingExtensionResult;
  answers: Record<string, number>;
  busy: boolean;
  onAnswer: (id: string, value: number) => void;
  onSubmit: () => void;
  onClose: () => void;
  closeLabel: string;
}) {
  const questions = Array.isArray(result.payload.questions)
    ? result.payload.questions as Array<{ id: string; prompt: string; choices: string[] }>
    : [];
  const concepts = Array.isArray(result.payload.concepts)
    ? result.payload.concepts.map(String)
    : [];
  return (
    <section className="relative shrink-0 border-b border-[var(--border)] bg-[var(--card)] px-3 py-3 text-xs text-[var(--foreground)]">
      <button type="button" onClick={onClose} aria-label={closeLabel} className="absolute right-2 top-2 text-[var(--muted-foreground)]"><X size={14} /></button>
      <h3 className="pr-6 font-semibold">{result.title}</h3>
      {result.message ? <p className="mt-1 text-[var(--muted-foreground)]">{result.message}</p> : null}
      {String(result.payload.overview || "") ? <p className="mt-2">{String(result.payload.overview)}</p> : null}
      {concepts.length ? <ul className="mt-2 list-disc space-y-1 pl-5">{concepts.map((row) => <li key={row}>{row}</li>)}</ul> : null}
      {String(result.payload.reflection || "") ? <p className="mt-2 font-medium">{String(result.payload.reflection)}</p> : null}
      {questions.map((question) => (
        <fieldset key={question.id} className="mt-3 space-y-1">
          <legend className="font-medium">{question.prompt}</legend>
          {question.choices.map((choice, index) => (
            <label key={`${question.id}-${index}`} className="flex gap-2">
              <input type="radio" name={question.id} checked={answers[question.id] === index} onChange={() => onAnswer(question.id, index)} />
              <span>{choice}</span>
            </label>
          ))}
        </fieldset>
      ))}
      {questions.length ? (
        <button type="button" disabled={busy || Object.keys(answers).length !== questions.length} onClick={onSubmit} className="mt-3 rounded-md bg-[var(--primary)] px-3 py-1.5 font-medium text-[var(--primary-foreground)] disabled:opacity-50">
          {busy ? "Checking…" : "Submit"}
        </button>
      ) : null}
    </section>
  );
}
