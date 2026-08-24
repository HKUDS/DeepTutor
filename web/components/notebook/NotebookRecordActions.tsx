"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Copy,
  CornerUpRight,
  MoreHorizontal,
  Pencil,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import Tooltip from "@/components/common/Tooltip";
import type { NotebookSummary } from "@/lib/notebook-api";

type Panel = "root" | "move" | "copy";

interface NotebookRecordActionsProps {
  targets: NotebookSummary[];
  disabled?: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onRelocate: (targetNotebookId: string, mode: "move" | "copy") => void;
}

/**
 * The per-record action menu.
 *
 * One always-present trigger rather than a cluster of icons that appears on
 * hover: the row keeps a stable shape, the affordance is discoverable, and
 * every destination fits in one place. Picking a notebook swaps the menu's
 * panel in place instead of opening a nested popover — no second layer to
 * position, and the back arrow keeps the path obvious.
 */
export default function NotebookRecordActions({
  targets,
  disabled = false,
  onEdit,
  onDelete,
  onRelocate,
}: NotebookRecordActionsProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [panel, setPanel] = useState<Panel>("root");
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on outside click and on Escape. A pointerdown listener rather than
  // onBlur: blur fires before the click lands on a menu item, which would
  // cancel the very action the user is choosing.
  // Always reopen on the root panel — a menu that remembers it was left on
  // the destination list would be disorienting next time round.
  const close = () => {
    setOpen(false);
    setPanel("root");
  };

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
        setPanel("root");
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        setOpen(false);
        setPanel("root");
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="relative shrink-0">
      <Tooltip label={t("Record actions")} side="bottom" suppressed={open}>
        <button
          type="button"
          disabled={disabled}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label={t("Record actions")}
          onClick={() => (open ? close() : setOpen(true))}
          className={`inline-flex h-7 w-7 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-[background-color,color,opacity,transform] duration-150 active:scale-[0.97] hover:bg-[var(--muted)] hover:text-[var(--foreground)] focus-visible:bg-[var(--muted)] focus-visible:text-[var(--foreground)] focus-visible:outline-none disabled:opacity-30 ${
            open
              ? "bg-[var(--muted)] text-[var(--foreground)] opacity-100"
              : "opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100"
          }`}
        >
          <MoreHorizontal size={15} />
        </button>
      </Tooltip>

      {open && (
        <div
          role="menu"
          className="animate-pop-in absolute right-0 top-full z-50 mt-1 w-[min(240px,calc(100vw-32px))] origin-top-right overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] shadow-lg backdrop-blur-md"
        >
          {panel === "root" ? (
            <div className="p-1">
              <MenuItem
                icon={Pencil}
                label={t("Edit")}
                onClick={() => {
                  close();
                  onEdit();
                }}
              />
              {targets.length > 0 && (
                <>
                  <MenuItem
                    icon={CornerUpRight}
                    label={t("Move to")}
                    hasSubmenu
                    onClick={() => setPanel("move")}
                  />
                  <MenuItem
                    icon={Copy}
                    label={t("Copy to")}
                    hasSubmenu
                    onClick={() => setPanel("copy")}
                  />
                </>
              )}
              <div className="my-1 h-px bg-[var(--border)]/60" />
              <MenuItem
                icon={Trash2}
                label={t("Delete")}
                tone="danger"
                onClick={() => {
                  close();
                  onDelete();
                }}
              />
            </div>
          ) : (
            <div className="p-1">
              <button
                type="button"
                onClick={() => setPanel("root")}
                className="mb-0.5 flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
              >
                <ArrowLeft size={12} />
                {panel === "move" ? t("Move to") : t("Copy to")}
              </button>
              <div className="max-h-[220px] overflow-y-auto">
                {targets.map((notebook) => (
                  <button
                    key={notebook.id}
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      close();
                      onRelocate(
                        notebook.id,
                        panel === "move" ? "move" : "copy",
                      );
                    }}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12.5px] text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/70"
                  >
                    <span
                      aria-hidden
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: notebook.color || "#6366F1" }}
                    />
                    <span className="min-w-0 flex-1 truncate">
                      {notebook.name}
                    </span>
                    <span className="shrink-0 text-[10.5px] tabular-nums text-[var(--muted-foreground)]">
                      {notebook.record_count ?? 0}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MenuItem({
  icon: Icon,
  label,
  onClick,
  tone = "default",
  hasSubmenu = false,
}: {
  icon: typeof Pencil;
  label: string;
  onClick: () => void;
  tone?: "default" | "danger";
  hasSubmenu?: boolean;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left text-[12.5px] transition-colors ${
        tone === "danger"
          ? "text-[var(--destructive)] hover:bg-[var(--destructive)]/10"
          : "text-[var(--foreground)] hover:bg-[var(--muted)]/70"
      }`}
    >
      <Icon size={13} className="shrink-0 opacity-70" />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {hasSubmenu && (
        <span aria-hidden className="shrink-0 text-[var(--muted-foreground)]">
          ›
        </span>
      )}
    </button>
  );
}
