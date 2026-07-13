"use client";

import { useEffect, useId, useRef } from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  titleIcon?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: "sm" | "md" | "lg" | "xl";
  closeOnBackdrop?: boolean;
  closeOnEscape?: boolean;
  showCloseButton?: boolean;
}

const widthClasses = {
  sm: "w-[400px]",
  md: "w-[500px]",
  lg: "w-[600px]",
  xl: "w-[800px]",
};

const FOCUSABLE_SELECTOR =
  'a[href], area[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), iframe, [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';

/**
 * Shared Modal base component.
 *
 * Provides the full dialog-behavior contract: Escape close, optional
 * backdrop click close, body scroll lock, role=dialog + aria-modal, initial
 * focus into the dialog, focus restoration on close, and a focus trap that
 * keeps Tab cycling inside the dialog. The contract matches PickerShell so
 * Modal and the picker overlays behave the same way from an a11y / keyboard
 * perspective.
 */
export default function Modal({
  isOpen,
  onClose,
  title,
  titleIcon,
  children,
  footer,
  width = "md",
  closeOnBackdrop = true,
  closeOnEscape = true,
  showCloseButton = true,
}: ModalProps) {
  const { t } = useTranslation();
  const dialogRef = useRef<HTMLDivElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  const titleId = useId();

  // Body scroll lock + remember trigger for focus restoration on close.
  useEffect(() => {
    if (!isOpen) return;
    previouslyFocusedRef.current =
      (document.activeElement as HTMLElement | null) ?? null;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [isOpen]);

  // Initial focus on the next frame so the dialog DOM is settled.
  useEffect(() => {
    if (!isOpen) return;
    const id = window.requestAnimationFrame(() => {
      const node = dialogRef.current;
      if (!node) return;
      const explicit = node.querySelector<HTMLElement>("[data-autofocus]");
      const target =
        explicit ?? node.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      target?.focus();
    });
    return () => window.cancelAnimationFrame(id);
  }, [isOpen]);

  // Restore focus to the trigger on close.
  useEffect(() => {
    if (isOpen) return;
    const trigger = previouslyFocusedRef.current;
    if (trigger && document.contains(trigger)) {
      trigger.focus();
    }
    previouslyFocusedRef.current = null;
  }, [isOpen]);

  if (!isOpen) return null;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (closeOnEscape && e.key === "Escape") {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab") return;
    const node = dialogRef.current;
    if (!node) return;
    const focusables = Array.from(
      node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
    );
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
  };

  const handleBackdropMouseDown = (e: React.MouseEvent) => {
    if (closeOnBackdrop && e.target === e.currentTarget) {
      onClose();
    }
  };

  const hasTitle = !!title || !!titleIcon;

  return (
    <div
      // mousedown rather than click so dragging out of an input doesn't
      // accidentally close on mouseup.
      onMouseDown={handleBackdropMouseDown}
      className="fixed inset-0 bg-[var(--overlay)] backdrop-blur-sm flex items-center justify-center z-50 animate-in fade-in"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={hasTitle ? titleId : undefined}
        aria-label={hasTitle ? undefined : (title ?? t("Dialog"))}
        onKeyDown={handleKeyDown}
        onMouseDown={(e) => e.stopPropagation()}
        className={`bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-2xl ${widthClasses[width]} max-h-[90vh] flex flex-col animate-in zoom-in-95`}
      >
        {/* Header */}
        {(hasTitle || showCloseButton) && (
          <div className="p-4 border-b border-[var(--border)] flex items-center justify-between shrink-0">
            <h3
              id={titleId}
              className="font-bold text-[var(--foreground)] flex items-center gap-2"
            >
              {titleIcon}
              {title}
            </h3>
            {showCloseButton ? (
              <button
                type="button"
                onClick={onClose}
                aria-label={t("Close")}
                className="p-1 hover:bg-[var(--muted)] rounded-lg transition-colors"
              >
                <X className="w-5 h-5 text-[var(--muted-foreground)]" />
              </button>
            ) : (
              <div />
            )}
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto">{children}</div>

        {/* Footer */}
        {footer && (
          <div className="p-4 border-t border-[var(--border)] shrink-0">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
