"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Search, Sparkles, UserRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLingerExpand } from "@/hooks/use-linger-expand";
import { listPersonas, type PersonaInfo } from "@/lib/personas-api";

/**
 * Session persona switcher (composer toolbar).
 *
 * Mirrors ModelSelector's chip + dropdown pattern. The selection is a
 * SESSION-level preference: it applies to every following message in the
 * current chat until changed (persisted via session.preferences.persona).
 * "Default" (value "") means no persona — the assistant's base behavior.
 *
 * Open state is optionally controlled (`open`/`onOpenChange`) so the
 * `/persona` slash command and the @space menu entry can pop the same
 * dropdown programmatically.
 */
export default function PersonaSelector({
  value,
  onChange,
  open: openProp,
  onOpenChange,
  placement = "top",
}: {
  /** Active persona name; "" = Default (no persona). */
  value: string;
  onChange: (persona: string) => void;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  placement?: "top" | "bottom";
}) {
  const { t } = useTranslation();
  const [openState, setOpenState] = useState(false);
  const open = openProp ?? openState;
  const { expanded, linger, triggerProps: lingerProps } = useLingerExpand(open);
  const setOpen = (next: boolean) => {
    setOpenState(next);
    onOpenChange?.(next);
    // Closing (selection or outside click) keeps the label expanded for a
    // beat so the change registers before the chip collapses.
    if (!next) linger();
  };
  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const [personas, setPersonas] = useState<PersonaInfo[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [query, setQuery] = useState("");

  // Load (cached) persona list when the dropdown first opens.
  useEffect(() => {
    if (!open || loaded) return;
    let cancelled = false;
    void listPersonas()
      .then((items) => {
        if (!cancelled) {
          setPersonas(items);
          setLoaded(true);
        }
      })
      .catch(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [open, loaded]);

  // Focus the search box and clear stale queries on open.
  useEffect(() => {
    if (!open) return;
    setQuery("");
    requestAnimationFrame(() => searchRef.current?.focus());
  }, [open]);

  // Close on outside click.
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

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return personas;
    return personas.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.description.toLowerCase().includes(q),
    );
  }, [personas, query]);

  const defaultLabel = t("Default");
  const label = value || defaultLabel;
  const menuPlacementClass =
    placement === "bottom" ? "top-full mt-1.5" : "bottom-full mb-1.5";

  const pick = (persona: string) => {
    onChange(persona);
    setOpen(false);
  };

  const showDefaultRow =
    !query.trim() ||
    defaultLabel.toLowerCase().includes(query.trim().toLowerCase());

  return (
    <div ref={rootRef} className="relative">
      {/* Resting state is just the small figure icon; hovering (or opening
          the menu) slides the persona name out with a max-width animation
          and lingers ~1.2s after leave/selection before collapsing. A
          non-default persona tints the icon primary so the active state
          stays visible even when collapsed. */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-label={t("Select persona")}
        aria-expanded={open}
        {...lingerProps}
        className={`inline-flex h-8 shrink-0 items-center rounded-lg px-2 text-[14px] font-medium transition-[background-color,color,transform] duration-150 active:scale-[0.97] ${
          open
            ? "bg-[var(--muted)] text-[var(--foreground)]"
            : value
              ? "text-[var(--primary)] hover:bg-[var(--primary)]/[0.07]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
        }`}
      >
        <UserRound size={16} strokeWidth={1.7} className="shrink-0" />
        <span
          className={`flex min-w-0 items-center gap-1 overflow-hidden whitespace-nowrap transition-[max-width,opacity,margin-left] duration-300 ease-out ${
            expanded
              ? "ml-1.5 max-w-[140px] opacity-100"
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
          className={`absolute right-0 z-50 ${menuPlacementClass} w-[min(280px,calc(100vw-32px))] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] shadow-lg backdrop-blur-md`}
        >
          <div className="border-b border-[var(--border)]/50 p-2">
            <div className="flex items-center gap-1.5 rounded-lg border border-[var(--border)]/60 bg-[var(--background)] px-2 py-1">
              <Search
                size={12}
                strokeWidth={1.7}
                className="shrink-0 text-[var(--muted-foreground)]"
              />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") {
                    e.preventDefault();
                    setOpen(false);
                  }
                }}
                placeholder={t("Search personas...")}
                className="w-full bg-transparent text-[12px] text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
              />
            </div>
          </div>
          <div className="max-h-[280px] overflow-y-auto py-1">
            {showDefaultRow && (
              <button
                type="button"
                onClick={() => pick("")}
                className={`flex w-full items-center gap-2.5 px-3 py-1.5 text-left transition-colors active:bg-[var(--muted)]/70 ${
                  !value
                    ? "bg-[var(--primary)]/[0.06]"
                    : "hover:bg-[var(--muted)]/45"
                }`}
              >
                <Sparkles
                  size={15}
                  strokeWidth={1.7}
                  className={`shrink-0 ${
                    !value
                      ? "text-[var(--primary)]"
                      : "text-[var(--muted-foreground)]"
                  }`}
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12.5px] font-medium leading-snug text-[var(--foreground)]">
                    {defaultLabel}
                  </div>
                  <div className="truncate text-[11px] leading-snug text-[var(--muted-foreground)]">
                    {t("No persona — the assistant's standard behavior")}
                  </div>
                </div>
                {!value && (
                  <Check
                    size={14}
                    strokeWidth={2}
                    className="shrink-0 text-[var(--primary)]"
                  />
                )}
              </button>
            )}
            {filtered.map((persona) => {
              const selected = persona.name === value;
              return (
                <button
                  key={persona.name}
                  type="button"
                  onClick={() => pick(persona.name)}
                  className={`flex w-full items-center gap-2.5 px-3 py-1.5 text-left transition-colors active:bg-[var(--muted)]/70 ${
                    selected
                      ? "bg-[var(--primary)]/[0.06]"
                      : "hover:bg-[var(--muted)]/45"
                  }`}
                >
                  <UserRound
                    size={15}
                    strokeWidth={1.7}
                    className={`shrink-0 ${
                      selected
                        ? "text-[var(--primary)]"
                        : "text-[var(--muted-foreground)]"
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <span className="truncate text-[12.5px] font-medium leading-snug text-[var(--foreground)]">
                        {persona.name}
                      </span>
                      {persona.source === "admin" && (
                        <span className="shrink-0 rounded-full bg-[var(--muted)] px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                          {t("Preset")}
                        </span>
                      )}
                    </div>
                    {persona.description ? (
                      <div className="truncate text-[11px] leading-snug text-[var(--muted-foreground)]">
                        {persona.description}
                      </div>
                    ) : null}
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
            {loaded && filtered.length === 0 && !showDefaultRow && (
              <div className="px-3 py-4 text-center text-[12px] text-[var(--muted-foreground)]">
                {t("No personas match this search.")}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
