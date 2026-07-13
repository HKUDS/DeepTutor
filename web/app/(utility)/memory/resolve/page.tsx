"use client";

// Resolver landing page for ``m_<ULID>`` citations clicked from an L3
// doc. The id alone is not enough to navigate — we need to know which
// L2 surface owns it. The backend resolver does the lookup; this page
// is just the redirect shim.

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { apiFetch, apiUrl } from "@/lib/api";

interface ResolveResponse {
  layer: string;
  key: string;
  entry_id: string;
}

function ResolveInner() {
  const { t } = useTranslation();
  const params = useSearchParams();
  const router = useRouter();
  const id = params.get("id");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(
          apiUrl(`/api/v1/memory/resolve_entry/${encodeURIComponent(id)}`),
        );
        if (!res.ok) {
          if (cancelled) return;
          setError(
            res.status === 404
              ? t(
                  "Entry {{id}} not found in any L2 doc — it may have been deleted.",
                  { id },
                )
              : t("Resolver failed ({{code}})", { code: res.status }),
          );
          return;
        }
        const data = (await res.json()) as ResolveResponse;
        if (cancelled) return;
        const layerPath = data.layer.toLowerCase();
        router.replace(
          `/memory/${layerPath}/${encodeURIComponent(data.key)}?focus=${encodeURIComponent(data.entry_id)}`,
        );
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : t("Resolver failed"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, router, t]);

  const message = !id ? t("Missing ?id= in URL") : error;

  if (message) {
    return (
      <div className="grid h-full place-items-center px-6 py-10">
        <div className="max-w-md space-y-3 text-center text-[13px]">
          <p className="text-[var(--foreground)]">{message}</p>
          <Link
            href="/memory"
            className="inline-block rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-1 text-[12px] transition hover:bg-[var(--muted)]"
          >
            {t("Back to memory")}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="grid h-full place-items-center px-6 py-10 text-[var(--muted-foreground)]">
      <div className="flex items-center gap-2 text-[13px]">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span>{t("Resolving entry…")}</span>
      </div>
    </div>
  );
}

export default function MemoryResolvePage() {
  return (
    <Suspense
      fallback={
        <div className="grid h-full place-items-center text-[var(--muted-foreground)]">
          <Loader2 className="h-4 w-4 animate-spin" />
        </div>
      }
    >
      <ResolveInner />
    </Suspense>
  );
}
