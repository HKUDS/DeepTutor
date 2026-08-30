"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, Bot, Brain, Check, ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLingerExpand } from "@/hooks/use-linger-expand";
import ProviderIcon from "@/components/common/ProviderIcon";
import type { LLMSelection } from "@/lib/unified-ws";
import {
  llmSelectionKey,
  sameLLMSelection,
  withLLMReasoningEffort,
  type LLMOption,
} from "@/lib/llm-options";
import { conversationReasoningEffortOptions } from "@/lib/reasoning-effort";

function formatContextWindow(value?: number) {
  if (!value) return "";
  if (value >= 1_000_000) return `${Math.round(value / 1_000_000)}M ctx`;
  if (value >= 1_000) return `${Math.round(value / 1_000)}k ctx`;
  return `${value} ctx`;
}

function providerLabel(option: LLMOption) {
  return (
    option.provider_label || option.provider || option.profile_name || "LLM"
  );
}

function ModelOptionRow({
  option,
  selected,
  onSelect,
}: {
  option: LLMOption;
  selected: boolean;
  onSelect: () => void;
}) {
  const { t } = useTranslation();
  // Official model ID as the primary label (what gets sent to the API),
  // per design. The user-given nickname and profile live in the tooltip.
  const modelLabel = option.model || option.model_name;
  const contextWindow = formatContextWindow(option.context_window);
  // Long model ids ("google/gemini-3-flash-preview") get ellipsized by the
  // inline layout; hovering the row reveals the full id as an overlay. The
  // scrollWidth check at mouseenter time keeps the overlay away from rows
  // that aren't actually truncated.
  const nameRef = useRef<HTMLSpanElement>(null);
  const [revealFull, setRevealFull] = useState(false);
  return (
    <button
      type="button"
      title={`${option.model_name} | ${option.profile_name}`}
      onClick={onSelect}
      onMouseEnter={() => {
        const el = nameRef.current;
        setRevealFull(!!el && el.scrollWidth > el.clientWidth + 1);
      }}
      onMouseLeave={() => setRevealFull(false)}
      className={`relative flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors active:bg-[var(--muted)]/70 ${
        selected ? "bg-[var(--primary)]/[0.06]" : "hover:bg-[var(--muted)]/45"
      }`}
    >
      <ProviderIcon
        provider={option.provider}
        size={14}
        className={
          selected ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]"
        }
      />
      <span
        ref={nameRef}
        className="min-w-0 truncate text-[12.5px] font-medium text-[var(--foreground)]"
      >
        {modelLabel}
      </span>
      {option.is_active_default && (
        <span className="shrink-0 rounded-full bg-[var(--muted)] px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("Default")}
        </span>
      )}
      <span className="min-w-0 flex-1 truncate text-[11px] text-[var(--muted-foreground)]">
        {providerLabel(option)}
      </span>
      {contextWindow ? (
        <span className="shrink-0 text-[11px] text-[var(--muted-foreground)]">
          {contextWindow}
        </span>
      ) : null}
      {selected && (
        <Check
          size={14}
          strokeWidth={2}
          className="shrink-0 text-[var(--primary)]"
        />
      )}
      {revealFull && (
        <span className="pointer-events-none absolute inset-x-1.5 top-1/2 z-10 -translate-y-1/2 break-all rounded-lg border border-[var(--border)] bg-[var(--popover)] px-2 py-1 text-[12px] font-medium text-[var(--foreground)] shadow-md">
          {modelLabel}
        </span>
      )}
    </button>
  );
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
  onRefresh,
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
  onRefresh?: () => void;
}) {
  const { t } = useTranslation();
  const [modelOpen, setModelOpen] = useState(false);
  const [reasoningOpen, setReasoningOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const { expanded, linger, triggerProps: lingerProps } = useLingerExpand(
    modelOpen || reasoningOpen,
  );

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
  const selectedEffort = selectedSelection?.reasoning_effort?.trim() || "";
  const reasoningOptions = selectedOption
    ? conversationReasoningEffortOptions(
        selectedOption.provider,
        selectedOption.model,
        selectedEffort,
        selectedOption.supported_reasoning_levels,
      )
    : [];
  const selectedReasoningOption =
    reasoningOptions.find((option) => option.value === selectedEffort) ?? null;
  const showReasoningSelector = Boolean(
    selectedOption && reasoningOptions.length > 0,
  );

  useEffect(() => {
    if (!modelOpen && !reasoningOpen) return;
    const handler = (event: MouseEvent) => {
      const target = event.target as Node;
      if (rootRef.current && !rootRef.current.contains(target)) {
        setModelOpen(false);
        setReasoningOpen(false);
        linger();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [modelOpen, reasoningOpen, linger]);

  const defaultLabel = systemDefaultLabel || t("System default");
  const defaultDetail =
    systemDefaultDetail || t("Use the active default model from Settings");
  const canRefresh = error && Boolean(onRefresh);
  const disabled =
    loading ||
    (!canRefresh && (error || (options.length === 0 && !allowSystemDefault)));
  const label = loading
    ? t("Loading models")
    : error
      ? canRefresh
        ? t("Refresh models")
        : t("Models unavailable")
      : allowSystemDefault && !selectedSelection
        ? defaultLabel
        : // Official model ID, consistent with the dropdown rows.
          selectedOption?.model ||
          selectedOption?.model_name ||
          t("Select model");
  const menuPlacementClass =
    placement === "bottom" ? "top-full mt-1.5" : "bottom-full mb-1.5";

  return (
    <div ref={rootRef} className="relative flex shrink-0 items-center gap-1">
      {/* Same resting/expanded treatment as PersonaSelector: the brand
          icon is the whole control at rest; hovering (or opening) slides
          the model name out with a max-width animation and lingers ~1.2s
          after leave/selection before collapsing. */}
      <button
        type="button"
        disabled={disabled}
        onClick={() => {
          if (canRefresh) {
            setModelOpen(false);
            setReasoningOpen(false);
            onRefresh?.();
            return;
          }
          setReasoningOpen(false);
          setModelOpen((current) => !current);
        }}
        aria-label={canRefresh ? t("Refresh models") : t("Select model")}
        title={canRefresh ? t("Refresh models") : undefined}
        aria-expanded={modelOpen}
        {...lingerProps}
        className={`inline-flex h-8 shrink-0 items-center rounded-lg px-2 text-[14px] font-medium transition-[background-color,color,transform] duration-150 active:scale-[0.97] ${
          disabled
            ? "cursor-not-allowed text-[var(--border)]"
            : modelOpen
              ? "bg-[var(--muted)] text-[var(--foreground)]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
        }`}
      >
        {error ? (
          <AlertCircle size={16} strokeWidth={1.7} className="shrink-0" />
        ) : (
          <ProviderIcon provider={selectedOption?.provider} size={16} />
        )}
        <span
          className={`flex min-w-0 items-center gap-1 overflow-hidden whitespace-nowrap transition-[max-width,opacity,margin-left] duration-300 ease-out ${
            expanded
              ? "ml-1.5 max-w-[180px] opacity-100"
              : "ml-0 max-w-0 opacity-0"
          }`}
        >
          <span className="min-w-0 truncate">{label}</span>
          <ChevronDown
            size={13}
            className={`shrink-0 transition-transform ${modelOpen ? "rotate-180" : ""}`}
          />
        </span>
      </button>
      {showReasoningSelector ? (
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            setModelOpen(false);
            setReasoningOpen((current) => !current);
          }}
          aria-label={t("Select reasoning effort")}
          title={t("Select reasoning effort")}
          aria-expanded={reasoningOpen}
          {...lingerProps}
          className={`inline-flex h-8 w-[86px] shrink-0 items-center justify-between gap-1 rounded-lg px-2 text-[14px] font-medium transition-[background-color,color,transform] duration-150 active:scale-[0.97] ${
            disabled
              ? "cursor-not-allowed text-[var(--border)]"
              : reasoningOpen
              ? "bg-[var(--muted)] text-[var(--foreground)]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
          }`}
        >
          <span className="flex min-w-0 items-center gap-1">
            <Brain size={16} strokeWidth={1.7} className="shrink-0" />
            <span className="min-w-0 truncate text-[12.5px]">
              {selectedEffort
                ? t(selectedReasoningOption?.label ?? selectedEffort)
                : t("Auto")}
            </span>
          </span>
          <ChevronDown
            size={13}
            className={`shrink-0 transition-transform ${reasoningOpen ? "rotate-180" : ""}`}
          />
        </button>
      ) : null}

      {modelOpen && !disabled && (
        <div
          className={`absolute right-0 z-50 ${menuPlacementClass} w-[min(280px,calc(100vw-32px))] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] shadow-lg backdrop-blur-md`}
        >
          {helperText ? (
            <div className="border-b border-[var(--border)]/50 px-3 py-1.5 text-[11px] text-[var(--muted-foreground)]">
              {helperText}
            </div>
          ) : null}
          <div className="max-h-[280px] overflow-y-auto py-1">
            {allowSystemDefault && (
              <button
                type="button"
                title={defaultDetail}
                onClick={() => {
                  onChange(null);
                  setModelOpen(false);
                  setReasoningOpen(false);
                  linger();
                }}
                className={`flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors active:bg-[var(--muted)]/70 ${
                  selectedKey === ""
                    ? "bg-[var(--primary)]/[0.06]"
                    : "hover:bg-[var(--muted)]/45"
                }`}
              >
                <Bot
                  size={14}
                  strokeWidth={1.7}
                  className={`shrink-0 ${
                    selectedKey === ""
                      ? "text-[var(--primary)]"
                      : "text-[var(--muted-foreground)]"
                  }`}
                />
                <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-[var(--foreground)]">
                  {defaultLabel}
                </span>
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
              return (
                <ModelOptionRow
                  key={optionKey}
                  option={option}
                  selected={optionKey === selectedKey}
                  onSelect={() => {
                    onChange(optionSelection);
                    setModelOpen(false);
                    setReasoningOpen(false);
                    linger();
                  }}
                />
              );
            })}
          </div>
        </div>
      )}

      {showReasoningSelector && reasoningOpen && !disabled && (
        <div
          className={`absolute right-0 z-50 ${menuPlacementClass} w-[min(230px,calc(100vw-32px))] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] shadow-lg backdrop-blur-md`}
        >
          <div className="px-3 py-1.5 text-[11px] text-[var(--muted-foreground)]">
            {t("Applies to this conversation until changed")}
          </div>
          <div className="max-h-[240px] overflow-y-auto py-1">
            {reasoningOptions.map((option) => {
              const selected = option.value === selectedEffort;
              return (
                <button
                  type="button"
                  key={option.value || "auto"}
                  onClick={() => {
                    onChange(withLLMReasoningEffort(selectedSelection, option.value));
                    setReasoningOpen(false);
                    linger();
                  }}
                  className={`flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors active:bg-[var(--muted)]/70 ${
                    selected
                      ? "bg-[var(--primary)]/[0.06]"
                      : "hover:bg-[var(--muted)]/45"
                  }`}
                >
                  <Brain
                    size={14}
                    strokeWidth={1.7}
                    className={`shrink-0 ${
                      selected
                        ? "text-[var(--primary)]"
                        : "text-[var(--muted-foreground)]"
                    }`}
                  />
                  <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-[var(--foreground)]">
                    {t(option.label)}
                  </span>
                  {selected ? (
                    <Check
                      size={14}
                      strokeWidth={2}
                      className="shrink-0 text-[var(--primary)]"
                    />
                  ) : null}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
