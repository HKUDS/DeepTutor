"use client";

import { AnimatePresence, m, useReducedMotion } from "framer-motion";
import { Check, ChevronDown, Search } from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { useOutsideClick } from "@/hooks/use-outside-click";
import { Tooltip } from "@/shared/ui/Tooltip";
import { useResourceReuse } from "./ResourceReuse";
import type { ResourceKind } from "@/lib/resource-reuse";

export type TrayPlacement = "up" | "down";

const OPTION = "[data-tray-option]:not(:disabled)";
const EASE_OUT = [0.16, 1, 0.3, 1] as const;
/** Space kept between the list and its button, and between it and the window edge. */
const GAP = 8;
const MARGIN = 12;
/** Below this, the preferred side is too cramped and the other one is tried. */
const ROOMY = 240;

interface Room {
  side: TrayPlacement;
  /** Tallest the list may be on that side without leaving the window. */
  max: number;
}

/**
 * Where a list opened from `trigger` fits. It keeps the side it was asked
 * for unless that side is cramped and the other has more room, and it is
 * never taller than the room it ends up with — the options scroll inside.
 */
function roomFor(trigger: DOMRect, preferred: TrayPlacement): Room {
  const below = window.innerHeight - trigger.bottom - GAP - MARGIN;
  const above = trigger.top - GAP - MARGIN;
  const [mine, other] = preferred === "down" ? [below, above] : [above, below];
  const side = mine < ROOMY && other > mine ? (preferred === "down" ? "up" : "down") : preferred;
  return { side, max: Math.max(160, Math.floor(side === "down" ? below : above)) };
}

/**
 * One control in the layer under the composer: a quiet button that opens a
 * short list beside the box.
 *
 * The list grows out of its button toward the page's free space and folds
 * back the same way, quickly — it is a menu, not a dialog. Arrow keys walk
 * the options, Escape hands focus back to the button, and a click anywhere
 * else puts it away. The list mounts with each opening, so a search typed
 * last time is never waiting in it.
 */
