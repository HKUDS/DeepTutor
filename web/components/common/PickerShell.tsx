"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { peekPickerOrigin } from "@/lib/picker-origin";

// Ref-count of currently-open PickerShells. While any are open we mark the
// <body> so global CSS can freeze ambient background animations (the sidebar
// "running session" pulse / breathing titles). Those repaints were being
// re-sampled by the modal's `backdrop-blur`, which read as a constant flicker
// behind the frosted scrim. Freezing them keeps the backdrop rock-steady.
let openShellCount = 0;
function acquireBodyFlag() {
  openShellCount += 1;
  if (typeof document !== "undefined") {
    document.body.setAttribute("data-picker-open", "");
  }
}
function releaseBodyFlag() {
  openShellCount = Math.max(0, openShellCount - 1);
  if (openShellCount === 0 && typeof document !== "undefined") {
    document.body.removeAttribute("data-picker-open");
  }
}

/**
 * Behavioral wrapper for fullscreen pickers (NotebookRecordPicker,
 * HistorySessionPicker, MemoryPicker, QuestionBankPicker, PersonaPicker,
 * BookReferencePicker, SaveToNotebookModal, …). Each of those was rolled
 * by hand and skipped the basic dialog-behavior contract — Escape, backdrop
 * click, body scroll lock, focus trap, ARIA roles. This component lifts
 * that contract into one place so the pickers themselves only have to
 * render their *content*.
 *
 * Design notes:
 * - The shell renders the centered backdrop. Callers render the picker
 *   card as `children` — they keep full control over the card's chrome,
 *   width, padding, etc. (see existing pickers).
 * - `onClose` fires on Escape, on backdrop click, and is reachable
 *   programmatically (e.g. a Cancel button inside the card).
 * - Focus management: on open we move focus to the first focusable element
 *   inside the dialog (typically the search input). On close we restore
 *   focus to wherever it was when the picker opened. This is what users
 *   expect from a modal but every hand-rolled picker had skipped it.
 * - Focus trap: Tab from the last focusable element wraps to the first,
 *   Shift+Tab from the first wraps to the last. The dialog is the only
 *   thing screen-reader / keyboard users can interact with while open.
 */
export interface PickerShellProps {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  /**
   * id of an element inside `children` that names the dialog. Required for
   * proper `aria-labelledby`. If the picker has no visible title, pass an
   * `aria-label` instead via `ariaLabel`.
   */
  labelledBy?: string;
  ariaLabel?: string;
  /**
   * Z-index for the backdrop. Defaults to 85 to match the existing
   * picker convention; raise it if stacking under another picker.
   */
  zIndex?: number;
  /**
   * Outer container layout. Most pickers center their card; some use a
   * full-bleed layout. Defaults to centered.
   */
  align?: "center" | "start";
  /**
   * Extra classes applied to the inner backdrop wrapper. Allows pickers
   * to opt out of the default `flex items-center justify-center` for
   * bespoke layouts.
   */
  className?: string;
  /**
   * Override the default `bg-[var(--overlay)]` backdrop (a theme-aware scrim:
   * warm/cool tint matches the active palette). Pass any opacity / blur /
   * tint combo for pickers that want a frosted-glass look or a lighter scrim.
   */
  backdropClass?: string;
}

const FOCUSABLE_SELECTOR =
  'a[href], area[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), iframe, [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';

