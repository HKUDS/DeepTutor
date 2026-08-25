"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { AlertCircle, Loader2, Smartphone } from "lucide-react";

interface HandoffResponse {
  tunnel_url: string;
  code: string;
  expires_in: number;
}

function DeviceAccessContent() {
  const { t } = useTranslation();
  const searchParams = useSearchParams();
  const pairingId = searchParams.get("pairing");
  const formRef = useRef<HTMLFormElement>(null);
  const [handoff, setHandoff] = useState<HandoffResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!pairingId) return;

    let cancelled = false;
    fetch(`/api/v1/auth/handoff/pairing/${encodeURIComponent(pairingId)}`, {
      method: "GET",
      headers: { "Cache-Control": "no-store" },
    })
      .then(async (res) => {
        if (!res.ok) throw new Error("pairing exchange failed");
        const data = (await res.json()) as HandoffResponse;
        if (!cancelled) setHandoff(data);
      })
      .catch(() => {
        if (!cancelled) setError(t("access.deviceFailed"));
      });

    return () => {
      cancelled = true;
    };
  }, [pairingId, t]);

  useEffect(() => {
    if (handoff) formRef.current?.submit();
  }, [handoff]);

  const displayError = !pairingId ? t("access.deviceFailed") : error;

  return (
    <div className="w-full max-w-sm space-y-6">
      <div className="text-center">
        <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[var(--primary)]/10 text-[var(--primary)] mb-3">
          <Smartphone className="w-6 h-6" />
        </div>
        <h1 className="font-serif text-2xl font-semibold text-[var(--foreground)] tracking-tight">
          {t("access.deviceTitle")}
        </h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          {displayError ? "" : handoff ? t("access.deviceRedirecting") : t("access.deviceAuthenticating")}
        </p>
      </div>

      <div className="bg-[var(--card)] border border-[var(--border)] rounded-xl shadow-sm p-6 text-center">
        {displayError ? (
          <div className="flex flex-col items-center justify-center gap-2 py-2">
            <AlertCircle className="w-8 h-8 text-red-500" />
            <p className="text-sm text-red-500 font-medium">{displayError}</p>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center gap-3 py-4">
            <Loader2 className="w-8 h-8 animate-spin text-[var(--primary)]" />
            <p className="text-xs text-[var(--muted-foreground)]">
              {t("access.securityNote")}
            </p>
          </div>
        )}
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

export default function DeviceAccessPage() {
  return (
    <Suspense
      fallback={
        <div className="w-full max-w-sm flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-[var(--muted-foreground)]" />
        </div>
      }
    >
      <DeviceAccessContent />
    </Suspense>
  );
}