export function TrayMenu({
  icon,
  label,
  value,
  active = false,
  dots,
  valueIcon,
  fold,
  placement,
  align = "start",
  open: openProp,
  onOpenChange,
  children,
}: {
  icon: ReactNode;
  label: string;
  /** What is chosen now, read after the label. */
  value?: string;
  /** The choice differs from the default, so the value takes the accent. */
  active?: boolean;
  dots?: ReactNode;
  /** Shown after the label, and kept when the button folds: what is chosen, as a mark. */
  valueIcon?: ReactNode;
  /**
   * Rest as marks only, unfolding while pointed at, focused or open. `false`
   * shows the words for now, built the same way, so a button that starts
   * folding mid-session — a mode just chosen — folds in place.
   */
  fold?: boolean;
  placement: TrayPlacement;
  /** Which edge of the button the list lines up with. */
  align?: "start" | "end";
  /** Controlled open state, for commands that open this list from elsewhere. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: (close: () => void) => ReactNode;
}) {
  const [openState, setOpenState] = useState(false);
  const [room, setRoom] = useState<Room | null>(null);
  const open = openProp ?? openState;
  const reduced = useReducedMotion();
  const id = useId();
  const triggerId = `${id}-trigger`;
  const rootRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const setOpen = useCallback(
    (next: boolean) => {
      setOpenState(next);
      onOpenChange?.(next);
    },
    [onOpenChange],
  );
  // Looked up rather than held in a ref: `close` is handed to the list while
  // it renders, and the button it returns focus to is always this one.
  const close = useCallback(() => {
    setOpen(false);
    document.getElementById(triggerId)?.focus({ preventScroll: true });
  }, [setOpen, triggerId]);
  useOutsideClick(rootRef, open, () => setOpen(false));

  // Land where the next keystroke belongs: the search box when there is one,
  // else the current choice, else the first option.
  useEffect(() => {
    if (!open) return;
    const frame = requestAnimationFrame(() => {
      const panel = panelRef.current;
      const target =
        panel?.querySelector<HTMLElement>("[data-tray-search]") ??
        panel?.querySelector<HTMLElement>(`${OPTION}[aria-selected="true"]`) ??
        panel?.querySelector<HTMLElement>(OPTION);
      target?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [open]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const options = Array.from(
      panelRef.current?.querySelectorAll<HTMLElement>(OPTION) ?? [],
    );
    if (!options.length) return;
    event.preventDefault();
    const index = options.indexOf(document.activeElement as HTMLElement);
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? options.length - 1
          : event.key === "ArrowDown"
            ? (index + 1) % options.length
            : index <= 0
              ? options.length - 1
              : index - 1;
    options[next]?.focus();
    options[next]?.scrollIntoView({ block: "nearest" });
  };

  // Grows from the edge it is attached to; on the way out it only drifts a
  // little, so closing never reads as a second event. Opened from elsewhere
  // (`/persona`) it has no measurement and keeps the side it was given.
  const side = room?.side ?? placement;
  const lift = side === "down" ? -6 : 6;
  return (
    <div
      ref={rootRef}
      className={`dt-tray-menu is-${align}`}
      onKeyDown={open ? onKeyDown : undefined}
    >
      {/* Named on hover too: in a narrow column the tray keeps only icons.
          A folding button names itself by unfolding instead. */}
      <Tooltip
        label={label}
        description={value}
        side={placement === "up" ? "top" : "bottom"}
        suppressed={open || fold !== undefined}
        className="min-w-0"
      >
      <button
        id={triggerId}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        data-active={active || undefined}
        onClick={(event) => {
          // Measured on the way in, so the list opens on the side it fits.
          if (!open) setRoom(roomFor(event.currentTarget.getBoundingClientRect(), placement));
          setOpen(!open);
        }}
        data-fold={fold || undefined}
        className="dt-tray-button"
      >
        {icon}
        {fold === undefined ? (
          <>
            <span className="dt-tray-label">{label}</span>
            {dots}
            {value && <span className="dt-tray-value">{value}</span>}
            <ChevronDown size={12} strokeWidth={2} aria-hidden className="dt-tray-chevron" />
          </>
        ) : (
          <>
            <TrayReveal>
              <span className="dt-tray-label">{label}</span>
              {dots}
            </TrayReveal>
            {valueIcon && <span className="dt-tray-value-icon">{valueIcon}</span>}
            <TrayReveal>
              {value && <span className="dt-tray-value">{value}</span>}
              <ChevronDown size={12} strokeWidth={2} aria-hidden className="dt-tray-chevron" />
            </TrayReveal>
          </>
        )}
      </button>
      </Tooltip>
      <AnimatePresence>
        {open && (
          <m.div
            ref={panelRef}
            id={id}
            role="dialog"
            aria-label={label}
            className={`dt-tray-popover is-${side} is-${align}`}
            style={room ? { maxHeight: room.max } : undefined}
            initial={reduced ? { opacity: 0 } : { opacity: 0, y: lift, scale: 0.97 }}
            animate={{
              opacity: 1,
              y: 0,
              scale: 1,
              transition: { duration: reduced ? 0 : 0.18, ease: EASE_OUT },
            }}
            exit={{
              opacity: 0,
              y: reduced ? 0 : lift / 2,
              scale: reduced ? 1 : 0.985,
              transition: { duration: reduced ? 0 : 0.1, ease: [0.4, 0, 1, 1] },
            }}
          >
            {children(close)}
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/**
 * Words a folding tray button can put away. The outer span animates its one
 * grid column between nothing and its content's width; the middle one clips;
 * the inner one carries the spacing, so a folded run leaves no gap behind.
 */
function TrayReveal({ children }: { children: ReactNode }) {
  return (
    <span className="dt-tray-reveal">
      <span>
        <span className="dt-tray-reveal-run">{children}</span>
      </span>
    </span>
  );
}

/** The options of one list; `multi` when several can be chosen at once. */
export function TrayList({
  label,
  multi = false,
  bare = false,
  children,
}: {
  label: string;
  multi?: boolean;
  /** Marks drawn to stand alone: larger, without the tile behind them. */
  bare?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      role="listbox"
      aria-label={label}
      aria-multiselectable={multi || undefined}
      data-bare={bare || undefined}
      className="dt-tray-list"
    >
      {children}
    </div>
  );
}

/** A titled run of options inside a list. */
/** A titled run of options; ``hint`` says once what every option in it does. */
export function TraySection({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <div
      role="group"
      aria-labelledby={id}
      aria-describedby={hint ? `${id}-hint` : undefined}
      className="dt-tray-group"
    >
      <div className="dt-tray-section">
        <span id={id}>{title}</span>
        {hint ? (
          <span id={`${id}-hint`} className="dt-tray-section-hint">
            {hint}
          </span>
        ) : null}
      </div>
      {children}
    </div>
  );
}

export function TrayOption({
  selected,
  onSelect,
  leading,
  title,
  meta,
  disabled = false,
}: {
  selected: boolean;
  onSelect: () => void;
  leading: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      data-tray-option
      disabled={disabled}
      onClick={onSelect}
      className="dt-tray-row"
    >
      <span aria-hidden className="dt-tray-lead">
        {leading}
      </span>
      <span className="min-w-0 flex-1">
        <span className="dt-tray-row-title">{title}</span>
        {meta ? <span className="dt-tray-row-meta">{meta}</span> : null}
      </span>
      <span aria-hidden className="dt-tray-check">
        <Check size={11} strokeWidth={3} />
      </span>
    </button>
  );
}

export function TraySearch({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <label className="dt-tray-search">
      <Search size={13} strokeWidth={1.8} aria-hidden />
      <input
        data-tray-search
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
      />
    </label>
  );
}

/**
 * Whether these choices carry into the next turn — the same policy the
 * resource panel keeps, as one small switch.
 */
export function TrayReuse({ kinds }: { kinds: readonly ResourceKind[] }) {
  const context = useResourceReuse();
  const { t } = useTranslation();
  if (!context) return null;
  const enabled = kinds.every((kind) => context.policy[kind]);
  return (
    <label className="dt-tray-reuse">
      <input
        type="checkbox"
        className="sr-only"
        checked={enabled}
        onChange={(event) => kinds.forEach((kind) => context.setEveryTurn(kind, event.target.checked))}
      />
      <span aria-hidden className="dt-tray-switch" />
      {t("Every turn")}
    </label>
  );
}

export function TrayFoot({ children }: { children: ReactNode }) {
  return <div className="dt-tray-foot">{children}</div>;
}
