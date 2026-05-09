"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, Bot, Check, ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { LLMSelection } from "@/lib/unified-ws";
import {
  llmSelectionKey,
  sameLLMSelection,
  type LLMOption,
} from "@/lib/llm-options";

function formatContextWindow(value?: number) {
  if (!value) return "";
  if (value >= 1_000_000) return `${Math.round(value / 1_000_000)}M ctx`;
  if (value >= 1_000) return `${Math.round(value / 1_000)}k ctx`;
  return `${value} ctx`;
}

function providerLabel(option: LLMOption) {
  return option.provider || option.profile_name || "LLM";
}

export default function ModelSelector({
  options,
  activeDefault,
  value,
  loading,
  error,
  allowSystemDefault = false,
  systemDefaultLabel,
  systemDefaultDetail,
  helperText,
  placement = "top",
  onChange,
}: {
  options: LLMOption[];
  activeDefault: LLMSelection | null;
  value: LLMSelection | null;
  loading: boolean;
  error: boolean;
  allowSystemDefault?: boolean;
  systemDefaultLabel?: string;
  systemDefaultDetail?: string;
  helperText?: string;
  placement?: "top" | "bottom";
  onChange: (selection: LLMSelection | null) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const selectedSelection = allowSystemDefault
    ? value
    : (value ?? activeDefault);
  const selectedKey = llmSelectionKey(selectedSelection);
  const selectedOption = useMemo(
    () =>
      options.find((option) => sameLLMSelection(option, selectedSelection)) ??
      null,
    [options, selectedSelection],
  );

  useEffect(() => {
    if (!open) return;
    const handler = (event: MouseEvent) => {
      const target = event.target as Node;
      if (rootRef.current && !rootRef.current.contains(target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const defaultLabel = systemDefaultLabel || t("System default");
  const defaultDetail =
    systemDefaultDetail || t("Use the active default model from Settings");
  const disabled =
    loading || error || (options.length === 0 && !allowSystemDefault);
  const label = loading
    ? t("Loading models")
    : error
      ? t("Models unavailable")
      : allowSystemDefault && !selectedSelection
        ? defaultLabel
        : selectedOption?.model_name || t("Select model");
  const detail = (() => {
    if (selectedOption) {
      return `${selectedOption.profile_name} | ${providerLabel(selectedOption)}`;
    }
    if (allowSystemDefault && !selectedSelection) return defaultDetail;
    if (error) return t("Could not load models");
    if (options.length === 0) return t("No configured models");
    return t("Choose a model");
  })();
  const menuPlacementClass =
    placement === "bottom" ? "top-full mt-1.5" : "bottom-full mb-1.5";

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        title={detail}
        aria-label={t("Select model")}
        aria-expanded={open}
        className={`inline-flex h-[28px] max-w-[150px] shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-[11px] font-medium transition-colors sm:max-w-[210px] ${
          disabled
            ? "cursor-not-allowed border-[var(--border)]/25 text-[var(--border)]"
            : open
              ? "border-[var(--primary)]/50 bg-[var(--primary)]/[0.04] text-[var(--foreground)]"
              : "border-[var(--border)]/40 text-[var(--muted-foreground)] hover:border-[var(--border)] hover:text-[var(--foreground)]"
        }`}
      >
        {error ? (
          <AlertCircle size={12} strokeWidth={1.7} className="shrink-0" />
        ) : (
          <Bot size={12} strokeWidth={1.7} className="shrink-0" />
        )}
        <span className="min-w-0 truncate">{label}</span>
        <ChevronDown
          size={10}
          className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && !disabled && (
        <div
          className={`absolute right-0 z-50 ${menuPlacementClass} w-[min(340px,calc(100vw-32px))] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] shadow-lg backdrop-blur-md`}
        >
          <div className="border-b border-[var(--border)]/50 px-3 py-2">
            <div className="text-[12px] font-semibold text-[var(--foreground)]">
              {t("Choose model")}
            </div>
            <div className="mt-0.5 text-[10px] text-[var(--muted-foreground)]">
              {helperText || t("Applies to the next message in this chat")}
            </div>
          </div>
          <div className="max-h-[280px] overflow-y-auto py-1">
            {allowSystemDefault && (
              <button
                type="button"
                onClick={() => {
                  onChange(null);
                  setOpen(false);
                }}
                className={`flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors ${
                  selectedKey === ""
                    ? "bg-[var(--primary)]/[0.06]"
                    : "hover:bg-[var(--muted)]/45"
                }`}
              >
                <div
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border ${
                    selectedKey === ""
                      ? "border-[var(--primary)]/35 bg-[var(--primary)]/10 text-[var(--primary)]"
                      : "border-[var(--border)]/50 bg-[var(--muted)]/25 text-[var(--muted-foreground)]"
                  }`}
                >
                  <Bot size={13} strokeWidth={1.7} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12px] font-medium text-[var(--foreground)]">
                    {defaultLabel}
                  </div>
                  <div className="mt-0.5 truncate text-[10px] text-[var(--muted-foreground)]">
                    {defaultDetail}
                  </div>
                </div>
                {selectedKey === "" && (
                  <Check
                    size={14}
                    strokeWidth={2}
                    className="shrink-0 text-[var(--primary)]"
                  />
                )}
              </button>
            )}
            {options.map((option) => {
              const optionSelection = {
                profile_id: option.profile_id,
                model_id: option.model_id,
              };
              const optionKey = llmSelectionKey(optionSelection);
              const selected = optionKey === selectedKey;
              const contextWindow = formatContextWindow(option.context_window);
              return (
                <button
                  key={optionKey}
                  type="button"
                  onClick={() => {
                    onChange(optionSelection);
                    setOpen(false);
                  }}
                  className={`flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors ${
                    selected
                      ? "bg-[var(--primary)]/[0.06]"
                      : "hover:bg-[var(--muted)]/45"
                  }`}
                >
                  <div
                    className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border ${
                      selected
                        ? "border-[var(--primary)]/35 bg-[var(--primary)]/10 text-[var(--primary)]"
                        : "border-[var(--border)]/50 bg-[var(--muted)]/25 text-[var(--muted-foreground)]"
                    }`}
                  >
                    <Bot size={13} strokeWidth={1.7} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <span className="truncate text-[12px] font-medium text-[var(--foreground)]">
                        {option.model_name || option.model}
                      </span>
                      {option.is_active_default && (
                        <span className="shrink-0 rounded-full bg-[var(--muted)] px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                          {t("Default")}
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 truncate text-[10px] text-[var(--muted-foreground)]">
                      {option.profile_name} | {providerLabel(option)}
                      {contextWindow ? ` | ${contextWindow}` : ""}
                    </div>
                  </div>
                  {selected && (
                    <Check
                      size={14}
                      strokeWidth={2}
                      className="shrink-0 text-[var(--primary)]"
                    />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
