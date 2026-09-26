"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ClipboardCopy, KeyRound, Link2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { fetchAuthStatus } from "@/lib/auth";
import { copyText } from "@/lib/clipboard";
import { createSessionHandoff, type SessionHandoff } from "@/lib/session-handoff-api";

export default function SessionHandoffPage() {
  const router = useRouter();
  const { t } = useTranslation();
  const [publicOrigin, setPublicOrigin] = useState("https://");
  const [handoff, setHandoff] = useState<SessionHandoff | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void fetchAuthStatus().then((status) => {
      if (cancelled) return;
      if (!status?.enabled || !status.authenticated) router.replace("/login");
    });
    return () => {
      cancelled = true;
    };
  }, [router]);

  const submit = useCallback(async () => {
    setLoading(true);
    setError("");
    setCopied(false);
    try {
      setHandoff(await createSessionHandoff(publicOrigin.trim()));
    } catch (err) {
      setHandoff(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [publicOrigin]);

  const copy = useCallback(async () => {
    if (!handoff) return;
    try {
      await copyText(handoff.handoff_url);
      setCopied(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [handoff]);

  return (
    <div className="min-h-screen bg-[var(--background)] px-4 py-10">
      <div className="mx-auto max-w-xl">
        <Link
          href="/profile"
          className="mb-4 inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
        >
          <ArrowLeft size={16} />
          {t("Back")}
        </Link>
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-sm">
          <div className="flex items-center gap-2.5">
            <KeyRound size={18} className="text-[var(--primary)]" />
            <h1 className="text-lg font-semibold text-[var(--foreground)]">
              {t("Public device sign-in")}
            </h1>
          </div>
          <form
            className="mt-5 space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <label
              htmlFor="public-origin"
              className="block text-sm font-medium text-[var(--foreground)]"
            >
              {t("Public HTTPS origin")}
            </label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                id="public-origin"
                value={publicOrigin}
                onChange={(event) => setPublicOrigin(event.target.value)}
                inputMode="url"
                autoComplete="url"
                spellCheck={false}
                className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:ring-2 focus:ring-[var(--primary)]"
              />
              <button
                type="submit"
                disabled={loading}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-sm font-medium text-[var(--primary-foreground)] transition-opacity disabled:opacity-50"
              >
                <Link2 size={14} />
                {loading ? t("Creating…") : t("Create link")}
              </button>
            </div>
          </form>
          {error && (
            <p className="mt-4 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-400">
              {error}
            </p>
          )}
          {handoff && (
            <div className="mt-5 rounded-xl border border-[var(--border)] bg-[var(--background)] p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <span className="font-mono text-sm break-all text-[var(--foreground)]">
                  {handoff.code}
                </span>
                <button
                  type="button"
                  onClick={() => void copy()}
                  title={t("Copy link")}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-xs text-[var(--foreground)] transition-colors hover:bg-[var(--card)]"
                >
                  <ClipboardCopy size={14} />
                  {copied ? t("Copied") : t("Copy")}
                </button>
              </div>
              <p className="mt-3 break-all text-sm text-[var(--muted-foreground)]">
                {handoff.handoff_url}
              </p>
              <p className="mt-2 text-xs text-[var(--muted-foreground)]">
                {t("Expires in {{seconds}} seconds", { seconds: handoff.expires_in })}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
