"use client";

import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import type { NotebookCategory } from "@/lib/notebook-api";

interface CategoryManagerProps {
  categories: NotebookCategory[];
  onCreate: (name: string) => Promise<boolean>;
  onRename: (id: number, name: string) => Promise<boolean>;
  onDelete: (id: number) => Promise<boolean>;
}

/**
 * Rename / delete / create categories.
 *
 * Filing lives on the entries themselves (see CategoryMenu); this panel is
 * only for maintaining the set of names, which is a rarer job and does not
 * belong in the way of the common one.
 */
export default function CategoryManager({
  categories,
  onCreate,
  onRename,
  onDelete,
}: CategoryManagerProps) {
  const { t } = useTranslation();
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);

  const run = useCallback(async (action: () => Promise<boolean>) => {
    setBusy(true);
    try {
      return await action();
    } finally {
      setBusy(false);
    }
  }, []);

  const commitRename = useCallback(async () => {
    if (!renaming?.name.trim()) {
      setRenaming(null);
      return;
    }
    const { id, name } = renaming;
    if (await run(() => onRename(id, name))) setRenaming(null);
  }, [onRename, renaming, run]);

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-3">
      <div className="space-y-1">
        {categories.map((category) => (
          <div
            key={category.id}
            className="flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 transition-colors hover:bg-[var(--muted)]/40"
          >
            {renaming?.id === category.id ? (
              <>
                <input
                  autoFocus
                  value={renaming.name}
                  disabled={busy}
                  onChange={(event) =>
                    setRenaming({ id: category.id, name: event.target.value })
                  }
                  onKeyDown={(event) => {
                    // Ignore the enter that confirms an IME candidate.
                    if (event.nativeEvent.isComposing) return;
                    if (event.key === "Enter") void commitRename();
                    if (event.key === "Escape") setRenaming(null);
                  }}
                  className="min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-[12.5px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]/50"
                />
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void commitRename()}
                  title={t("Save")}
                  className="rounded-md p-1 text-[var(--primary)] transition-colors hover:bg-[var(--muted)] disabled:opacity-40"
                >
                  <Check size={13} />
                </button>
                <button
                  type="button"
                  onClick={() => setRenaming(null)}
                  title={t("Cancel")}
                  className="rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]"
                >
                  <X size={13} />
                </button>
              </>
            ) : (
              <>
                <span className="min-w-0 flex-1 truncate text-[12.5px] text-[var(--foreground)]">
                  {category.name}
                  <span className="ml-1.5 tabular-nums text-[11px] text-[var(--muted-foreground)]">
                    {category.entry_count}
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() =>
                    setRenaming({ id: category.id, name: category.name })
                  }
                  title={t("Rename")}
                  className="rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                >
                  <Pencil size={13} />
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    // Deleting a category unfiles its questions; it never
                    // deletes them. Say so — the wording is the whole point
                    // of the prompt.
                    if (
                      window.confirm(
                        t(
                          "Delete this category? The questions themselves stay in your bank.",
                        ),
                      )
                    )
                      void run(() => onDelete(category.id));
                  }}
                  title={t("Delete")}
                  className="rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:bg-red-50 hover:text-red-500 disabled:opacity-40 dark:hover:bg-red-950/30"
                >
                  <Trash2 size={13} />
                </button>
              </>
            )}
          </div>
        ))}
        {categories.length === 0 && (
          <p className="py-2 text-center text-[12px] text-[var(--muted-foreground)]">
            {t("No categories yet.")}
          </p>
        )}
      </div>

      <div className="mt-2.5 flex items-center gap-1.5 border-t border-[var(--border)]/70 pt-2.5">
        <input
          value={newName}
          disabled={busy}
          onChange={(event) => setNewName(event.target.value)}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing) return;
            if (event.key !== "Enter" || !newName.trim()) return;
            void run(() => onCreate(newName)).then((ok) => {
              if (ok) setNewName("");
            });
          }}
          placeholder={t("New category name...")}
          className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-[12px] text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)] focus:border-[var(--primary)]/50"
        />
        <button
          type="button"
          disabled={busy || !newName.trim()}
          onClick={() =>
            void run(() => onCreate(newName)).then((ok) => {
              if (ok) setNewName("");
            })
          }
          className="shrink-0 rounded-lg bg-[var(--primary)] p-1.5 text-white transition-opacity disabled:opacity-30"
        >
          <Plus size={13} />
        </button>
      </div>
    </div>
  );
}
