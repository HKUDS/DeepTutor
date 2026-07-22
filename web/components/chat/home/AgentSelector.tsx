"use client";

import { useEffect, useRef, useState } from "react";
import { Bot, Check, ChevronDown, Minus, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { agentGlyph } from "@/components/agents/agent-icons";
import { useLingerExpand } from "@/hooks/use-linger-expand";

const BUDGET_MIN = 1;
const BUDGET_MAX = 12;

/**
 * Connected-agent selector (composer toolbar).
 *
 * Sibling of KnowledgeSelector, but single-select: a turn consults at most one
 * connected agent (Claude Code / Codex). Picking one routes the whole turn
 * through the subagent capability — the chat model consults the live local
 * agent instead of retrieving from a KB. Selecting the active one again clears
 * it. A selection tints the bot icon primary so the active agent stays visible
 * when collapsed.
 */
export default function AgentSelector({
  agents,
  selected,
  onSelect,
  budget = null,
  onBudgetChange,
  placement = "top",
}: {
  agents: { name: string; kind?: string }[];
  selected: string | null;
  onSelect: (name: string | null) => void;
  /** Max times DeepTutor may consult the agent this turn. */
  budget?: number | null;
  onBudgetChange?: (budget: number) => void;
  placement?: "top" | "bottom";
}) {
  const { t } = useTranslation();
  const [open, setOpenState] = useState(false);
  const { expanded, linger, triggerProps: lingerProps } = useLingerExpand(open);
  const setOpen = (next: boolean) => {
    setOpenState(next);
    if (!next) linger();
  };
  const rootRef = useRef<HTMLDivElement>(null);

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const label = selected ?? t("Agent");
  const menuPlacementClass =
    placement === "bottom" ? "top-full mt-1.5" : "bottom-full mb-1.5";
  const SelectedGlyph = agentGlyph(
    agents.find((a) => a.name === selected)?.kind,
  );

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-label={t("Select a connected agent")}
        aria-expanded={open}
        {...lingerProps}
        className={`inline-flex h-8 shrink-0 items-center rounded-lg px-2 text-[14px] font-medium transition-[background-color,color,transform] duration-150 active:scale-[0.97] ${
          open
            ? "bg-[var(--muted)] text-[var(--foreground)]"
            : selected
              ? "text-[var(--primary)] hover:bg-[var(--primary)]/[0.07]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
        }`}
      >
        {SelectedGlyph ? (
          <SelectedGlyph size={16} className="shrink-0" />
        ) : (
          <Bot size={16} strokeWidth={1.7} className="shrink-0" />
        )}
        <span
          className={`flex min-w-0 items-center gap-1 overflow-hidden whitespace-nowrap transition-[max-width,opacity,margin-left] duration-300 ease-out ${
            expanded
              ? "ml-1.5 max-w-[160px] opacity-100"
              : "ml-0 max-w-0 opacity-0"
          }`}
        >
          <span className="min-w-0 truncate">{label}</span>
          <ChevronDown
            size={13}
            className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
          />
        </span>
      </button>

      {open && (
        <div
          className={`dt-popup-up absolute right-0 z-50 ${menuPlacementClass} w-[min(280px,calc(100vw-32px))] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] shadow-lg backdrop-blur-md`}
        >
          <div className="max-h-[280px] overflow-y-auto py-1">
            {agents.map((agent) => {
              const active = selected === agent.name;
              const RowGlyph = agentGlyph(agent.kind) ?? Bot;
              return (
                <button
                  key={agent.name}
                  type="button"
                  onClick={() => {
                    onSelect(active ? null : agent.name);
                    setOpen(false);
                  }}
                  className={`flex w-full items-center gap-2.5 px-3 py-1.5 text-left transition-colors active:bg-[var(--muted)]/70 ${
                    active
                      ? "bg-[var(--primary)]/[0.06]"
                      : "hover:bg-[var(--muted)]/45"
                  }`}
                >
                  <RowGlyph size={15} className="shrink-0" />
                  <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-[var(--foreground)]">
                    {agent.name}
                  </span>
                  {active && (
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

          {onBudgetChange && (
            <div className="flex items-center justify-between gap-2 border-t border-[var(--border)] px-3 py-2">
              <span className="min-w-0 text-[11.5px] text-[var(--muted-foreground)]">
                {t("Max rounds DeepTutor may ask")}
              </span>
              <div className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  aria-label={t("Fewer rounds")}
                  disabled={(budget ?? BUDGET_MIN) <= BUDGET_MIN}
                  onClick={() =>
                    onBudgetChange(
                      Math.max(BUDGET_MIN, (budget ?? BUDGET_MIN) - 1),
                    )
                  }
                  className="flex h-5 w-5 items-center justify-center rounded-md text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)] disabled:opacity-40"
                >
                  <Minus size={12} />
                </button>
                <span className="w-5 text-center text-[12.5px] font-semibold tabular-nums text-[var(--foreground)]">
                  {budget ?? "–"}
                </span>
                <button
                  type="button"
                  aria-label={t("More rounds")}
                  disabled={(budget ?? BUDGET_MAX) >= BUDGET_MAX}
                  onClick={() =>
                    onBudgetChange(
                      Math.min(BUDGET_MAX, (budget ?? BUDGET_MIN) + 1),
                    )
                  }
                  className="flex h-5 w-5 items-center justify-center rounded-md text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)] disabled:opacity-40"
                >
                  <Plus size={12} />
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
