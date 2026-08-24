"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { useTranslation } from "react-i18next";

type WhisperRoomChipProps = {
  roomId: string;
};

export default function WhisperRoomChip({ roomId }: WhisperRoomChipProps) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  async function copyRoomId() {
    try {
      await navigator.clipboard.writeText(roomId);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard may be denied; leave chip usable without toast noise.
    }
  }

  return (
    <div className="flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1 text-xs text-[var(--muted-foreground)]">
      <span className="font-medium text-[var(--foreground)]">{t("room")}</span>
      <code className="max-w-[12rem] truncate font-mono text-[11px] text-[var(--foreground)]">
        {roomId}
      </code>
      <button
        type="button"
        onClick={() => void copyRoomId()}
        className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--card)] hover:text-[var(--foreground)]"
        aria-label={t("Copy room id")}
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-emerald-500" />
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
        <span>{copied ? t("Copied") : t("Copy")}</span>
      </button>
    </div>
  );
}
