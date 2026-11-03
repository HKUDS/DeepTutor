"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarDays } from "lucide-react";

import {
  JALALI_MONTHS,
  JALALI_WEEKDAYS,
  formatJalali,
  isoToJalali,
  jalaliMonthLength,
  jalaliToIso,
  jalaliWeekday,
  persianDigits,
} from "@/lib/jalali";

type Props = {
  /**
   * ISO `yyyy-mm-dd` (Gregorian), or `yyyy-mm-ddTHH:mm` when `withTime`.
   * Possibly empty.
   */
  value: string;
  /** Receives the same shape as `value`, or "" when the field is cleared. */
  onChange: (value: string) => void;
  /** Show an hour/minute row and emit `yyyy-mm-ddTHH:mm` values. */
  withTime?: boolean;
  ariaLabel?: string;
  min?: string;
  disabled?: boolean;
  className?: string;
};

type GridCell = { iso: string; jd: number; inMonth: boolean };

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** The date half of a field value, tolerant of an empty or timed value. */
function dateHalf(value: string): string {
  return (value || "").slice(0, 10);
}

/** The time half as `HH:mm`, defaulting to the current minute. */
function timeHalf(value: string): string {
  const t = (value || "").slice(11, 16);
  if (/^\d{2}:\d{2}$/.test(t)) return t;
  const now = new Date();
  return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
}

/**
 * The Persian date field. Persian learners read and write dates in the Solar
 * Hijri calendar, and the native `<input type="date">` popup is always
 * Gregorian regardless of the page language, so when the interface language
 * is Persian this renders a Jalali month grid instead. Every other locale
 * keeps the native input untouched.
 */
