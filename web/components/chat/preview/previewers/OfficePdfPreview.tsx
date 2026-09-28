"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { apiFetch } from "@/lib/api";
import { activeWorkspaceId, scopedUrl } from "@/lib/workspace-scope";
import PdfPreview from "./PdfPreview";

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

type PreviewState =
  | { kind: "loading"; sourceUrl: string }
  | { kind: "ready"; sourceUrl: string; pdfUrl: string }
  | { kind: "fallback"; sourceUrl: string };

/**
 * Use the server's Office layout engine for real page/slide boundaries. A
 * blob or data URL belongs to an unsaved local file, so it is sent directly;
 * served files are resolved by the server from their own allowlisted URL.
 * The original-format renderer remains available if conversion fails.
 */
export default function OfficePdfPreview({
  url,
  filename,
  fallback,
}: {
  url: string;
  filename: string;
  fallback: ReactNode;
}) {
  const { t } = useTranslation();
  const [state, setState] = useState<PreviewState>({
    kind: "loading",
    sourceUrl: url,
  });

  useEffect(() => {
    const controller = new AbortController();
    let pdfUrl: string | null = null;
    setState({ kind: "loading", sourceUrl: url });

    (async () => {
      try {
        let response: Response;
        if (url.startsWith("blob:") || url.startsWith("data:")) {
          const sourceResponse = await apiFetch(url, { signal: controller.signal });
          if (!sourceResponse.ok) throw new Error("Office source unavailable");
          const sourceBlob = await sourceResponse.blob();
          if (!sourceBlob.size || sourceBlob.size > MAX_UPLOAD_BYTES) {
            throw new Error("Office source too large");
          }
          const form = new FormData();
          form.append("file", sourceBlob, filename);
          response = await apiFetch(apiUrlForLocalFile(), {
            method: "POST",
            body: form,
            signal: controller.signal,
          });
        } else {
          const source = new URL(url, window.location.origin);
          if (source.origin !== window.location.origin) {
            throw new Error("Office source is not local");
          }
          const sourcePath = `${source.pathname}${source.search}`;
          const workspaceId =
            source.searchParams.get("dt_workspace") ??
            source.searchParams.get("workspace") ??
            activeWorkspaceId();
          const endpoint = scopedUrl(
            `/api/file-preview/pdf?source=${encodeURIComponent(sourcePath)}`,
            workspaceId,
          );
          response = await apiFetch(endpoint, {
            signal: controller.signal,
            cache: "no-store",
          });
        }
        if (!response.ok || !response.headers.get("content-type")?.includes("application/pdf")) {
          throw new Error("Office conversion unavailable");
        }
        const pdf = await response.blob();
        if (!pdf.size) throw new Error("Office conversion returned an empty PDF");
        if (controller.signal.aborted) return;
        pdfUrl = URL.createObjectURL(pdf);
        setState({ kind: "ready", sourceUrl: url, pdfUrl });
      } catch {
        if (!controller.signal.aborted) {
          setState({ kind: "fallback", sourceUrl: url });
        }
      }
    })();

    return () => {
      controller.abort();
      if (pdfUrl) URL.revokeObjectURL(pdfUrl);
    };
  }, [filename, url]);

  const current = state.sourceUrl === url ? state : { kind: "loading" as const };
  if (current.kind === "ready") {
    return <PdfPreview key={current.pdfUrl} url={current.pdfUrl} filename={filename} />;
  }
  if (current.kind === "fallback") return <>{fallback}</>;
  return (
    <div className="flex h-full items-center justify-center gap-2 bg-[var(--muted)]/30 text-[12px] text-[var(--muted-foreground)]">
      <Loader2 size={14} className="animate-spin" />
      <span>{t("Loading preview…")}</span>
    </div>
  );
}

function apiUrlForLocalFile(): string {
  return scopedUrl("/api/file-preview/pdf");
}
