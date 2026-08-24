"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, FolderPlus, Loader2, Plus } from "lucide-react";
import { notify } from "@/lib/notifications";
import type { NotebookCategory } from "@/lib/notebook-api";

interface CategoryMenuProps {
  categories: NotebookCategory[];
  /** Ids of the categories the target entries are already in. */
  activeIds?: number[];
  disabled?: boolean;
  label?: string;
  align?: "left" | "right";
  /** Which way the panel opens. "up" for triggers pinned near the viewport
   *  bottom, where a downward panel would be clipped. */
  direction?: "down" | "up";
  /** "ghost" sits in an icon-button row (no border, like its neighbours);
   *  "outlined" stands alone with a label. */
  variant?: "ghost" | "outlined";
  /** Resolve `false` to say the write failed and the menu should stay put.
   *  Throwing works too — the menu reports that itself. */
  onPick: (categoryId: number) => Promise<boolean | void> | boolean | void;
  onUnpick?: (categoryId: number) => Promise<boolean | void> | boolean | void;
  onCreate: (name: string) => Promise<boolean | void> | boolean | void;
}

/**
 * The "file this into a set" control — the piece the bank never had.
 *
 * Creating and filing are one flow, not two screens: typing a new name and
 * pressing enter files the target in the same gesture, which is what a
 * learner means by "put these in a new mistakes set". Existing categories
 * are listed first so the common case is one click and no typing.
 */
export default function CategoryMenu({
  categories,
  activeIds = [],
  disabled = false,
  label,
  align = "right",
  direction = "down",
  variant = "ghost",
  onPick,
  onUnpick,
  onCreate,
}: CategoryMenuProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Close on outside press, not on blur: blur fires before the click that
  // was meant for an item inside the menu and swallows it.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  // Callers that already report their own failures resolve normally; the
  // ones that throw (the quiz viewer's direct API calls) are reported here,
  // so no path can fail silently behind a closing menu.
  const run = useCallback(
    async (action: () => Promise<boolean | void> | boolean | void) => {
      setBusy(true);
      try {
        // An explicit false means the caller already reported the failure.
        return (await action()) !== false;
      } catch (err) {
        notify(err instanceof Error ? err.message : String(err), {
          tone: "error",
        });
        return false;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const handleCreate = useCallback(async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    const ok = await run(() => onCreate(trimmed));
    if (ok) {
      setName("");
      setOpen(false);
    }
  }, [name, onCreate, run]);

  const active = new Set(activeIds);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        title={t("Add to category")}
        className={`inline-flex items-center gap-1.5 rounded-lg text-[11.5px] font-medium transition-colors disabled:opacity-40 ${
          variant === "outlined" ? "border px-2 py-1.5" : "p-1.5"
        } ${
          open
            ? variant === "outlined"
              ? "border-[var(--primary)]/40 bg-[var(--primary)]/10 text-[var(--primary)]"
              : "bg-[var(--muted)]/60 text-[var(--primary)]"
            : variant === "outlined"
              ? "border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
        }`}
      >
        <FolderPlus className="h-3.5 w-3.5" />
        {label ? <span>{label}</span> : null}
      </button>

      {open && (
        <div
          className={`absolute z-30 w-60 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-lg ${
            align === "right" ? "right-0" : "left-0"
          } ${direction === "up" ? "bottom-full mb-1.5" : "mt-1.5"}`}
        >
          <div className="max-h-56 overflow-y-auto p-1.5">
            {categories.length === 0 && (
              <p className="px-2 py-3 text-center text-[11.5px] text-[var(--muted-foreground)]">
                {t("No categories yet. Type a name below to create one.")}
              </p>
            )}
            {categories.map((category) => {
              const isActive = active.has(category.id);
              return (
                <button
                  key={category.id}
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void run(() =>
                      isActive ? onUnpick?.(category.id) : onPick(category.id),
                    ).then((ok) => {
                      if (ok) setOpen(false);
                    })
                  }
                  className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/70 disabled:opacity-50"
                >
                  <span className="min-w-0 flex-1 truncate">
                    {category.name}
                  </span>
                  {isActive ? (
                    <Check className="h-3.5 w-3.5 shrink-0 text-[var(--primary)]" />
                  ) : (
                    <span className="shrink-0 text-[10.5px] tabular-nums text-[var(--muted-foreground)]">
                      {category.entry_count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          <div className="flex items-center gap-1.5 border-t border-[var(--border)]/70 p-1.5">
            <input
              value={name}
              autoFocus={categories.length === 0}
              disabled={busy}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                // An IME's enter confirms the candidate word; committing on it
                // would file a half-typed 中文 name.
                if (event.key === "Enter" && !event.nativeEvent.isComposing)
                  void handleCreate();
              }}
              placeholder={t("New category…")}
              className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-[12px] text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)] focus:border-[var(--primary)]/50"
            />
            <button
              type="button"
              disabled={busy || !name.trim()}
              onClick={() => void handleCreate()}
              title={t("Create and add")}
              className="shrink-0 rounded-lg bg-[var(--primary)] p-1.5 text-white transition-opacity disabled:opacity-30"
            >
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Plus className="h-3.5 w-3.5" />
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
