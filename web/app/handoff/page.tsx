"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { KeyRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import { normalizeInternalReturnPath } from "@/shared/auth/return-url";
import {
  completeSessionHandoff,
  exchangeSessionHandoff,
} from "@/lib/session-handoff-api";

function HandoffPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useTranslation();
  const next = normalizeInternalReturnPath(searchParams.get("next"));
  const [manualCode, setManualCode] = useState("");
  const [status, setStatus] = useState<"idle" | "working" | "error">("idle");
  const [error, setError] = useState("");
  const started = useRef(false);

  const finish = useCallback(
    async (code: string) => {
      setStatus("working");
      setError("");
      try {
        const ticket = await exchangeSessionHandoff(code.trim());
        await completeSessionHandoff(ticket);
        router.replace(next);
      } catch (err) {
        setStatus("error");
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [next, router],
  );

  useEffect(() => {
    const code = searchParams.get("code")?.trim() ?? "";
    window.history.replaceState(null, "", window.location.pathname);
    if (!code || started.current) return;
    started.current = true;
    const timer = window.setTimeout(() => {
      void finish(code);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [finish, searchParams]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--background)] px-4">
      <div className="w-full max-w-sm rounded-2xl border border-[var(--border)] bg-[var(--card)] p-7 shadow-sm">
        <div className="flex items-center gap-2.5">
          <KeyRound size={18} className="text-[var(--primary)]" />
          <h1 className="text-lg font-semibold text-[var(--foreground)]">
            {t("Public device sign-in")}
          </h1>
        </div>
        {status === "working" ? (
          <p className="mt-4 text-sm text-[var(--muted-foreground)]">
            {t("Completing sign-in…")}
          </p>
        ) : (
          <form
            className="mt-5 space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              void finish(manualCode);
            }}
          >
            <label
              htmlFor="handoff-code"
              className="block text-sm font-medium text-[var(--foreground)]"
            >
              {t("Pairing code")}
            </label>
            <input
              id="handoff-code"
              value={manualCode}
              onChange={(event) => setManualCode(event.target.value)}
              autoComplete="one-time-code"
              spellCheck={false}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-mono text-sm text-[var(--foreground)] outline-none focus:ring-2 focus:ring-[var(--primary)]"
            />
            <button
              type="submit"
              className="w-full rounded-lg bg-[var(--primary)] px-3.5 py-2 text-sm font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
            >
              {t("Continue")}
            </button>
          </form>
        )}
        {status === "error" && (
          <p className="mt-4 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}
      </div>
    </main>
  );
}

export default function HandoffPage() {
  return (
    <Suspense fallback={null}>
      <HandoffPageContent />
    </Suspense>
  );
}
