"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useTranslation } from "react-i18next";

interface HandoffResponse {
  tunnel_url: string;
  code: string;
  expires_in: number;
}

export default function AccessPage() {
  const { t } = useTranslation();
  const formRef = useRef<HTMLFormElement>(null);
  const [handoff, setHandoff] = useState<HandoffResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/v1/auth/handoff", { method: "POST" })
      .then(async (response) => {
        if (!response.ok) throw new Error("handoff failed");
        const payload = (await response.json()) as HandoffResponse;
        if (!cancelled) setHandoff(payload);
      })
      .catch(() => {
        if (!cancelled) setError(t("access.handoffFailed"));
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  useEffect(() => {
    if (handoff) formRef.current?.submit();
  }, [handoff]);

  return (
    <div className="w-full max-w-sm">
      <div className="text-center mb-8">
        <h1 className="font-serif text-2xl font-semibold text-[var(--foreground)] tracking-tight">
          {t("access.title")}
        </h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          {handoff ? t("access.redirecting") : t("access.preparing")}
        </p>
      </div>

      <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg shadow-sm px-6 py-6 text-sm text-[var(--muted-foreground)]">
        {error ? (
          <p className="text-red-500">{error}</p>
        ) : (
          <p>{t("access.securityNote")}</p>
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
