"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, Loader2, Search, UserRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import PickerShell from "@/components/common/PickerShell";
import PickerHeader from "@/components/common/PickerHeader";
import { listPersonas, type PersonaInfo } from "@/lib/personas-api";

interface PersonaPickerProps {
  open: boolean;
  initialPersona: string | null;
  onClose: () => void;
  onApply: (selection: string | null) => void;
}

export default function PersonaPicker({
  open,
  initialPersona,
  onClose,
  onApply,
}: PersonaPickerProps) {
  const { t } = useTranslation();
  const [personas, setPersonas] = useState<PersonaInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<string | null>(initialPersona);
  const [query, setQuery] = useState("");

  // Sync local state with the parent's current selection every time the
  // picker is reopened so the modal always starts from the latest choice.
  useEffect(() => {
    if (!open) return;
    setSelected(initialPersona);
    setQuery("");
  }, [open, initialPersona]);

  useEffect(() => {
    if (!open) return;
    let mounted = true;
    void (async () => {
      setLoading(true);
      try {
        const items = await listPersonas({ force: true });
        if (mounted) setPersonas(items);
      } catch {
        if (mounted) setPersonas([]);
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [open]);

  const filteredPersonas = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return personas;
    return personas.filter((persona) => {
      const name = persona.name.toLowerCase();
      const desc = (persona.description || "").toLowerCase();
      return name.includes(keyword) || desc.includes(keyword);
    });
  }, [personas, query]);

  const handleApply = () => {
    onApply(selected);
    onClose();
  };

  return (
    <PickerShell
      open={open}
      onClose={onClose}
      labelledBy="persona-picker-title"
      className="p-4 backdrop-blur-md"
      backdropClass="bg-[var(--background)]/65"
    >
      <div className="surface-card w-full max-w-3xl overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] text-[var(--card-foreground)] shadow-[0_22px_70px_rgba(0,0,0,0.18)]">
        <PickerHeader
          icon={UserRound}
          titleId="persona-picker-title"
          title={t("Select Persona")}
          subtitle={t(
            "Choose a behavior persona to apply, or pick No persona to use the default.",
          )}
          onClose={onClose}
        />

        <div className="bg-[var(--background)]/40 p-5">
          <button
            type="button"
            onClick={() => setSelected(null)}
            className={`mb-3 flex w-full items-start gap-3 rounded-2xl border px-4 py-3 text-left transition-colors ${
              selected === null
                ? "border-[var(--primary)]/40 bg-[var(--primary)]/8"
                : "border-[var(--border)] bg-[var(--card)] hover:bg-[var(--muted)]/40"
            }`}
          >
            <div
              className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition-colors ${
                selected === null
                  ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                  : "border-[var(--border)] text-transparent"
              }`}
            >
              <Check size={12} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-[14px] font-medium text-[var(--foreground)]">
                {t("No persona")}
              </div>
              <p className="mt-0.5 text-[12px] leading-5 text-[var(--muted-foreground)]">
                {t("Use the default assistant behavior for this turn.")}
              </p>
            </div>
          </button>

          <div className="mb-4">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("Search personas by name or description")}
                className="w-full rounded-xl border border-[var(--border)] bg-[var(--card)] py-2.5 pl-9 pr-3 text-[13px] text-[var(--foreground)] outline-none transition focus:border-[var(--primary)]/50 focus:ring-2 focus:ring-[var(--primary)]/15"
              />
            </div>
          </div>

          <div className="max-h-[48vh] overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--card)]">
            {loading ? (
              <div className="flex min-h-[220px] items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
              </div>
            ) : filteredPersonas.length ? (
              <div className="divide-y divide-[var(--border)]">
                {filteredPersonas.map((persona) => {
                  const active = selected === persona.name;
                  return (
                    <button
                      key={persona.name}
                      onClick={() => setSelected(persona.name)}
                      className={`flex w-full items-start gap-3 px-4 py-3 text-left transition-colors ${
                        active
                          ? "bg-[var(--primary)]/8"
                          : "hover:bg-[var(--muted)]/40"
                      }`}
                    >
                      <div
                        className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition-colors ${
                          active
                            ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                            : "border-[var(--border)] text-transparent"
                        }`}
                      >
                        <Check size={12} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-[14px] font-medium text-[var(--foreground)]">
                            {persona.name}
                          </span>
                          {persona.source === "admin" ? (
                            <span className="rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                              {t("preset")}
                            </span>
                          ) : null}
                        </div>
                        {persona.description ? (
                          <p className="mt-1 line-clamp-2 text-[12px] leading-5 text-[var(--muted-foreground)]">
                            {persona.description}
                          </p>
                        ) : null}
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="px-6 py-14 text-center text-[13px] text-[var(--muted-foreground)]">
                {personas.length === 0
                  ? t("No personas yet")
                  : t("No matching personas found.")}
              </div>
            )}
          </div>

          <div className="mt-4 flex items-center justify-between gap-3">
            <div className="text-[12px] text-[var(--muted-foreground)]">
              {selected
                ? t("Persona: {{name}}", { name: selected })
                : t("No persona selected")}
            </div>
            <button
              onClick={handleApply}
              className="btn-primary rounded-xl bg-[var(--primary)] px-4 py-2.5 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
            >
              {selected ? t("Use Persona") : t("Continue without persona")}
            </button>
          </div>
        </div>
      </div>
    </PickerShell>
  );
}
