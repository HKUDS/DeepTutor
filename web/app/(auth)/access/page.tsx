"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useTranslation } from "react-i18next";
import { QRCodeSVG } from "qrcode.react";
import { AlertCircle, Laptop, Loader2, QrCode, RefreshCw, Smartphone } from "lucide-react";

interface HandoffResponse {
  tunnel_url: string;
  code: string;
  expires_in: number;
}

interface PairingResponse {
  pairing_id: string;
  expires_in: number;
}

export default function AccessPage() {
  const { t } = useTranslation();
  const formRef = useRef<HTMLFormElement>(null);
  const [pairing, setPairing] = useState<PairingResponse | null>(null);
  const [timeLeft, setTimeLeft] = useState(0);
  const [loadingPairing, setLoadingPairing] = useState(true);
  const [pairingError, setPairingError] = useState("");
  const [refreshIndex, setRefreshIndex] = useState(0);

  const [handoff, setHandoff] = useState<HandoffResponse | null>(null);
  const [directLoading, setDirectLoading] = useState(false);
  const [directError, setDirectError] = useState("");

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/v1/auth/handoff/pairing", { method: "POST" })
      .then(async (res) => {
        if (!res.ok) throw new Error("pairing request failed");
        const data = (await res.json()) as PairingResponse;
        if (!cancelled) {
          setPairing(data);
          setTimeLeft(data.expires_in);
          setPairingError("");
          setLoadingPairing(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPairingError(t("access.handoffFailed"));
          setLoadingPairing(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [t, refreshIndex]);

  const handleRefreshPairing = () => {
    setLoadingPairing(true);
    setRefreshIndex((prev) => prev + 1);
  };

  useEffect(() => {
    if (timeLeft <= 0) return;
    const timer = setInterval(() => {
      setTimeLeft((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [timeLeft]);

  const handleDirectAccess = () => {
    if (directLoading) return;
    setDirectLoading(true);
    setDirectError("");
    apiFetch("/api/v1/auth/handoff", { method: "POST" })
      .then(async (res) => {
        if (!res.ok) throw new Error("handoff failed");
        const payload = (await res.json()) as HandoffResponse;
        setHandoff(payload);
      })
      .catch(() => {
        setDirectError(t("access.handoffFailed"));
        setDirectLoading(false);
      });
  };

  useEffect(() => {
    if (handoff) formRef.current?.submit();
  }, [handoff]);

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const qrUrl = pairing && origin ? `${origin}/access/device?pairing=${encodeURIComponent(pairing.pairing_id)}` : "";
  const isExpired = timeLeft <= 0 && !loadingPairing;

  return (
    <div className="w-full max-w-md space-y-6">
      <div className="text-center">
        <h1 className="font-serif text-2xl font-semibold text-[var(--foreground)] tracking-tight">
          {t("access.title")}
        </h1>
        <p className="mt-1 text-xs text-[var(--muted-foreground)]">
          {t("access.scanDesc")}
        </p>
      </div>

      <div className="bg-[var(--card)] border border-[var(--border)] rounded-xl shadow-sm p-6 space-y-5">
        <div className="flex items-center justify-between border-b border-[var(--border)] pb-3">
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
            <Smartphone className="w-4 h-4 text-[var(--primary)]" />
            <span>{t("access.scanWithPhone")}</span>
          </div>
          {!loadingPairing && !pairingError && (
            <span className={`text-xs ${isExpired ? "text-red-500 font-medium" : "text-[var(--muted-foreground)]"}`}>
              {isExpired ? t("access.qrExpired") : t("access.qrExpiresIn", { seconds: timeLeft })}
            </span>
          )}
        </div>

        <div className="flex flex-col items-center justify-center py-2">
          {loadingPairing ? (
            <div className="w-48 h-48 flex items-center justify-center bg-[var(--muted)]/20 rounded-lg">
              <Loader2 className="w-8 h-8 animate-spin text-[var(--muted-foreground)]" />
            </div>
          ) : pairingError ? (
            <div className="w-48 h-48 flex flex-col items-center justify-center gap-2 p-4 text-center bg-red-500/10 rounded-lg">
              <AlertCircle className="w-8 h-8 text-red-500" />
              <p className="text-xs text-red-500">{pairingError}</p>
              <button
                type="button"
                onClick={handleRefreshPairing}
                className="mt-2 text-xs font-medium text-[var(--primary)] underline hover:opacity-80"
              >
                {t("access.refreshQr")}
              </button>
            </div>
          ) : isExpired ? (
            <div className="w-48 h-48 flex flex-col items-center justify-center gap-2 p-4 text-center bg-[var(--muted)]/30 rounded-lg">
              <QrCode className="w-8 h-8 text-[var(--muted-foreground)] opacity-50" />
              <p className="text-xs text-[var(--muted-foreground)]">{t("access.qrExpired")}</p>
              <button
                type="button"
                onClick={handleRefreshPairing}
                className="mt-1 flex items-center gap-1.5 px-3 py-1.5 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-md text-xs font-medium hover:opacity-90 transition-opacity"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                {t("access.refreshQr")}
              </button>
            </div>
          ) : (
            <div className="relative group p-3 bg-white rounded-lg shadow-sm border border-neutral-200 dark:border-neutral-700">
              <QRCodeSVG
                value={qrUrl}
                size={180}
                level="M"
                marginSize={1}
                fgColor="#000000"
                bgColor="#ffffff"
              />
            </div>
          )}
        </div>

        <div className="border-t border-[var(--border)] pt-4 space-y-3">
          <button
            type="button"
            onClick={handleDirectAccess}
            disabled={directLoading}
            className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg bg-[var(--secondary)] hover:bg-[var(--secondary)]/80 text-[var(--secondary-foreground)] text-xs font-medium transition-colors disabled:opacity-50"
          >
            {directLoading ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>{t("access.openingOnThisDevice")}</span>
              </>
            ) : (
              <>
                <Laptop className="w-3.5 h-3.5" />
                <span>{t("access.openOnThisDevice")}</span>
              </>
            )}
          </button>
          {directError && <p className="text-xs text-red-500 text-center">{directError}</p>}
        </div>
      </div>

      <div className="text-center">
        <p className="text-xs text-[var(--muted-foreground)]">
          {t("access.securityNote")}
        </p>
      </div>

      {handoff && (
        <form
          ref={formRef}
          method="POST"
          action={`${handoff.tunnel_url}/api/v1/auth/handoff/consume`}
          className="hidden"
        >
          <input type="hidden" name="code" value={handoff.code} />
        </form>
      )}
    </div>
  );
}
