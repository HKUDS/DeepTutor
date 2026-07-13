"use client";

/**
 * Click-to-open model dropdown that always shows the full current choice as
 * text (no collapse-to-icon, no hover-expand). Used for the partner's
 * primary/backup model rows; `noneLabel` names the null choice ("System
 * default" for primary, "No backup" for backup).
 */

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  llmSelectionKey,
  sameLLMSelection,
  type LLMOption,
} from "@/lib/llm-options";
import type { LLMSelection } from "@/lib/unified-ws";

function formatContext(tokens?: number): string {
  if (!tokens || tokens <= 0) return "";
  if (tokens >= 1_000_000) return `${Math.round(tokens / 100_000) / 10}M`;
  if (tokens >= 1_000) return `${Math.round(tokens / 1_000)}K`;
  return String(tokens);
}

export default function PartnerModelSelect({
  options,
  activeDefault,
  value,
  loading,
  error,
  noneLabel,
  noneDetail,
  onChange,
}: {
  options: LLMOption[];
  activeDefault: LLMSelection | null;
  value: LLMSelection | null;
  loading: boolean;
  error: boolean;
  noneLabel: string;
  noneDetail?: string;
  onChange: (selection: LLMSelection | null) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-[var(--border)] px-3.5 py-2.5 text-[13.5px] text-[var(--muted-foreground)]">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {t("Loading models…")}
      </div>
    );
  }
  if (error) {
    return (
      <p className="text-[13px] text-[var(--muted-foreground)]">
        {t(
          "Could not load the model catalog — the partner will use the system default.",
        )}
      </p>
    );
  }

  const current = value
    ? options.find((option) => sameLLMSelection(option, value))
    : undefined;
  const defaultOption = activeDefault
    ? options.find((option) => sameLLMSelection(option, activeDefault))
    : undefined;

  const currentTitle = value
    ? current
      ? current.model_name || current.model
      : value.model_id
    : noneLabel;
  const currentSubtitle = value
    ? current
      ? `${current.provider_label || current.provider} · ${current.profile_name}`
      : ""
    : (noneDetail ??
      (defaultOption
        ? `${defaultOption.model_name || defaultOption.model} · ${defaultOption.provider_label || defaultOption.provider}`
        : ""));

  const select = (next: LLMSelection | null) => {
    onChange(next);
    setOpen(false);
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`flex w-full items-center gap-3 rounded-xl border px-3.5 py-2.5 text-left transition-colors ${
          open
            ? "border-[var(--ring)]"
            : "border-[var(--border)] hover:border-[var(--ring)]"
        }`}
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13.5px] font-medium text-[var(--foreground)]">
            {currentTitle}
          </span>
          {currentSubtitle && (
            <span className="block truncate text-[11.5px] text-[var(--muted-foreground)]">
              {currentSubtitle}
            </span>
          )}
        </span>
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-[var(--muted-foreground)] transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open && (
        <div className="absolute left-0 right-0 z-30 mt-1 max-h-[300px] overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--popover)] p-1 shadow-lg">
          <DropdownRow
            title={noneLabel}
            subtitle={noneDetail}
            selected={value === null}
            onClick={() => select(null)}
          />
          {options.map((option) => (
            <DropdownRow
              key={llmSelectionKey(option)}
              title={option.model_name || option.model}
              subtitle={`${option.provider_label || option.provider} · ${option.profile_name}`}
              trailing={formatContext(option.context_window)}
              selected={value !== null && sameLLMSelection(option, value)}
              onClick={() =>
                select({
                  profile_id: option.profile_id,
                  model_id: option.model_id,
                })
              }
            />
          ))}
          {options.length === 0 && (
            <p className="px-3 py-2 text-[13px] text-[var(--muted-foreground)]">
              {t("No models configured yet — add providers in Settings → LLM.")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function DropdownRow({
  title,
  subtitle,
  trailing,
  selected,
  onClick,
}: {
  title: string;
  subtitle?: string;
  trailing?: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors ${
        selected ? "bg-[var(--secondary)]" : "hover:bg-[var(--muted)]"
      }`}
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13.5px] text-[var(--foreground)]">
          {title}
        </span>
        {subtitle && (
          <span className="block truncate text-[11.5px] text-[var(--muted-foreground)]">
            {subtitle}
          </span>
        )}
      </span>
      {trailing && (
        <span className="shrink-0 text-[11.5px] text-[var(--muted-foreground)]">
          {trailing}
        </span>
      )}
      {selected && (
        <Check className="h-3.5 w-3.5 shrink-0 text-[var(--primary)]" />
      )}
    </button>
  );
}
