"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Check, ChevronDown, Folder, FolderOpen, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useLingerExpand } from "@/hooks/use-linger-expand";
import ToolbarLabel from "@/components/chat/home/ToolbarLabel";
import { saveWorkspace, type ChatWorkspaceRegistration } from "@/lib/workspaces-api";

/**
 * Which workspace this conversation belongs to.
 *
 * Unlike the other composer settings, picking a workspace is not a preference
 * that takes effect next turn: it re-navigates the app (a full page load,
 * which drops the draft) and moves an existing conversation's storage. That is
 * why ``readOnly``
 * turns it into a plain label once the conversation has messages. Re-binding a
 * thread mid-conversation is a management action; it belongs on the workspace
 * settings page, where the consequences are visible, rather than one stray
 * click away from a half-written message.
 */
export function WorkspacePill({
  workspaces,
  workspaceId,
  onSelect,
  disabled = false,
  readOnly = false,
  collapsible = false,
  error = "",
  label: pickerLabel = "Conversation workspace",
}: {
  workspaces: ChatWorkspaceRegistration[];
  workspaceId: string;
  onSelect: (workspaceId: string) => void;
  disabled?: boolean;
  collapsible?: boolean;
  /** Freeze the binding as a label: this conversation already has messages. */
  readOnly?: boolean;
  error?: string;
  label?: string;
}) {
  const { t } = useTranslation();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [createError, setCreateError] = useState("");
  const [created, setCreated] = useState<ChatWorkspaceRegistration[]>([]);
  const [open, setOpen] = useState(false);
  const { expanded, triggerProps } = useLingerExpand(open, 1200, !collapsible);
  const menuRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        !menuRef.current?.contains(target) &&
        !buttonRef.current?.contains(target)
      ) {
        setOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const choices = [...workspaces, ...created.filter(row => !workspaces.some(item => item.workspace_id === row.workspace_id))];
  const active = choices.find((row) => row.workspace_id === workspaceId);
  // An archived workspace keeps its conversations; it just stops being offered
  // for new ones. Still listed while it is the current binding, or the menu
  // would deny the workspace the pill is naming.
  const selectable = choices.filter(
    (row) =>
      row.kind === "workspace" &&
      (!row.archived || row.workspace_id === workspaceId),
  );

  const label = active
    ? active.display_name
    : workspaceId
      ? t("Workspace unavailable")
      : t("Default workspace");

  if (readOnly) {
    return (
      <span
        {...triggerProps}
        tabIndex={collapsible ? 0 : undefined}
        className="inline-flex h-8 min-w-0 shrink-0 items-center rounded-lg px-2 text-[13px] font-medium text-[var(--muted-foreground)]"
        title={`${t(pickerLabel)}: ${label}\n${t("Conversations with messages are moved from workspace settings")}`}
      >
        {workspaceId ? (
          <FolderOpen size={15} strokeWidth={1.7} className="shrink-0" />
        ) : (
          <Folder size={15} strokeWidth={1.7} className="shrink-0" />
        )}
        <span className="sr-only">{label}</span>
        <ToolbarLabel expanded={expanded}>
          <span className="max-w-[150px] truncate">{label}</span>
        </ToolbarLabel>
      </span>
    );
  }

  return (
    <div className="relative flex min-w-0 items-center gap-1.5">
      <button
        ref={buttonRef}
        {...triggerProps}
        type="button"
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t(pickerLabel)}
        title={label}
        className="inline-flex h-8 shrink-0 items-center rounded-lg px-2 text-[13px] font-medium text-[var(--muted-foreground)] transition-[background-color,color,transform] duration-150 hover:bg-[color-mix(in_srgb,var(--muted)_55%,transparent)] hover:text-[var(--foreground)] active:scale-[0.97] disabled:opacity-50"
      >
        {workspaceId ? (
          <FolderOpen size={15} strokeWidth={1.7} className="shrink-0" />
        ) : (
          <Folder size={15} strokeWidth={1.7} className="shrink-0" />
        )}
        <ToolbarLabel expanded={expanded}>
          <span className="max-w-[150px] truncate">{label}</span>
          <ChevronDown
            size={12}
            strokeWidth={2}
            className={`-mr-0.5 shrink-0 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          />
        </ToolbarLabel>
      </button>

      {error ? (
        <span
          role="alert"
          className="max-w-[180px] truncate text-[11.5px] text-[var(--destructive)]"
          title={error}
        >
          {error}
        </span>
      ) : null}

      {open && !disabled && (
        <div
          ref={menuRef}
          role="menu"
          className="dt-popup-up absolute bottom-full left-0 z-50 mb-1.5 w-[248px] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] py-1 shadow-lg backdrop-blur-md"
        >
          <div className="max-h-[280px] overflow-y-auto">
            {selectable.length === 0 ? (
              <p className="px-3 py-2.5 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
                {t(
                  "Create a workspace to keep conversations and learning materials together.",
                )}
              </p>
            ) : (
              selectable.map((row) => (
                <button
                  key={row.workspace_id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={row.workspace_id === workspaceId}
                  disabled={row.status !== "ready"}
                  title={row.status === "ready" ? row.path : row.error}
                  onClick={() => {
                    onSelect(row.workspace_id);
                    setOpen(false);
                  }}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12.5px] text-[var(--foreground)] transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_60%,transparent)] disabled:opacity-50"
                >
                  <Folder
                    size={13}
                    strokeWidth={1.7}
                    className="shrink-0 text-[var(--muted-foreground)]"
                  />
                  <span className="min-w-0 flex-1 truncate">
                    {row.display_name}
                  </span>
                  {row.workspace_id === workspaceId ? (
                    <Check size={12} className="shrink-0" />
                  ) : null}
                </button>
              ))
            )}
          </div>

          {workspaceId ? (
            <button
              type="button"
              onClick={() => {
                onSelect("");
                setOpen(false);
              }}
              className="mt-1 flex w-full items-center gap-2 border-t border-[color-mix(in_srgb,var(--border)_70%,transparent)] px-3 py-1.5 pt-2 text-left text-[12px] text-[var(--muted-foreground)] transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_60%,transparent)] hover:text-[var(--foreground)]"
            >
              {t("Default workspace")}
            </button>
          ) : null}

          {creating ? (
            <form className="space-y-2 border-t border-[var(--border)] p-3" onSubmit={async event => {
              event.preventDefault();
              event.stopPropagation();
              if (!name.trim() || saving) return;
              setSaving(true);
              setCreateError("");
              try {
                const row = await saveWorkspace({ name: name.trim() });
                setCreated(items => [...items, row]);
                onSelect(row.workspace_id);
                setCreating(false);
                setName("");
                setOpen(false);
              } catch (error) {
                setCreateError(error instanceof Error ? error.message : String(error));
              } finally { setSaving(false); }
            }}>
              <label className="block text-xs">{t("Workspace name")}
                <input autoFocus required maxLength={100} value={name} onChange={event => setName(event.target.value)}
                  className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--background)] p-2" />
              </label>
              {createError && <p role="alert" className="text-xs text-[var(--destructive)]">{createError}</p>}
              <div className="flex gap-3 text-xs">
                <button type="submit" disabled={saving || !name.trim()} className="rounded bg-[var(--primary)] px-2 py-1 text-[var(--primary-foreground)] disabled:opacity-50">{t("Create workspace")}</button>
                <button type="button" disabled={saving} onClick={() => setCreating(false)}>{t("Cancel")}</button>
              </div>
            </form>
          ) : null}
          <div className="mt-1 flex items-center gap-1 border-t border-[color-mix(in_srgb,var(--border)_70%,transparent)] px-2 pt-1 text-[var(--muted-foreground)]">
            <Link
              href="/settings/workspace"
              onClick={() => setOpen(false)}
              className="min-w-0 flex-1 rounded-md px-1 py-1.5 text-[11.5px] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
            >
              {t("Manage workspaces")}
            </Link>
            {!creating && (
              <button
                type="button"
                aria-label={t("New workspace")}
                title={t("New workspace")}
                onClick={() => setCreating(true)}
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
              >
                <Plus size={15} strokeWidth={1.7} />
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
