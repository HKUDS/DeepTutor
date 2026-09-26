"use client";

import {
  CheckCircle2,
  FileText,
  LoaderCircle,
  TriangleAlert,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type {
  AttachmentProcessingItem,
  AttachmentProcessingPhase,
} from "@/features/chat/selectors/attachment-processing";

function phaseLabel(
  phase: AttachmentProcessingPhase,
  t: (key: string) => string,
): string {
  switch (phase) {
    case "received":
      return t("Uploaded to DeepTutor");
    case "submitting":
      return t("Sending to document parser");
    case "parsing":
      return t("Document parser is processing");
    case "retrieving":
      return t("Retrieving parsed result");
    case "completed":
      return t("Ready for this answer");
    case "fallback":
      return t("Using local PDF text");
    case "failed":
      return t("Document parsing failed");
  }
}

function PhaseIcon({ phase }: { phase: AttachmentProcessingPhase }) {
  if (phase === "completed") {
    return <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />;
  }
  if (phase === "failed" || phase === "fallback") {
    return <TriangleAlert className="h-3.5 w-3.5 text-amber-600" />;
  }
  return (
    <LoaderCircle className="h-3.5 w-3.5 animate-spin text-[var(--primary)]" />
  );
}

export default function AttachmentProcessingStatus({
  items,
}: {
  items: AttachmentProcessingItem[];
}) {
  const { t } = useTranslation();
  if (!items.length) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={t("Attachment processing")}
      className="mx-3 mb-2 space-y-1 rounded-xl border border-[var(--border)]/70 bg-[var(--muted)]/30 px-3 py-2"
    >
      {items.map((item) => {
        const hasDetails =
          (item.phase === "failed" || item.phase === "fallback") &&
          item.detail;
        return (
          <div key={item.attachmentId} className="text-[11px]">
            <div className="flex min-w-0 items-center gap-2">
              <span className="shrink-0" aria-hidden="true">
                <PhaseIcon phase={item.phase} />
              </span>
              <FileText
                className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]"
                aria-hidden="true"
              />
              <span className="min-w-0 flex-1 truncate font-medium text-[var(--foreground)]">
                {item.filename}
              </span>
              <span className="shrink-0 text-[var(--muted-foreground)]">
                {phaseLabel(item.phase, t)}
              </span>
            </div>
            {hasDetails ? (
              <details className="ml-9 mt-1 text-[var(--muted-foreground)]">
                <summary className="cursor-pointer select-none">
                  {t("Failure details")}
                </summary>
                <p className="mt-1 break-words">{item.detail}</p>
              </details>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
