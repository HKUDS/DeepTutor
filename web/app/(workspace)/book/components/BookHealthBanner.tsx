"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, RefreshCcw, X, ScrollText } from "lucide-react";
import { useTranslation } from "react-i18next";
import { bookApi } from "@/lib/book-api";

export interface BookHealthBannerProps {
  bookId: string | null;
  refreshKey?: number;
  onRecompile?: (pageId: string) => void;
  /** Retrieval failed while this book was planned — it was written from the
   *  proposal alone, with none of the selected sources behind it. */
  explorationFailed?: boolean;
}

interface KbDrift {
  has_drift: boolean;
  new_kbs?: string[];
  removed_kbs?: string[];
  changed_kbs?: string[];
  stale_page_ids?: string[];
}

interface LogHealth {
  total_entries: number;
  error_entries: number;
  block_failures: number;
  repeated_failures?: { signature: string; count: number }[];
}

export default function BookHealthBanner({
  bookId,
  refreshKey,
  onRecompile,
  explorationFailed = false,
}: BookHealthBannerProps) {
  const { t } = useTranslation();
  const [kbDrift, setKbDrift] = useState<KbDrift | null>(null);
  const [logHealth, setLogHealth] = useState<LogHealth | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [acknowledgeError, setAcknowledgeError] = useState<string | null>(null);
  const [canForce, setCanForce] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!bookId) {
      setKbDrift(null);
      setLogHealth(null);
      return;
    }
    // `refreshKey` is the book's `updated_at`, undefined until the book has
    // loaded. Waiting for it avoids a duplicate check on every open — and this
    // one is expensive: it stats every raw file in the book's knowledge bases.
    if (refreshKey === undefined) return;
    setDismissed(false);
    (async () => {
      try {
        const data = await bookApi.health(bookId);
        if (cancelled) return;
        setKbDrift(data.kb_drift);
        setLogHealth(data.log_health);
      } catch {
        // ignore – health is non-critical
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [bookId, refreshKey]);

  if (!bookId || dismissed) return null;

  const hasDrift = !!kbDrift?.has_drift;
  // Filter out repeated failures that are already represented elsewhere
  // (kb_health drift logs are surfaced via the kb-drift section above).
  const repeated = (logHealth?.repeated_failures || [])
    .filter((r) => {
      const sig = (r.signature || "").toLowerCase();
      if (sig.includes("kb_health")) return false;
      if (sig.includes("kb drift")) return false;
      return true;
    })
    .slice(0, 3);
  const blockFailures = logHealth?.block_failures || 0;
  const hasLogIssues = blockFailures >= 3 || repeated.length > 0;

  if (!hasDrift && !hasLogIssues && !explorationFailed) return null;

  // Convert technical signatures into a short human label.
  const humanizeSignature = (sig: string): string => {
    if (!sig) return t("unknown failure");
    const stripped = sig.replace(/^[a-z_]+:/i, "").trim();
    return stripped.length > 80 ? `${stripped.slice(0, 80)}…` : stripped;
  };

  const acknowledge = async (force = false) => {
    if (!bookId) return;
    setBusy(true);
    setAcknowledgeError(null);
    try {
      await bookApi.refreshFingerprints(bookId, force);
      setKbDrift({ has_drift: false });
      setCanForce(false);
    } catch (err) {
      setAcknowledgeError(err instanceof Error ? err.message : String(err));
      // The refusal is about pages still owed, not a transport failure. Stale
      // detection over-marks on purpose, so offer the override rather than
      // leaving a banner nothing can clear.
      if (!force) setCanForce(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-6 mt-4 rounded-xl border border-amber-300/60 bg-amber-50 px-4 py-3 text-sm text-amber-900 shadow-sm dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="flex-1 space-y-1.5">
          {explorationFailed && (
            <div>
              <strong>
                {t("This book was written without reading your sources.")}
              </strong>{" "}
              <span>
                {t(
                  "Retrieval failed while planning it, so the chapters come from the proposal alone. Rebuilding will try your knowledge bases again.",
                )}
              </span>
            </div>
          )}
          {hasDrift && (
            <div>
              <strong>
                {t(
                  "Your knowledge bases changed since this book was generated.",
                )}
              </strong>{" "}
              <span className="opacity-90">
                {kbDrift?.new_kbs?.length ? (
                  <>
                    {t("Newly added")}:{" "}
                    <code className="rounded bg-white/40 px-1 text-[11px] dark:bg-white/10">
                      {kbDrift.new_kbs.join(", ")}
                    </code>
                    .{" "}
                  </>
                ) : null}
                {kbDrift?.changed_kbs?.length ? (
                  <>
                    {t("Updated")}:{" "}
                    <code className="rounded bg-white/40 px-1 text-[11px] dark:bg-white/10">
                      {kbDrift.changed_kbs.join(", ")}
                    </code>
                    .{" "}
                  </>
                ) : null}
                {kbDrift?.removed_kbs?.length ? (
                  <>
                    {t("Removed")}:{" "}
                    <code className="rounded bg-white/40 px-1 text-[11px] dark:bg-white/10">
                      {kbDrift.removed_kbs.join(", ")}
                    </code>
                    .{" "}
                  </>
                ) : null}
              </span>
              {kbDrift?.stale_page_ids?.length ? (
                <div className="mt-1.5 text-xs opacity-90">
                  {kbDrift.stale_page_ids.length === 1
                    ? t(
                        "{{count}} previously-compiled page may be out of date.",
                        {
                          count: kbDrift.stale_page_ids.length,
                        },
                      )
                    : t(
                        "{{count}} previously-compiled pages may be out of date.",
                        {
                          count: kbDrift.stale_page_ids.length,
                        },
                      )}{" "}
                  {onRecompile && kbDrift.stale_page_ids[0] && (
                    <button
                      onClick={() => onRecompile(kbDrift.stale_page_ids![0])}
                      className="ml-1 inline-flex items-center gap-1 rounded border border-current px-1.5 py-0.5 text-xs hover:bg-white/40"
                    >
                      <RefreshCcw className="h-3 w-3" />{" "}
                      {t("Recompile first stale page")}
                    </button>
                  )}
                </div>
              ) : null}
            </div>
          )}
          {hasLogIssues && (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <ScrollText className="h-3.5 w-3.5" />
              {blockFailures > 0 && (
                <span>
                  {blockFailures === 1
                    ? t("{{count}} block generation failure recorded.", {
                        count: blockFailures,
                      })
                    : t("{{count}} block generation failures recorded.", {
                        count: blockFailures,
                      })}
                </span>
              )}
              {repeated.length > 0 && (
                <span>
                  {repeated.length === 1
                    ? t("Recurring issue")
                    : t("Recurring issues")}
                  :{" "}
                  {repeated
                    .map(
                      (r) => `${humanizeSignature(r.signature)} (×${r.count})`,
                    )
                    .join("; ")}
                  .
                </span>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-1">
          {hasDrift && (
            <button
              onClick={() => acknowledge()}
              disabled={busy}
              title={t(
                "Available only after every stale page has been recompiled.",
              )}
              className="whitespace-nowrap rounded-md border border-current px-2 py-1 text-xs font-medium hover:bg-white/40 disabled:opacity-60"
            >
              {busy ? "…" : t("Mark as seen")}
            </button>
          )}
          {hasDrift && canForce && (
            <button
              onClick={() => acknowledge(true)}
              disabled={busy}
              title={t("Dismiss the warning without recompiling those pages.")}
              className="whitespace-nowrap rounded-md border border-current px-2 py-1 text-xs font-medium hover:bg-white/40 disabled:opacity-60"
            >
              {t("Mark as seen anyway")}
            </button>
          )}
          <button
            onClick={() => setDismissed(true)}
            className="rounded p-1 text-amber-700 hover:bg-white/40 dark:text-amber-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {acknowledgeError && (
          <div className="text-xs font-medium text-red-700 dark:text-red-200">
            {acknowledgeError}
          </div>
        )}
      </div>
    </div>
  );
}
