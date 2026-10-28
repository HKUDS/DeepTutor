"use client";

import { useEffect, useRef, type Dispatch, type SetStateAction } from "react";

/**
 * Menu-button behaviour for a small popover: focus the first item on open,
 * close on outside pointer or Escape (returning focus to the trigger), and
 * move between `[role="menuitem"]`s with the arrow keys.
 */
export function useMenuPopover<T extends HTMLElement>(
  open: boolean,
  setOpen: Dispatch<SetStateAction<boolean>>,
) {
  const rootRef = useRef<T>(null);
  useEffect(() => {
    if (!open) return;
    const root = rootRef.current;
    root?.querySelector<HTMLElement>('[role="menuitem"][aria-current="page"], [role="menuitem"]')?.focus();
    const dismiss = (event: PointerEvent) => {
      if (!root?.contains(event.target as Node)) setOpen(false);
    };
    const keys = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        root?.querySelector<HTMLElement>('[aria-haspopup="menu"]')?.focus();
        return;
      }
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      event.preventDefault();
      const items = [...(root?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])];
      const index = items.indexOf(document.activeElement as HTMLElement);
      const next = event.key === "ArrowDown" ? index + 1 : index - 1;
      items[(next + items.length) % items.length]?.focus();
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", keys);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", keys);
    };
  }, [open, setOpen]);
  return rootRef;
}
