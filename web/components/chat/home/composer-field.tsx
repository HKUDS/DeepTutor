import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";

export const INPUT_CLS =
  "h-[30px] rounded-lg border border-[var(--border)]/30 bg-[var(--background)]/50 px-2.5 text-[12px] text-[var(--foreground)] outline-none transition-colors hover:border-[var(--border)]/50 focus:border-[var(--primary)]/35 placeholder:text-[var(--muted-foreground)]/40";

export function Field({
  label,
  width,
  children,
}: {
  label: string;
  width?: string;
  children: ReactNode;
}) {
  return (
    <label className={`flex min-w-0 flex-col ${width || ""}`}>
      <span className="mb-0.5 text-[10px] font-medium text-[var(--muted-foreground)]/60">
        {label}
      </span>
      {children}
    </label>
  );
}

/**
 * Shared header used by every capability-specific config panel
 * (Quiz / Math Animator / Visualize / Deep Research).
 *
 * The body is hidden when `collapsed` is true; a one-line summary is shown
 * next to the chevron so the user can verify the current settings without
 * expanding the panel.
 */
export function CollapsibleConfigSection({
  collapsed,
  summary,
  onToggleCollapsed,
  bodyClassName,
  children,
}: {
  collapsed: boolean;
  summary?: string;
  onToggleCollapsed: () => void;
  bodyClassName?: string;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <button
        type="button"
        onClick={onToggleCollapsed}
        className="flex w-full items-center gap-1.5 px-3.5 py-1.5 text-start transition-colors hover:opacity-80"
      >
        <ChevronDown
          size={10}
          className={`shrink-0 text-[var(--muted-foreground)]/40 transition-transform ${collapsed ? "-rotate-90" : ""}`}
        />
        <span className="text-[10px] font-medium text-[var(--muted-foreground)]/55">
          {t("Settings")}
        </span>
        {collapsed && summary && (
          <span className="min-w-0 truncate text-[10px] text-[var(--muted-foreground)]/30">
            — {summary}
          </span>
        )}
      </button>
      {!collapsed && (
        <div className={bodyClassName ?? "px-3.5 pb-2.5"}>{children}</div>
      )}
    </div>
  );
}