export default function FaDateInput({
  value,
  onChange,
  withTime,
  ariaLabel,
  min,
  disabled,
  className,
}: Props) {
  const { t, i18n } = useTranslation();
  const enabled = (i18n.language || "").split("-")[0] === "fa";
  // Time values are emitted through the same ISO shape the native input uses.
  const emitDate = (iso: string) =>
    onChange(withTime && iso ? `${iso}T${timeHalf(value)}` : iso);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const [view, setView] = useState(() => {
    const j = isoToJalali(dateHalf(value)) ?? isoToJalali(todayIso());
    return j ? { jy: j.jy, jm: j.jm } : { jy: 1404, jm: 1 };
  });

  const toggle = () => {
    if (open) {
      setOpen(false);
      return;
    }
    const j = isoToJalali(dateHalf(value)) ?? isoToJalali(todayIso());
    if (j) setView({ jy: j.jy, jm: j.jm });
    setOpen(true);
  };

  useLayoutEffect(() => {
    if (!open || !buttonRef.current) return;
    const rect = buttonRef.current.getBoundingClientRect();
    const width = 272;
    const estHeight = 330;
    const left = Math.min(Math.max(8, rect.left), window.innerWidth - width - 8);
    const below = rect.bottom + 6;
    const top =
      below + estHeight > window.innerHeight ? Math.max(8, rect.top - estHeight - 6) : below;
    setPos({ top, left });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (!popRef.current?.contains(target) && !buttonRef.current?.contains(target)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const cells = useMemo<GridCell[]>(() => {
    if (!open) return [];
    const firstWeekday = jalaliWeekday(view.jy, view.jm, 1);
    const len = jalaliMonthLength(view.jy, view.jm);
    const list: GridCell[] = [];
    for (let i = 0; i < firstWeekday; i += 1) list.push({ iso: "", jd: 0, inMonth: false });
    for (let jd = 1; jd <= len; jd += 1) {
      list.push({ iso: jalaliToIso(view.jy, view.jm, jd), jd, inMonth: true });
    }
    return list;
  }, [open, view]);

  if (!enabled) {
    return (
      <input
        type={withTime ? "datetime-local" : "date"}
        aria-label={ariaLabel}
        value={value}
        min={min}
        disabled={disabled}
        className={className}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  const moveMonth = (delta: number) => {
    setView((v) => {
      const total = v.jy * 12 + (v.jm - 1) + delta;
      return { jy: Math.floor(total / 12), jm: (total % 12) + 1 };
    });
  };

  const isDisabled = (iso: string) => Boolean(min && iso < min);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="dialog"
        aria-expanded={open}
        disabled={disabled}
        className={`inline-flex items-center gap-1.5 text-start ${className ?? ""}`}
        onClick={toggle}
      >
        {/* The calendar mark is the affordance learners look for: clicking it
            (or the label) opens the Jalali month grid. */}
        <CalendarDays aria-hidden className="shrink-0 opacity-70" size={14} />
        <span>
          {value
            ? withTime
              ? `${formatJalali(dateHalf(value))} ${persianDigits(timeHalf(value))}`
              : formatJalali(dateHalf(value))
            : t("Pick a date")}
        </span>
      </button>
      {open && pos && (
        <div
          ref={popRef}
          role="dialog"
          aria-label={ariaLabel}
          className="fixed z-[80] w-[272px] rounded-xl border border-[var(--border)] bg-[var(--popover)] p-2 text-[13px] text-[var(--popover-foreground)] shadow-xl"
          style={{ top: pos.top, left: pos.left }}
        >
          <div className="mb-1 flex items-center justify-between gap-1">
            <button
              type="button"
              aria-label={t("Previous month")}
              className="rounded-md px-2 py-1 hover:bg-accent"
              onClick={() => moveMonth(-1)}
            >
              &rsaquo;
            </button>
            <span className="font-medium">
              {JALALI_MONTHS[view.jm - 1]} {persianDigits(view.jy)}
            </span>
            <button
              type="button"
              aria-label={t("Next month")}
              className="rounded-md px-2 py-1 hover:bg-accent"
              onClick={() => moveMonth(1)}
            >
              &lsaquo;
            </button>
          </div>
          <div className="grid grid-cols-7 text-center text-[11px] text-muted-foreground">
            {JALALI_WEEKDAYS.map((d) => (
              <span key={d} className="py-1">
                {d}
              </span>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-y-0.5 text-center">
            {cells.map((cell, idx) =>
              cell.inMonth ? (
                <button
                  key={cell.iso}
                  type="button"
                  disabled={isDisabled(cell.iso)}
                  onClick={() => {
                    emitDate(cell.iso);
                    setOpen(false);
                  }}
                  className={
                    "mx-auto flex h-7 w-7 items-center justify-center rounded-md " +
                    (cell.iso === dateHalf(value)
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "hover:bg-accent") +
                    (isDisabled(cell.iso) ? " opacity-40" : "")
                  }
                >
                  {persianDigits(cell.jd)}
                </button>
              ) : (
                <span key={`pad-${idx}`} />
              ),
            )}
          </div>
          {withTime && (
            <div className="mt-1 flex items-center justify-center gap-1 border-t border-[var(--border)] pt-2">
              <label className="flex items-center gap-1 text-[12px] text-muted-foreground">
                {t("Time")}
                <input
                  type="time"
                  aria-label={t("Time")}
                  value={timeHalf(value)}
                  onChange={(e) => {
                    const iso = dateHalf(value) || todayIso();
                    onChange(`${iso}T${e.target.value || "00:00"}`);
                  }}
                  className="rounded-md border border-[var(--border)] bg-[var(--popover)] px-1.5 py-0.5 text-[13px] text-[var(--popover-foreground)]"
                />
              </label>
            </div>
          )}
          <div className="mt-1 flex items-center justify-between border-t border-[var(--border)] pt-1">
            <button
              type="button"
              className="rounded-md px-2 py-1 text-[12px] text-muted-foreground hover:bg-accent"
              onClick={() => {
                emitDate(todayIso());
                setOpen(false);
              }}
            >
              {t("Today")}
            </button>
            <button
              type="button"
              className="rounded-md px-2 py-1 text-[12px] text-muted-foreground hover:bg-accent"
              onClick={() => {
                onChange("");
                setOpen(false);
              }}
            >
              {t("Clear")}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