export default function PickerShell({
  open,
  onClose,
  children,
  labelledBy,
  ariaLabel,
  zIndex = 85,
  align = "center",
  className,
  backdropClass = "bg-[var(--overlay)]",
}: PickerShellProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  const reduceMotion = useReducedMotion();

  // Capture the trigger's rect at the moment `open` flips true so the card can
  // expand outward from it. Derived during render (React's documented
  // adjust-state-on-prop-change pattern) so it is available for the very first
  // animated frame — an effect would run a frame too late.
  const [originRect, setOriginRect] = useState<DOMRect | null>(null);
  const [wasOpen, setWasOpen] = useState(false);
  if (open !== wasOpen) {
    setWasOpen(open);
    setOriginRect(open ? peekPickerOrigin() : null);
  }

  // Freeze ambient background animations while this shell is open.
  useEffect(() => {
    if (!open) return;
    acquireBodyFlag();
    return () => releaseBodyFlag();
  }, [open]);

  // Stash the focused element when the picker opens so we can return focus
  // there on close. Reset on every open so reopening returns to the latest
  // trigger.
  useEffect(() => {
    if (!open) return;
    previouslyFocusedRef.current =
      (document.activeElement as HTMLElement | null) ?? null;
  }, [open]);

  // Body scroll lock. Preserve the user's prior overflow so we don't trample
  // a parent that already had a lock in place.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Move initial focus into the dialog on open. We defer to the next frame
  // so the rendered card has measured + focusable elements are in the DOM.
  useEffect(() => {
    if (!open) return;
    const id = window.requestAnimationFrame(() => {
      const node = dialogRef.current;
      if (!node) return;
      // Prefer an explicit autofocus marker, then the first focusable child.
      const explicit = node.querySelector<HTMLElement>("[data-autofocus]");
      const target =
        explicit ?? node.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      target?.focus();
    });
    return () => window.cancelAnimationFrame(id);
  }, [open]);

  // Restore focus to the trigger on close. Guarded by document.contains so
  // we never call focus() on a detached element (e.g. the trigger was
  // unmounted while the picker was open).
  useEffect(() => {
    if (open) return;
    const trigger = previouslyFocusedRef.current;
    if (trigger && document.contains(trigger)) {
      trigger.focus();
    }
    previouslyFocusedRef.current = null;
  }, [open]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      // Focus trap. Cycle within the dialog so Tab can never escape into
      // the page chrome behind us.
      const node = dialogRef.current;
      if (!node) return;
      const focusables = Array.from(
        node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      ).filter((el) => !el.hasAttribute("data-focus-skip"));
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    },
    [onClose],
  );

  const handleBackdropMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget) {
        onClose();
      }
    },
    [onClose],
  );

  const alignmentClass =
    align === "center" ? "items-center justify-center" : "items-start";

  // Motion. When we captured the trigger rect, the card *expands outward from
  // it* — it starts small, centered on the clicked row, and grows + glides to
  // the screen center. That sells the "this box unfolded into the picker"
  // feeling. Without an origin (picker opened from elsewhere) it falls back to
  // a quiet placed-from-below settle. The scrim always cross-fades, masking
  // the menu's own exit so the handoff reads as one continuous motion.
  // reduced-motion keeps presence (AnimatePresence still gates mount) but drops
  // transforms to a plain fade.
  const originExpand =
    !reduceMotion && originRect && typeof window !== "undefined"
      ? {
          x: originRect.x + originRect.width / 2 - window.innerWidth / 2,
          y: originRect.y + originRect.height / 2 - window.innerHeight / 2,
        }
      : null;

  const scrimTransition = reduceMotion
    ? { duration: 0 }
    : { duration: 0.2, ease: [0.22, 1, 0.36, 1] as const };
  const cardInitial = reduceMotion
    ? { opacity: 0 }
    : originExpand
      ? { opacity: 0, scale: 0.5, x: originExpand.x, y: originExpand.y }
      : { opacity: 0, y: 10, scale: 0.97, x: 0 };
  const cardAnimate = reduceMotion
    ? { opacity: 1 }
    : { opacity: 1, y: 0, scale: 1, x: 0 };
  const cardExit = reduceMotion
    ? { opacity: 0 }
    : {
        opacity: 0,
        y: 6,
        scale: 0.985,
        x: 0,
        // Closing stays a quick, clean collapse — no bounce on the way out.
        transition: { duration: 0.16, ease: [0.4, 0, 1, 1] as const },
      };
  const cardTransition = reduceMotion
    ? { duration: 0 }
    : {
        // A gently under-damped spring gives the expand some life: it eases out
        // and settles with a barely-there overshoot, instead of the flat,
        // mechanical glide a fixed cubic-bezier produces. Opacity rides a quick
        // separate fade so only the size/position carry the spring.
        type: "spring" as const,
        bounce: 0.28,
        duration: 0.44,
        opacity: { duration: 0.2, ease: [0.22, 1, 0.36, 1] as const },
      };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          // Backdrop. mousedown rather than click so dragging out of a search
          // input doesn't dismiss the picker on the eventual mouseup.
          key="picker-backdrop"
          onMouseDown={handleBackdropMouseDown}
          className={`fixed inset-0 flex ${backdropClass} ${alignmentClass} ${
            className ?? ""
          }`}
          style={{ zIndex }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={scrimTransition}
        >
          <motion.div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={labelledBy}
            aria-label={labelledBy ? undefined : ariaLabel}
            onKeyDown={handleKeyDown}
            // Stop propagation so a click *inside* the dialog never reaches the
            // backdrop's mousedown handler above. Width/layout decisions stay
            // with the picker that renders the card inside.
            onMouseDown={(e) => e.stopPropagation()}
            // Own GPU layer keeps the expand transform crisp (no sub-pixel
            // shimmer) and isolates it from the blurred backdrop's compositing.
            style={{
              willChange: "transform, opacity",
              backfaceVisibility: "hidden",
            }}
            initial={cardInitial}
            animate={cardAnimate}
            exit={cardExit}
            transition={cardTransition}
          >
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
