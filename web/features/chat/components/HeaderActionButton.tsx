"use client";

import { forwardRef } from "react";
import type { LucideIcon } from "lucide-react";

import Tooltip from "@/shared/ui/Tooltip";

const FILLED_ACTIVE =
  "bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-[var(--primary)]";
const FILLED_OPEN =
  "bg-[color-mix(in_srgb,var(--muted)_70%,transparent)] text-[var(--foreground)]";
const IDLE =
  "text-[var(--muted-foreground)] hover:bg-[color-mix(in_srgb,var(--muted)_55%,transparent)] hover:text-[var(--foreground)] disabled:hover:bg-transparent disabled:hover:text-[var(--muted-foreground)]";

/**
 * A bare icon in the chat header: no shell, a hover fill, its name in the
 * tooltip. ``menuOpen`` marks a button that opens a menu — it then reads as
 * pressed while the menu is up, and its tooltip yields to the menu.
 */
const HeaderActionButton = forwardRef<
  HTMLButtonElement,
  {
    onClick: () => void;
    disabled?: boolean;
    active?: boolean;
    icon: LucideIcon;
    label: string;
    title?: string;
    menuOpen?: boolean;
  }
>(function HeaderActionButton(
  { onClick, disabled, active, icon: Icon, label, title, menuOpen },
  ref,
) {
  const opensMenu = menuOpen !== undefined;
  return (
    <Tooltip label={title ?? label} side="bottom" suppressed={menuOpen}>
      <button
        ref={ref}
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={label}
        aria-pressed={opensMenu ? undefined : active}
        aria-haspopup={opensMenu ? "menu" : undefined}
        aria-expanded={opensMenu ? menuOpen : undefined}
        className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-[background-color,color,transform] duration-150 active:scale-90 disabled:cursor-not-allowed disabled:opacity-40 ${
          menuOpen ? FILLED_OPEN : active ? FILLED_ACTIVE : IDLE
        }`}
      >
        <Icon size={16} strokeWidth={1.7} className="shrink-0" />
      </button>
    </Tooltip>
  );
});

export default HeaderActionButton;
