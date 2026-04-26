"use client";

import { useEffect, useCallback } from "react";
import { X } from "lucide-react";

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
  sm: "w-full max-w-[400px]",
  md: "w-full max-w-[500px]",
  lg: "w-full max-w-[600px]",
  xl: "w-full max-w-[800px]",
};

/**
 * Shared Modal base component
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
  // Handle escape key
  const handleEscape = useCallback(
    (e: KeyboardEvent) => {
      if (closeOnEscape && e.key === "Escape") {
        onClose();
      }
    },
    [closeOnEscape, onClose],
  );

  useEffect(() => {
    if (isOpen) {
      document.addEventListener("keydown", handleEscape);
      // Prevent body scroll when modal is open
      document.body.style.overflow = "hidden";
    }
    return () => {
      document.removeEventListener("keydown", handleEscape);
      document.body.style.overflow = "";
    };
  }, [isOpen, handleEscape]);

  if (!isOpen) return null;

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (closeOnBackdrop && e.target === e.currentTarget) {
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-3 backdrop-blur-sm animate-in fade-in sm:items-center sm:p-4"
      onClick={handleBackdropClick}
    >
      <div
        className={`flex max-h-[92dvh] flex-col rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-2xl ${widthClasses[width]} animate-in zoom-in-95`}
      >
        {/* Header */}
        {(title || titleIcon || showCloseButton) && (
          <div className="p-4 border-b border-[var(--border)] flex items-center justify-between shrink-0">
            <h3 className="font-bold text-[var(--foreground)] flex items-center gap-2">
              {titleIcon}
              {title}
            </h3>
            {showCloseButton ? (
              <button
                onClick={onClose}
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
