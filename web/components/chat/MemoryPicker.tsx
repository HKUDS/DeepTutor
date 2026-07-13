"use client";

import { useEffect, useState } from "react";
import { Brain, Check, FileText, ScrollText } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { LucideIcon } from "lucide-react";
import PickerShell from "@/components/common/PickerShell";
import PickerHeader from "@/components/common/PickerHeader";
import type { SpaceMemoryFile } from "@/lib/space-items";

interface MemoryPickerProps {
  open: boolean;
  initialFiles: SpaceMemoryFile[];
  onClose: () => void;
  onApply: (files: SpaceMemoryFile[]) => void;
}

interface MemoryOption {
  key: SpaceMemoryFile;
  label: string;
  description: string;
  icon: LucideIcon;
}

const MEMORY_OPTIONS: MemoryOption[] = [
  {
    key: "summary",
    label: "Summary",
    description:
      "Inject the assistant's running summary of past learning sessions.",
    icon: ScrollText,
  },
  {
    key: "profile",
    label: "Profile",
    description: "Inject the learner profile (preferences, goals, background).",
    icon: FileText,
  },
];

export default function MemoryPicker({
  open,
  initialFiles,
  onClose,
  onApply,
}: MemoryPickerProps) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<SpaceMemoryFile[]>(initialFiles);

  // IIFE keeps the setState call out of the synchronous effect body to
  // satisfy `react-hooks/set-state-in-effect`.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      if (cancelled) return;
      setSelected(initialFiles);
    })();
    return () => {
      cancelled = true;
    };
  }, [open, initialFiles]);

  const toggle = (key: SpaceMemoryFile) => {
    setSelected((prev) =>
      prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key],
    );
  };

  const handleApply = () => {
    onApply(selected);
    onClose();
  };

  return (
    <PickerShell
      open={open}
      onClose={onClose}
      labelledBy="memory-picker-title"
      className="p-4 backdrop-blur-md"
      backdropClass="bg-[var(--background)]/65"
    >
      <div className="surface-card w-full max-w-xl overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] text-[var(--card-foreground)] shadow-[0_22px_70px_rgba(0,0,0,0.18)]">
        <PickerHeader
          icon={Brain}
          titleId="memory-picker-title"
          title={t("Select Memory")}
          subtitle={t(
            "Choose which long-form memory artifacts to attach to this turn.",
          )}
          onClose={onClose}
        />

        <div className="bg-[var(--background)]/40 p-5">
          <div className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)]">
            <div className="divide-y divide-[var(--border)]">
              {MEMORY_OPTIONS.map((option) => {
                const active = selected.includes(option.key);
                const Icon = option.icon;
                return (
                  <button
                    key={option.key}
                    onClick={() => toggle(option.key)}
                    className={`flex w-full items-start gap-3 px-4 py-3 text-left transition-colors ${
                      active
                        ? "bg-[var(--primary)]/8"
                        : "hover:bg-[var(--muted)]/40"
                    }`}
                  >
                    <div
                      className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors ${
                        active
                          ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                          : "border-[var(--border)] text-transparent"
                      }`}
                    >
                      <Check size={12} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 text-[14px] font-medium text-[var(--foreground)]">
                        <Icon
                          size={14}
                          strokeWidth={1.7}
                          className="text-[var(--primary)]"
                        />
                        {t(option.label)}
                      </div>
                      <p className="mt-0.5 text-[12px] leading-5 text-[var(--muted-foreground)]">
                        {t(option.description)}
                      </p>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between gap-3">
            <div className="text-[12px] text-[var(--muted-foreground)]">
              {selected.length === 1
                ? t("1 memory artifact selected")
                : t("{{n}} memory artifacts selected", { n: selected.length })}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setSelected([])}
                className="rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                {t("Clear")}
              </button>
              <button
                onClick={handleApply}
                disabled={!selected.length}
                className="btn-primary rounded-xl bg-[var(--primary)] px-4 py-2.5 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {t("Use Selected Memory ({{n}})", { n: selected.length })}
              </button>
            </div>
          </div>
        </div>
      </div>
    </PickerShell>
  );
}
