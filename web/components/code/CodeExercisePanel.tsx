"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Loader2, Play, RotateCcw, Terminal, X } from "lucide-react";

import CodeEditor from "./CodeEditor";
import type { CodeLanguage } from "./completions";
import {
  fetchCodeCapabilities,
  runCode,
  type CodeCapabilities,
  type CodeRunResponse,
  type CodeSpec,
} from "@/lib/code-runner-api";

interface CodeExercisePanelProps {
  questionId: string;
  turnId?: string | null;
  codeSpec?: CodeSpec;
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
  onRunResult?: (result: CodeRunResponse) => void;
}

function draftKey(turnId: string | null | undefined, questionId: string): string {
  return `code-draft:${turnId || "local"}:${questionId}`;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default function CodeExercisePanel({
  questionId,
  turnId,
  codeSpec,
  value,
  disabled = false,
  onChange,
  onRunResult,
}: CodeExercisePanelProps) {
  const { t } = useTranslation();
  const language: CodeLanguage = codeSpec?.language ?? "python";
  const starter = codeSpec?.starter_code ?? "";
  const key = draftKey(turnId, questionId);
  const [code, setCode] = useState(value || starter);
  const [capabilities, setCapabilities] = useState<CodeCapabilities | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<CodeRunResponse | null>(null);
  const [error, setError] = useState("");
  const codeRef = useRef(code);
  const onChangeRef = useRef(onChange);
  const onRunResultRef = useRef(onRunResult);
  codeRef.current = code;
  onChangeRef.current = onChange;
  onRunResultRef.current = onRunResult;

  useEffect(() => {
    let initial = value || starter;
    try {
      const draft = window.localStorage.getItem(key);
      if (draft !== null && draft !== "" && !disabled) initial = draft;
    } catch {
      /* storage may be unavailable in private mode */
    }
    if (initial !== value) {
      setCode(initial);
      onChangeRef.current(initial);
    }
    // Draft is read once per question, not on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => {
    if (value && value !== codeRef.current) setCode(value);
  }, [value]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        window.localStorage.setItem(key, code);
      } catch {
        /* ignore quota / privacy errors */
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [code, key]);

  useEffect(() => {
    let active = true;
    void fetchCodeCapabilities()
      .then((next) => {
        if (active) setCapabilities(next);
      })
      .catch(() => {
        if (active) {
          setCapabilities({
            available: false,
            isolation: "off",
            languages: [],
            max_timeout: 0,
            max_tests: 0,
          });
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const tests = useMemo(() => codeSpec?.tests ?? [], [codeSpec]);

  const updateCode = useCallback((next: string) => {
    setCode(next);
    onChangeRef.current(next);
  }, []);

  const execute = useCallback(
    async (withTests: boolean) => {
      if (!capabilities?.available || running || disabled) return;
      setRunning(true);
      setError("");
      try {
        const next = await runCode({
          language,
          code,
          stdin: codeSpec?.stdin ?? "",
          timeout: 10,
          tests: withTests ? tests : [],
        });
        setResult(next);
        onRunResultRef.current?.(next);
      } catch (err) {
        setError(errorText(err));
      } finally {
        setRunning(false);
      }
    },
    [capabilities?.available, code, codeSpec?.stdin, disabled, language, running, tests],
  );

  const reset = useCallback(() => {
    updateCode(starter);
    setResult(null);
    setError("");
    try {
      window.localStorage.removeItem(key);
    } catch {
      /* ignore */
    }
  }, [key, starter, updateCode]);

  const canRun = Boolean(capabilities?.available) && !disabled && !running;
  const publicTests = result?.tests ?? [];
  const failedTests = publicTests.filter((test) => !test.passed);

  return (
    <div
      className="mt-2 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)]"
      onKeyDown={(event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
          event.preventDefault();
          void execute(false);
        }
      }}
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] px-2.5 py-2">
        <span className="rounded-md bg-[var(--muted)] px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
          {language}
        </span>
        <div className="flex flex-1 flex-wrap items-center justify-end gap-1.5">
          <button
            type="button"
            onClick={reset}
            disabled={disabled}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2 py-1 text-[11px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <RotateCcw size={12} />
            {t("Reset")}
          </button>
          <button
            type="button"
            onClick={() => void execute(false)}
            disabled={!canRun}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-[11px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--primary)]/40 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {running ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
            {t("Run")}
          </button>
          {tests.length > 0 && (
            <button
              type="button"
              onClick={() => void execute(true)}
              disabled={!canRun}
              className="inline-flex items-center gap-1 rounded-md bg-[var(--primary)] px-2 py-1 text-[11px] font-medium text-[var(--primary-foreground,white)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {running ? <Loader2 size={12} className="animate-spin" /> : <Terminal size={12} />}
              {t("Run Tests")}
            </button>
          )}
        </div>
      </div>

      <CodeEditor
        value={code}
        language={language}
        onChange={updateCode}
        readOnly={disabled}
        minHeight={200}
        ariaLabel={t("Code editor")}
      />

      {capabilities && !capabilities.available && (
        <div className="border-t border-[var(--border)] px-3 py-2 text-[11px] text-[var(--muted-foreground)]">
          {t("Code execution is unavailable")}
        </div>
      )}

      {error && (
        <div className="border-t border-[var(--border)] px-3 py-2 text-[12px] text-[var(--destructive)]">
          {error}
        </div>
      )}

      {result && (
        <div className="border-t border-[var(--border)]">
          <div className="flex items-center justify-between px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
            <span>{t("Output")}</span>
            <span className="font-mono tabular-nums">
              {t("Exit code")}: {result.exit_code}
              {result.timed_out ? ` · ${t("Timed out")}` : ""}
            </span>
          </div>
          <div className="grid gap-2 px-3 pb-3">
            {result.stdout && (
              <pre className="max-h-56 overflow-auto rounded-md bg-[var(--muted)]/60 p-2 text-[12px] leading-relaxed text-[var(--foreground)]">
                {result.stdout}
              </pre>
            )}
            {result.stderr && (
              <pre className="max-h-56 overflow-auto rounded-md bg-[var(--destructive)]/10 p-2 text-[12px] leading-relaxed text-[var(--destructive)]">
                {result.stderr}
              </pre>
            )}
            {!result.stdout && !result.stderr && (
              <p className="text-[12px] text-[var(--muted-foreground)]">{t("No output")}</p>
            )}
          </div>

          {publicTests.length > 0 && (
            <div className="border-t border-[var(--border)] px-3 py-2">
              <p
                className={`mb-2 text-[11px] font-semibold ${
                  result.passed === result.total
                    ? "text-[var(--success)]"
                    : "text-[var(--muted-foreground)]"
                }`}
              >
                {t("Tests passed", { passed: result.passed, total: result.total })}
              </p>
              <ul className="space-y-1.5">
                {publicTests.map((test) => (
                  <li
                    key={`${test.name}:${test.duration_ms}`}
                    className="rounded-md border border-[var(--border)] px-2 py-1.5"
                  >
                    <div className="flex items-center gap-1.5 text-[11px] font-medium">
                      {test.passed ? (
                        <Check size={12} className="text-[var(--success)]" />
                      ) : (
                        <X size={12} className="text-[var(--destructive)]" />
                      )}
                      <span className="text-[var(--foreground)]">{test.name}</span>
                    </div>
                    {!test.passed && (
                      <div className="mt-1 grid gap-1 text-[11px] text-[var(--muted-foreground)]">
                        <div>
                          <span className="font-semibold">{t("Expected output")}: </span>
                          <code className="whitespace-pre-wrap">{test.expected_stdout}</code>
                        </div>
                        <div>
                          <span className="font-semibold">{t("Actual output")}: </span>
                          <code className="whitespace-pre-wrap">{test.stdout || test.stderr}</code>
                        </div>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
              {failedTests.length > 0 && result.error && (
                <p className="mt-2 text-[11px] text-[var(--destructive)]">{result.error}</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
