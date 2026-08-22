"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  ExternalLink,
  Loader2,
  QrCode,
  RefreshCw,
  TriangleAlert,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  applyChannelOnboarding,
  cancelChannelOnboarding,
  getChannelOnboarding,
  startChannelOnboarding,
  type PartnerChannelOnboardingChannel,
  type PartnerChannelOnboardingSession,
} from "@/lib/partners-api";

const ACTIVE_STATUSES = new Set(["pending_scan", "ready"]);

export default function ChannelOnboardingPanel({
  partnerId,
  channel,
  onApplied,
  onToast,
}: {
  partnerId: string;
  channel: PartnerChannelOnboardingChannel;
  onApplied: () => Promise<void> | void;
  onToast: (message: string) => void;
}) {
  const { t } = useTranslation();
  const [session, setSession] =
    useState<PartnerChannelOnboardingSession | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const applyingRef = useRef(false);

  useEffect(() => {
    setSession(null);
    setError(null);
  }, [partnerId, channel]);

  useEffect(() => {
    if (!session || !ACTIVE_STATUSES.has(session.status)) return;
    const timer = setInterval(() => setNowMs(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, [session]);

  const applySession = useCallback(
    async (sessionId: string) => {
      if (applyingRef.current) return;
      applyingRef.current = true;
      setBusy(true);
      setError(null);
      try {
        const result = await applyChannelOnboarding(partnerId, sessionId);
        setSession(result.session);
        onToast(t("Channel connected"));
        await onApplied();
      } catch (err) {
        setError(err instanceof Error ? err.message : t("Connection failed"));
      } finally {
        applyingRef.current = false;
        setBusy(false);
      }
    },
    [onApplied, onToast, partnerId, t],
  );

  const poll = useCallback(
    async (sessionId: string) => {
      try {
        const next = await getChannelOnboarding(partnerId, sessionId);
        setSession(next);
        if (next.status === "ready") {
          void applySession(next.session_id);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : t("Status check failed"));
      }
    },
    [applySession, partnerId, t],
  );

  useEffect(() => {
    if (!session || session.status !== "pending_scan") return;
    let cancelled = false;
    const pollOnce = async () => {
      if (!cancelled) await poll(session.session_id);
    };
    void pollOnce();
    const timer = setInterval(
      () => void pollOnce(),
      Math.max(1, session.poll_interval_seconds) * 1_000,
    );
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [poll, session]);

  const start = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setSession(await startChannelOnboarding(partnerId, channel));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Connection failed"));
    } finally {
      setBusy(false);
    }
  }, [channel, partnerId, t]);

  const cancel = useCallback(async () => {
    if (!session) return;
    setBusy(true);
    try {
      setSession(await cancelChannelOnboarding(partnerId, session.session_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Cancel failed"));
    } finally {
      setBusy(false);
    }
  }, [partnerId, session, t]);

  const secondsLeft = useMemo(() => {
    if (!session || !ACTIVE_STATUSES.has(session.status)) return null;
    return Math.max(
      0,
      Math.floor((new Date(session.expires_at).getTime() - nowMs) / 1_000),
    );
  }, [nowMs, session]);

  const statusText = useMemo(() => {
    const labels = {
      pending_scan: t("Waiting for scan"),
      ready: t("Scan completed"),
      applied: t("Connected"),
      cancelled: t("Cancelled"),
      expired: t("Expired"),
      denied: t("Authorization denied"),
      failed: t("Connection failed"),
    } as const;
    return session ? labels[session.status] : null;
  }, [session, t]);

  const active = session ? ACTIVE_STATUSES.has(session.status) : false;
  const canRestart =
    !session || !active || session.status === "ready" ? session !== null : true;

  return (
    <div className="space-y-3 border-t border-[var(--border)] pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="inline-flex items-center gap-2 text-[12px] font-medium text-[var(--foreground)]">
          <QrCode className="h-4 w-4" />
          {t("Scan to connect")}
        </div>
        {statusText && (
          <span
            aria-live="polite"
            className={`inline-flex items-center gap-1.5 text-[12px] ${
              session?.status === "applied"
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-[var(--muted-foreground)]"
            }`}
          >
            {session?.status === "applied" && (
              <CheckCircle2 className="h-3.5 w-3.5" />
            )}
            {statusText}
            {secondsLeft !== null && (
              <span className="font-mono">
                {t("{{count}}s remaining", { count: secondsLeft })}
              </span>
            )}
          </span>
        )}
      </div>

      {channel === "wecom" && (
        <p className="flex items-start gap-2 rounded-md bg-amber-500/10 px-2.5 py-2 text-[11px] leading-5 text-amber-700 dark:text-amber-300">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {t(
            "WeCom will allow every user who can reach this bot. Restrict allowed senders after setup if needed.",
          )}
        </p>
      )}

      {session?.qr_data_url && active ? (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={session.qr_data_url}
            alt={t("Authorization QR code")}
            className="h-[168px] w-[168px] shrink-0 rounded-md border border-[var(--border)] bg-white p-2"
          />
          <a
            href={session.fallback_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex w-fit items-center gap-1.5 text-[12px] text-[var(--primary)] underline-offset-4 hover:underline"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            {t("Open authorization link")}
          </a>
        </div>
      ) : session && active ? (
        <a
          href={session.fallback_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex w-fit items-center gap-1.5 text-[12px] text-[var(--primary)] underline-offset-4 hover:underline"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          {t("Open authorization link")}
        </a>
      ) : null}

      {error && (
        <p className="text-[12px] text-red-600 dark:text-red-400">{error}</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {session && active ? (
          <>
            {session.status === "ready" && (
              <button
                type="button"
                onClick={() => void applySession(session.session_id)}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-2.5 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
              >
                {busy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                {t("Apply")}
              </button>
            )}
            <button
              type="button"
              onClick={() => void cancel()}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[12px] font-medium text-[var(--foreground)] disabled:opacity-40"
            >
              <X className="h-3.5 w-3.5" />
              {t("Cancel")}
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => void start()}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-2.5 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <QrCode className="h-3.5 w-3.5" />
            )}
            {canRestart ? t("Try again") : t("Start")}
          </button>
        )}
      </div>
    </div>
  );
}
