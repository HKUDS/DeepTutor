"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  JALALI_MONTHS,
  JALALI_WEEKDAYS,
  formatJalali,
  isoToJalali,
  jalaliMonthLength,
  jalaliToIso,
  jalaliWeekday,
} from "@/lib/jalali";

type Props = {
  /** ISO `yyyy-mm-dd` (Gregorian), possibly empty. */
  value: string;
  /** Receives an ISO `yyyy-mm-dd`, or "" when the learner clears the field. */
  onChange: (value: string) => void;
  ariaLabel?: string;
  min?: string;
  disabled?: boolean;
  className?: string;
};

type GridCell = { iso: string; jd: number; inMonth: boolean };

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
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
  ariaLabel,
  min,
  disabled,
  className,
}: Props) {
  const { t, i18n } = useTranslation();
  const enabled = (i18n.language || "").split("-")[0] === "fa";
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const [view, setView] = useState(() => {
    const j = isoToJalali(value) ?? isoToJalali(todayIso());
    return j ? { jy: j.jy, jm: j.jm } : { jy: 1404, jm: 1 };
  });

  const toggle = () => {
    if (open) {
      setOpen(false);
      return;
    }
    const j = isoToJalali(value) ?? isoToJalali(todayIso());
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
        type="date"
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
        className={className}
        onClick={toggle}
      >
        {value ? formatJalali(value) : t("Pick a date")}
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
              {JALALI_MONTHS[view.jm - 1]} {view.jy}
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
                    onChange(cell.iso);
                    setOpen(false);
                  }}
                  className={
                    "mx-auto flex h-7 w-7 items-center justify-center rounded-md " +
                    (cell.iso === value
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "hover:bg-accent") +
                    (isDisabled(cell.iso) ? " opacity-40" : "")
                  }
                >
                  {cell.jd}
                </button>
              ) : (
                <span key={`pad-${idx}`} />
              ),
            )}
          </div>
          <div className="mt-1 flex items-center justify-between border-t border-[var(--border)] pt-1">
            <button
              type="button"
              className="rounded-md px-2 py-1 text-[12px] text-muted-foreground hover:bg-accent"
              onClick={() => {
                onChange(todayIso());
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
