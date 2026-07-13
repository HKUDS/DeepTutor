"use client";

import { Compass } from "lucide-react";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useGeogebraTabOpener } from "@/context/GeogebraTabContext";

interface GeogebraOpenCTAProps {
  /** Raw ggbscript body. */
  script: string;
  /** Stable id from the ```ggbscript[id;title] fence — used for tab dedupe. */
  payloadId?: string;
  /** Title to show on the CTA + the resulting tab. */
  title?: string;
  className?: string;
}

/**
 * Card-style CTA shown in-place of a ```ggbscript fence in chat answers.
 * Clicking expands the right-hand SessionViewerPanel and opens (or
 * focuses) a GeoGebra tab carrying this script.
 *
 * When no GeogebraTabProvider is mounted (e.g. preview surfaces), the
 * button is disabled with a tooltip — we don't want a click to silently
 * no-op.
 */
export default function GeogebraOpenCTA({
  script,
  payloadId,
  title,
  className = "",
}: GeogebraOpenCTAProps) {
  const { t } = useTranslation();
  const controller = useGeogebraTabOpener();

  // A stable id keyed on the script content. This makes the tab dedupe
  // robust even if the assistant doesn't bother emitting an explicit
  // page_id in the fence info (older outputs).
  const id = useMemo(() => {
    if (payloadId) return payloadId;
    let hash = 0;
    for (let i = 0; i < script.length; i += 1) {
      hash = (hash * 31 + script.charCodeAt(i)) | 0;
    }
    return `script-${(hash >>> 0).toString(36)}`;
  }, [payloadId, script]);

  const onClick = useCallback(() => {
    if (!controller) return;
    controller.openTab({ id, title: title || t("GeoGebra figure"), script });
  }, [controller, id, script, t, title]);

  const disabled = !controller;

  return (
    <div className={`my-3 ${className}`}>
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        title={
          disabled
            ? t("GeoGebra viewer is not available in this surface")
            : undefined
        }
        className={`group flex w-full items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-left transition-colors ${
          disabled
            ? "cursor-not-allowed opacity-60"
            : "hover:border-[var(--primary)]/60 hover:bg-[var(--muted)]/30"
        }`}
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--primary)]/10 text-[var(--primary)]">
          <Compass size={18} strokeWidth={1.9} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-[var(--foreground)]">
            {title || t("Interactive GeoGebra figure")}
          </span>
          <span className="block text-xs text-[var(--muted-foreground)]">
            {t(
              "Click to open an interactive GeoGebra canvas in the side viewer.",
            )}
          </span>
        </span>
      </button>
    </div>
  );
}
