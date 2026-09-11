"use client";

import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  listDiscussionModes,
  type DiscussionMode,
} from "@/lib/partner-groups-api";

/**
 * How the group talks.
 *
 * The backend's own label/description are written for the model, so the copy
 * here is the product's: what actually happens, plus how long it takes —
 * a group turn costs one model call per member, and the modes differ by a
 * factor of two in both calls and waiting. Hiding that behind a bare name
 * would let someone pick "debate" without knowing they doubled the wait.
 *
 * Unknown modes fall back to the server's own strings, so a mode added later
 * still renders before this table knows about it.
 */
function useModeCopy() {
  const { t } = useTranslation();
  return (
    mode: DiscussionMode,
  ): { label: string; hint: string; cost: string } => {
    switch (mode.name) {
      case "panel_parallel":
        return {
          label: t("Parallel answers"),
          hint: t("Everyone answers the same question at once, independently."),
          cost: t("Fastest"),
        };
      case "sequential":
        return {
          label: t("One after another"),
          hint: t(
            "Each member sees what the others already said and builds on it.",
          ),
          cost: t("Slower · they wait for each other"),
        };
      case "debate":
        return {
          label: t("Cross-examination"),
          hint: t(
            "First everyone states a position, then each responds to the disagreements.",
          ),
          cost: t("Two rounds · about twice the wait"),
        };
      default:
        return { label: mode.label, hint: mode.description, cost: "" };
    }
  };
}

export default function DiscussionModePicker({
  value,
  onChange,
  title,
  note,
  disabled = false,
}: {
  value: string;
  onChange: (name: string) => void;
  /** Rendered with the options, so a single-mode install shows neither. */
  title: string;
  note?: string;
  disabled?: boolean;
}) {
  const [modes, setModes] = useState<DiscussionMode[]>([]);
  const copyFor = useModeCopy();

  useEffect(() => {
    void listDiscussionModes()
      .then(setModes)
      .catch(() => setModes([]));
  }, []);

  // One mode is not a choice. The heading goes with it — a lone title over an
  // empty area is worse than not raising the subject at all.
  if (modes.length < 2) return null;

  return (
    <section>
      <h2 className="mb-2 text-[12px] font-medium text-[var(--foreground)]">
        {title}
      </h2>
      <div className="space-y-2">
        {modes.map((mode) => {
          const active = mode.name === value;
          const copy = copyFor(mode);
          return (
            <button
              key={mode.name}
              type="button"
              disabled={disabled}
              onClick={() => onChange(mode.name)}
              className={`flex w-full items-start gap-2.5 rounded-xl border p-3 text-left transition-colors disabled:opacity-50 ${
                active
                  ? "border-[var(--primary)] bg-[var(--primary)]/[0.05]"
                  : "border-[var(--border)] hover:border-[var(--ring)]"
              }`}
            >
              <span
                className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                  active
                    ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                    : "border-[var(--border)]"
                }`}
              >
                {active ? <Check size={10} /> : null}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline gap-2">
                  <span className="text-[12.5px] font-medium text-[var(--foreground)]">
                    {copy.label}
                  </span>
                  {copy.cost ? (
                    <span className="text-[10px] text-[var(--muted-foreground)]">
                      {copy.cost}
                    </span>
                  ) : null}
                </span>
                <span className="mt-0.5 block text-[11px] leading-relaxed text-[var(--muted-foreground)]">
                  {copy.hint}
                </span>
              </span>
            </button>
          );
        })}
      </div>
      {note ? (
        <p className="mt-2 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
          {note}
        </p>
      ) : null}
    </section>
  );
}

/** The short name for a mode, for headers and list rows. */
export function useDiscussionModeLabel() {
  const { t } = useTranslation();
  return (name: string): string => {
    switch (name) {
      case "panel_parallel":
        return t("Parallel answers");
      case "sequential":
        return t("One after another");
      case "debate":
        return t("Cross-examination");
      default:
        return name;
    }
  };
}
