"use client";

/**
 * Always-expanded model picker for the partner wizard — a plain radio list
 * (system default + every catalog option), no hover-to-expand animation.
 */

import { Check, Loader2 } from "lucide-react";
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

function Row({
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
      className={`flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition-colors ${
        selected
          ? "border-[var(--primary)] bg-[var(--secondary)]"
          : "border-[var(--border)] hover:border-[var(--ring)]"
      }`}
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13.5px] font-medium text-[var(--foreground)]">
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
      <span
        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
          selected
            ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
            : "border-[var(--border)]"
        }`}
      >
        {selected && <Check className="h-3 w-3" strokeWidth={3} />}
      </span>
    </button>
  );
}

export default function PartnerModelPicker({
  options,
  activeDefault,
  value,
  loading,
  error,
  onChange,
}: {
  options: LLMOption[];
  activeDefault: LLMSelection | null;
  value: LLMSelection | null;
  loading: boolean;
  error: boolean;
  onChange: (selection: LLMSelection | null) => void;
}) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-2 text-[13px] text-[var(--muted-foreground)]">
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

  const defaultOption = activeDefault
    ? options.find((option) => sameLLMSelection(option, activeDefault))
    : undefined;
  const defaultDetail = defaultOption
    ? `${defaultOption.model_name || defaultOption.model} · ${defaultOption.provider_label || defaultOption.provider}`
    : undefined;

  return (
    <div className="max-h-[340px] space-y-1.5 overflow-y-auto pr-1">
      <Row
        title={t("System default")}
        subtitle={
          defaultDetail ?? t("Follows whatever the system default model is.")
        }
        selected={value === null}
        onClick={() => onChange(null)}
      />
      {options.map((option) => (
        <Row
          key={llmSelectionKey(option)}
          title={option.model_name || option.model}
          subtitle={`${option.provider_label || option.provider} · ${option.profile_name}`}
          trailing={formatContext(option.context_window)}
          selected={value !== null && sameLLMSelection(option, value)}
          onClick={() =>
            onChange({
              profile_id: option.profile_id,
              model_id: option.model_id,
            })
          }
        />
      ))}
      {options.length === 0 && (
        <p className="py-1 text-[13px] text-[var(--muted-foreground)]">
          {t("No models configured yet — add providers in Settings → LLM.")}
        </p>
      )}
    </div>
  );
}
