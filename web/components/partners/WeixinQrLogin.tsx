"use client";

/**
 * Scan-to-connect for the personal-WeChat channel (#951).
 *
 * The channel authenticates by QR and always has — but it drew the code on the
 * server's stdout, which on a container deployment is a supervisord log the
 * admin cannot read. So its own advice, "scan the QR code to authenticate", had
 * nowhere to be followed. This panel is that missing surface.
 *
 * The token is never in flight here: the server writes it into the partner's
 * channel config and these replies only ever say whether the scan succeeded.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, QrCode, RefreshCw } from "lucide-react";
import {
  pollWeixinQr,
  startWeixinQr,
  type WeixinQrSession,
} from "@/lib/partners-api";

const POLL_INTERVAL_MS = 2000;

export default function WeixinQrLogin({
  partnerId,
  onConfirmed,
}: {
  partnerId: string;
  /** The config now holds a token — the caller reloads to show it masked. */
  onConfirmed?: () => void;
}) {
  const { t } = useTranslation();
  const [session, setSession] = useState<WeixinQrSession | null>(null);
  const [svg, setSvg] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Polling closes over the session it started with; a ref keeps the timer
  // pointed at the current attempt when the admin restarts the scan.
  const sessionRef = useRef<string>("");

  const settled =
    session?.status === "confirmed" ||
    session?.status === "expired" ||
    session?.status === "error";

  const start = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const started = await startWeixinQr(partnerId);
      sessionRef.current = started.session_id;
      setSession(started);
      setSvg(started.qr_svg ?? "");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [partnerId]);

  useEffect(() => {
    if (!session || settled) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const next = await pollWeixinQr(partnerId, sessionRef.current);
        if (cancelled || next.session_id !== sessionRef.current) return;
        setSession(next);
        // Only sent when the code actually changed, so an unchanged reply must
        // not blank the image already on screen.
        if (next.qr_svg) setSvg(next.qr_svg);
        if (next.status === "confirmed") onConfirmed?.();
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [session, settled, partnerId, onConfirmed]);

  const statusLine = () => {
    switch (session?.status) {
      case "waiting":
        return t("Waiting for a scan…");
      case "scanned":
        return t("Scanned — confirm on your phone.");
      case "confirmed":
        return t("Connected. The bot token has been saved.");
      case "expired":
        return t("This code expired. Start a new scan.");
      case "error":
        return session.error || t("The scan failed.");
      default:
        return "";
    }
  };

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[12px] font-medium text-[var(--foreground)]">
          <QrCode className="h-3.5 w-3.5 text-[var(--primary)]" aria-hidden />
          {t("Scan to connect")}
        </div>
        <button
          type="button"
          onClick={() => void start()}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--ring)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? (
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
          ) : (
            <RefreshCw className="h-3 w-3" aria-hidden />
          )}
          {session ? t("New code") : t("Get a code")}
        </button>
      </div>

      <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
        {t(
          "Sign in with the WeChat account this partner should speak as. The bot token is saved on the server.",
        )}
      </p>

      {error && (
        <p className="mt-2 text-[11px] text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      {session && !error && (
        <div className="mt-3 flex items-center gap-3">
          {svg && session.status !== "confirmed" ? (
            <div
              className="h-[132px] w-[132px] shrink-0 rounded-md bg-white p-1.5 [&_svg]:h-full [&_svg]:w-full"
              // Server-rendered from the scan payload: a QR path, no scripting.
              dangerouslySetInnerHTML={{ __html: svg }}
              role="img"
              aria-label={t("WeChat login QR code")}
            />
          ) : null}
          <div className="min-w-0 text-[11px] text-[var(--muted-foreground)]">
            <p>{statusLine()}</p>
            {/* Without the server-side `qrcode` library there is no image to
                draw, so show the payload rather than an empty box. */}
            {!svg && session.scan_payload && session.status !== "confirmed" && (
              <p className="mt-1 break-all font-mono text-[10px] opacity-80">
                {session.scan_payload}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
