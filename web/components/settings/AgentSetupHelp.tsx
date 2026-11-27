"use client";

import { useState } from "react";
import { Bot, Check, Copy } from "lucide-react";
import { useTranslation } from "react-i18next";
import Modal from "@/components/common/Modal";
import { copyText } from "@/lib/clipboard";

export default function AgentSetupHelp() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [copyState, setCopyState] = useState<"idle" | "copying" | "copied" | "failed">("idle");
  const prompt = t("settings.agentSetup.prompt");

  const copy = async () => {
    setCopyState("copying");
    try {
      await copyText(prompt);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  };

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)]/50 py-4">
        <p className="text-[13px] leading-relaxed text-[var(--muted-foreground)]">
          {t("settings.agentSetup.description")}
        </p>
        <button
          type="button"
          onClick={() => {
            setCopyState("idle");
            setOpen(true);
          }}
          className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-[13px] font-medium hover:bg-[var(--muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
        >
          <Bot size={16} aria-hidden="true" />
          {t("settings.agentSetup.title")}
        </button>
      </div>
      <Modal
        isOpen={open}
        onClose={() => setOpen(false)}
        title={t("settings.agentSetup.title")}
        width="lg"
        footer={
          <div className="flex flex-wrap items-center justify-end gap-3">
            <p role="status" className="text-xs text-[var(--muted-foreground)]">
              {copyState === "failed" ? t("settings.agentSetup.copyFailed") : copyState === "copied" ? t("Copied") : ""}
            </p>
            <button
              type="button"
              onClick={() => void copy()}
              disabled={copyState === "copying"}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--foreground)] px-4 py-2 text-sm font-medium text-[var(--background)] disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2"
            >
              {copyState === "copied" ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
              {t("settings.agentSetup.copy")}
            </button>
          </div>
        }
      >
        <div className="space-y-4 p-5">
          <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">
            {t("settings.agentSetup.instructions")}
          </p>
          <textarea
            readOnly
            data-autofocus
            aria-label={t("settings.agentSetup.title")}
            value={prompt}
            onFocus={(event) => event.currentTarget.select()}
            className="h-72 w-full resize-y rounded-lg border border-[var(--border)] bg-[var(--background)] p-3 text-sm leading-relaxed text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
          />
        </div>
      </Modal>
    </>
  );
}
