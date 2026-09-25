"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { useChatWorkspaces } from "@/hooks/useChatWorkspaces";
import {
  createReadingWorkspace,
  updateReadingWorkspace,
  type ReadingWorkspace,
} from "@/lib/reading-workspace-api";

import { FOLDER_COLORS, FolderGlyph, folderTone } from "./FolderGlyph";

/**
 * Creating a collection and renaming or recolouring one are the same small
 * form. Creating also says where the collection lives: a workspace holds
 * many collections, and a collection's files and conversations are stored
 * in exactly one of them.
 */
export function FolderDialog({
  collection,
  workspaceId,
  lockWorkspace = false,
  onClose,
  onSaved,
}: {
  /** Present when editing; absent when creating. */
  collection?: ReadingWorkspace;
  /** The workspace a new collection starts in. */
  workspaceId: string;
  /** A course keeps what it creates in its own workspace. */
  lockWorkspace?: boolean;
  onClose: () => void;
  onSaved: (collection: ReadingWorkspace, workspaceId: string) => void;
}) {
  const { t } = useTranslation();
  const headingId = useId();
  const { workspaces } = useChatWorkspaces();
  const [title, setTitle] = useState(collection?.title ?? "");
  const [color, setColor] = useState(collection?.color ?? "");
  const [destination, setDestination] = useState(workspaceId);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const destinations = [
    { id: "", name: t("Default workspace") },
    ...workspaces
      .filter((row) => !row.archived && row.status === "ready")
      .map((row) => ({ id: row.workspace_id, name: row.display_name })),
  ];
  // Only worth asking when there is somewhere else to put it.
  const askWorkspace =
    !collection &&
    !lockWorkspace &&
    destinations.length > 1 &&
    destinations.some((row) => row.id === destination);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (working) return;
    setWorking(true);
    setError("");
    const name = title.trim() || t("Untitled collection");
    const saved = collection
      ? updateReadingWorkspace(
          collection.workspace_id,
          { title: name, color },
          collection.content_workspace_id ?? "",
        ).then((row) => onSaved(row, collection.content_workspace_id ?? ""))
      : createReadingWorkspace({ title: name, color }, destination).then(
          (row) => onSaved(row, destination),
        );
    void saved
      .catch((caught) =>
        setError(
          caught instanceof Error ? caught.message : t("Could not save."),
        ),
      )
      .finally(() => setWorking(false));
  };

  return (
    <div
      className="fixed inset-0 z-[110] flex items-center justify-center bg-[var(--overlay)] p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        onSubmit={submit}
        className="w-full max-w-[380px] rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-lg dark:bg-[var(--popover)]"
      >
        <h2 id={headingId} className="font-serif text-[17px] font-semibold">
          {collection ? t("Edit collection") : t("New collection")}
        </h2>

        <div className="mt-4 flex items-center gap-3">
          <FolderGlyph
            color={color}
            files={collection?.tabs.length ?? 0}
            size={44}
            className="shrink-0"
          />
          <input
            autoFocus
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={300}
            placeholder={t("Untitled collection")}
            aria-label={t("Collection name")}
            className="h-9 min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 text-[13px] outline-none transition placeholder:text-[var(--muted-foreground)] focus:border-[var(--ring)]"
          />
        </div>

        <fieldset className="mt-4">
          <legend className="text-[11.5px] font-medium text-[var(--muted-foreground)]">
            {t("Color")}
          </legend>
          <div className="mt-2 flex flex-wrap gap-2">
            {FOLDER_COLORS.map((row) => {
              const selected = row.key === color;
              return (
                <button
                  key={row.key || "default"}
                  type="button"
                  onClick={() => setColor(row.key)}
                  aria-label={t(row.label)}
                  aria-pressed={selected}
                  title={t(row.label)}
                  className="size-6 rounded-full transition hover:scale-110"
                  style={{
                    background: row.tone,
                    boxShadow: selected
                      ? `0 0 0 2px var(--card), 0 0 0 3.5px ${folderTone(row.key)}`
                      : undefined,
                  }}
                />
              );
            })}
          </div>
        </fieldset>

        {askWorkspace && (
          <label className="mt-4 block">
            <span className="text-[11.5px] font-medium text-[var(--muted-foreground)]">
              {t("Workspace")}
            </span>
            <select
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
              aria-label={t("Workspace")}
              className="mt-2 h-9 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 text-[13px] outline-none focus:border-[var(--ring)]"
            >
              {destinations.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
            <span className="mt-1.5 block text-[11px] leading-relaxed text-[var(--muted-foreground)]">
              {t(
                "The collection's files and reading conversations are kept in this workspace.",
              )}
            </span>
          </label>
        )}

        {error && (
          <p role="alert" className="mt-3 text-[11px] text-[var(--destructive)]">
            {error}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="h-8 rounded-lg px-3 text-[12px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            {t("Cancel")}
          </button>
          <button
            type="submit"
            disabled={working}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 text-[12px] font-semibold text-[var(--primary-foreground)] transition hover:opacity-90 disabled:opacity-50"
          >
            {working && <Loader2 size={12} className="animate-spin" />}
            {collection ? t("Save") : t("Create")}
          </button>
        </div>
      </form>
    </div>
  );
}
