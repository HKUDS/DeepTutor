"use client";

import {
  Check,
  CircleAlert,
  FileAudio,
  FileText,
  Film,
  Library,
  Loader2,
  StickyNote,
  Youtube,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { type ReadingLibraryMaterial } from "@/lib/reading-workspace-api";
import { readingFailureMessage } from "@/lib/reading-failure";

export function iconForMaterial(material: ReadingLibraryMaterial) {
  if (material.source_kind === "youtube") return Youtube;
  if (material.source_kind === "bilibili") return Film;
  if (material.render_mode === "video") return Film;
  if (material.render_mode === "audio") return FileAudio;
  return FileText;
}

export function MenuItem({
  icon: Icon,
  label,
  onClick,
  disabled,
  hint,
  active,
  spinning,
}: {
  icon: typeof StickyNote;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  /** A second line under the label — why it is disabled, or what it acts on. */
  hint?: string;
  /** A setting that is on. Toggles report it; plain actions leave it unset. */
  active?: boolean;
  spinning?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      role={active === undefined ? undefined : "menuitemcheckbox"}
      aria-checked={active}
      className="flex w-full items-start gap-2 rounded-md px-2.5 py-2 text-left text-[var(--foreground)] transition hover:bg-[var(--muted)] disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-transparent"
    >
      <Icon
        size={13}
        className={`mt-[2px] shrink-0 ${
          active ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]"
        } ${spinning ? "animate-spin" : ""}`}
      />
      <span className="min-w-0 flex-1">
        <span className="block">{label}</span>
        {hint ? (
          <span className="mt-0.5 block text-[10.5px] leading-snug text-[var(--muted-foreground)]">
            {hint}
          </span>
        ) : null}
      </span>
      {active ? (
        <Check size={13} className="mt-[2px] shrink-0 text-[var(--primary)]" />
      ) : null}
    </button>
  );
}

export function CompanionWelcome({ hasMaterial }: { hasMaterial: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="mx-auto flex min-h-full max-w-[290px] flex-col items-center justify-center py-10 text-center">
      <SelectPassageMark />
      <p className="mt-5 font-serif text-[18px] font-medium tracking-[-0.01em] text-[var(--foreground)]">
        {t("Read and ask as you go")}
      </p>
      <p className="mt-2 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
        {hasMaterial
          ? t(
              "Select any passage to ask about it, explain it or translate it — or just ask below. Answers point back to the page they come from.",
            )
          : t("Add material to begin a reading conversation.")}
      </p>
    </div>
  );
}

/**
 * A page with one line picked out — the gesture the panel is waiting for,
 * drawn instead of an icon that stands for "AI". Theme tokens only, so it
 * follows light and dark without a second drawing.
 */
function SelectPassageMark() {
  const line = "fill-[color-mix(in_srgb,var(--muted-foreground)_22%,transparent)]";
  return (
    <svg
      width="64"
      height="72"
      viewBox="0 0 64 72"
      aria-hidden="true"
      className="overflow-visible"
    >
      <rect
        x="8.5"
        y="4.5"
        width="47"
        height="63"
        rx="7"
        className="fill-[var(--card)] stroke-[var(--border)]"
      />
      <rect x="17" y="17" width="30" height="3" rx="1.5" className={line} />
      <rect x="17" y="25" width="26" height="3" rx="1.5" className={line} />
      <rect
        x="14.5"
        y="30.5"
        width="30"
        height="10"
        rx="2.5"
        className="fill-[color-mix(in_srgb,var(--primary)_16%,transparent)]"
      />
      <rect
        x="17"
        y="34"
        width="25"
        height="3"
        rx="1.5"
        className="fill-[var(--primary)]"
      />
      <path
        d="M44.5 29v13"
        strokeWidth="1.5"
        strokeLinecap="round"
        className="stroke-[var(--primary)]"
      />
      <rect x="17" y="46" width="30" height="3" rx="1.5" className={line} />
      <rect x="17" y="54" width="18" height="3" rx="1.5" className={line} />
    </svg>
  );
}

export function EmptyWorkspace({ onAdd }: { onAdd: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <Library size={25} className="text-[var(--primary)]" />
      <p className="mt-3 font-serif text-[18px] font-medium">
        {t("Add material to begin")}
      </p>
      <button
        type="button"
        onClick={onAdd}
        className="mt-5 rounded-xl bg-[var(--primary)] px-4 py-2 text-[11px] font-semibold text-[var(--primary-foreground)]"
      >
        {t("Add material")}
      </button>
    </div>
  );
}

export function MaterialProcessing({
  material,
}: {
  material: ReadingLibraryMaterial;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <Loader2 size={24} className="animate-spin text-[var(--primary)]" />
      <p className="mt-4 font-serif text-[18px] font-medium">
        {t("Preparing {{title}}", { title: material.title })}
      </p>
      <p className="mt-2 text-[10.5px] text-[var(--muted-foreground)]">
        {t("Extracting structure and grounded passages…")} {material.progress}%
      </p>
    </div>
  );
}

export function MaterialFailure({
  material,
  onRetry,
}: {
  material: ReadingLibraryMaterial;
  onRetry: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState("");

  const retry = async () => {
    setRetrying(true);
    setRetryError("");
    try {
      await onRetry();
    } catch (caught) {
      setRetryError(
        caught instanceof Error
          ? caught.message
          : t("Try importing this material again."),
      );
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div className="flex h-full flex-col items-center justify-center px-8 text-center">
      <CircleAlert size={24} className="text-red-600" />
      <p className="mt-4 font-serif text-[18px] font-medium">
        {t("This material could not be prepared")}
      </p>
      <p className="mt-2 max-w-lg text-[10.5px] leading-relaxed text-[var(--muted-foreground)]">
        {readingFailureMessage(material, t) ||
          t("Try importing this material again.")}
      </p>
      {retryError && (
        <p className="mt-2 max-w-lg text-[10.5px] text-red-700">{retryError}</p>
      )}
      <button
        type="button"
        onClick={() => void retry()}
        disabled={retrying}
        className="mt-5 inline-flex h-9 items-center gap-2 rounded-xl bg-[var(--primary)] px-4 text-[11px] font-semibold text-[var(--primary-foreground)] transition hover:opacity-90 disabled:cursor-wait disabled:opacity-60"
      >
        {retrying && <Loader2 size={12} className="animate-spin" />}
        {retrying ? t("Retrying…") : t("Retry")}
      </button>
    </div>
  );
}
