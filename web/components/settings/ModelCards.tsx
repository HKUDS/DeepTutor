"use client";

import { Check, ChevronDown, ChevronRight, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import ProviderIcon from "@/components/common/ProviderIcon";
import type {
  CatalogModel,
  CatalogProfile,
  ServiceName,
} from "@/features/settings/store/SettingsStore";

/**
 * The two levels of a model settings page, as cards.
 *
 * A page shows the providers configured for its service; opening one shows
 * the models under it. Cards rather than a list because each one carries more
 * than a name — what it points at, how many models it holds, whether it is the
 * one actually running — and because "open this" and "put this to use" have to
 * be visibly different acts, which a row that does both on click cannot say.
 *
 * The visual language is the one measured off the rest of the app: hairline
 * borders, the accent tint the sidebar uses for its selected row, one radius
 * from the settings scale, no shadows.
 */

export function SectionHead({
  title,
  action,
}: {
  title: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex items-center justify-between gap-2 border-b border-[var(--border)]/60 pb-2">
      <h2 className="text-[13px] font-medium text-[var(--foreground)]">
        {title}
      </h2>
      {action}
    </div>
  );
}

export function CardAction({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)]/50 px-2.5 py-1 text-[12px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)] disabled:opacity-40"
    >
      {children}
    </button>
  );
}

export function CardGrid({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">{children}</div>
  );
}

export function AddCard({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-h-[86px] items-center justify-center gap-1.5 rounded-xl border border-dashed border-[var(--border)] text-[12.5px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--foreground)]/30 hover:bg-[var(--accent)]/30 hover:text-[var(--foreground)]"
    >
      <Plus className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}

/**
 * Shared chrome: the frame, the name row and the expand affordance.
 *
 * A card that opens carries a chevron in its lower-right and lifts its border
 * and tint on hover — without that it read as a panel that happened to be
 * clickable, which is the same as not clickable. Cards that do not open (a
 * search provider has no models under it) draw no chevron, so the two kinds
 * are told apart before you click rather than after.
 */
function CardShell({
  expanded,
  inUse,
  onOpen,
  children,
}: {
  expanded: boolean;
  inUse: boolean;
  onOpen?: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`group relative flex min-h-[86px] flex-col justify-between gap-2 rounded-xl border p-3 transition-[background-color,border-color,transform] duration-150 ${
        expanded
          ? "border-[var(--foreground)]/25 bg-[var(--accent)]/40"
          : inUse
            ? "border-[var(--border)] bg-[var(--accent)]/25"
            : "border-[var(--border)]/70"
      } ${
        onOpen
          ? "cursor-pointer hover:border-[var(--foreground)]/40 hover:bg-[var(--accent)]/45 active:scale-[0.995]"
          : ""
      }`}
      onClick={onOpen}
      role={onOpen ? "button" : undefined}
      tabIndex={onOpen ? 0 : undefined}
      onKeyDown={
        onOpen
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onOpen();
              }
            }
          : undefined
      }
    >
      {children}
      {onOpen && (
        <ChevronRight
          aria-hidden
          className="pointer-events-none absolute bottom-2.5 right-2.5 h-3.5 w-3.5 text-[var(--muted-foreground)]/35 transition-all duration-150 group-hover:translate-x-0.5 group-hover:text-[var(--foreground)]/70"
        />
      )}
    </div>
  );
}

function NameRow({
  icon,
  name,
  renaming,
  renameValue,
  onRenameChange,
  onRenameCommit,
  onRenameCancel,
  onRenameStart,
  expanded,
  onToggleExpand,
  expandLabel,
}: {
  icon?: React.ReactNode;
  name: string;
  renaming: boolean;
  renameValue: string;
  onRenameChange: (value: string) => void;
  onRenameCommit: () => void;
  onRenameCancel: () => void;
  onRenameStart: () => void;
  /** Absent when this card has nothing to expand in place (e.g. a provider
   *  card, which opens a dialog instead). */
  expanded?: boolean;
  onToggleExpand?: () => void;
  expandLabel?: string;
}) {
  if (renaming) {
    return (
      <input
        autoFocus
        value={renameValue}
        onClick={(event) => event.stopPropagation()}
        onChange={(event) => onRenameChange(event.target.value)}
        onBlur={onRenameCommit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") {
            event.preventDefault();
            onRenameCancel();
          }
        }}
        className="w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-1.5 py-0.5 text-[13px] font-medium text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
      />
    );
  }
  return (
    <div className="flex items-start gap-2">
      {icon}
      <span
        onDoubleClick={(event) => {
          event.stopPropagation();
          onRenameStart();
        }}
        className="min-w-0 flex-1 truncate text-[13px] font-medium leading-5 text-[var(--foreground)]"
      >
        {name}
      </span>
      {onToggleExpand && (
        <button
          type="button"
          aria-label={expandLabel}
          aria-expanded={expanded}
          onClick={(event) => {
            event.stopPropagation();
            onToggleExpand();
          }}
          className="-mr-1 -mt-0.5 shrink-0 rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
        >
          <ChevronDown
            className={`h-3.5 w-3.5 transition-transform ${expanded ? "rotate-180" : ""}`}
          />
        </button>
      )}
    </div>
  );
}

/** "In use" is stated; everything else offers to become it. */
export function UseRow({
  inUse,
  onUse,
  detail,
}: {
  inUse: boolean;
  onUse: () => void;
  detail?: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-end justify-between gap-2">
      <span className="min-w-0 truncate text-[11px] text-[var(--muted-foreground)]">
        {detail}
      </span>
      {inUse ? (
        <span className="inline-flex shrink-0 items-center gap-1 text-[11px] font-medium text-[var(--foreground)]">
          <Check className="h-3 w-3" />
          {t("In use")}
        </span>
      ) : (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onUse();
          }}
          className="shrink-0 rounded-md px-1 text-[11px] text-[var(--muted-foreground)] underline-offset-2 transition-colors hover:text-[var(--foreground)] hover:underline"
        >
          {t("Set as active")}
        </button>
      )}
    </div>
  );
}

export function ProfileCard({
  profile,
  service,
  inUse,
  open,
  renaming,
  renameValue,
  onRenameChange,
  onRenameCommit,
  onRenameCancel,
  onRenameStart,
  onOpen,
  onUse,
}: {
  profile: CatalogProfile;
  service: ServiceName;
  inUse: boolean;
  /** Whether this card's dialog is currently open — a purely visual cue,
   *  distinct from `inUse` (which provider is actually running). */
  open: boolean;
  renaming: boolean;
  renameValue: string;
  onRenameChange: (value: string) => void;
  onRenameCommit: () => void;
  onRenameCancel: () => void;
  onRenameStart: () => void;
  onOpen: () => void;
  onUse: () => void;
}) {
  const { t } = useTranslation();
  const provider =
    service === "search" ? profile.provider || "" : profile.binding || "";
  const endpoint = (profile.base_url || "").replace(/^https?:\/\//, "");
  const count = profile.models.length;

  return (
    <CardShell expanded={open} inUse={inUse} onOpen={onOpen}>
      <NameRow
        icon={<ProviderIcon provider={provider} size={15} className="mt-0.5" />}
        name={profile.name}
        renaming={renaming}
        renameValue={renameValue}
        onRenameChange={onRenameChange}
        onRenameCommit={onRenameCommit}
        onRenameCancel={onRenameCancel}
        onRenameStart={onRenameStart}
      />
      <div className="min-w-0">
        <p className="truncate font-mono text-[10.5px] text-[var(--muted-foreground)]/80">
          {endpoint || t("Provider default endpoint")}
        </p>
      </div>
      <div className="pr-5">
        <UseRow
          inUse={inUse}
          onUse={onUse}
          detail={
            service === "search" ? undefined : t("{{count}} models", { count })
          }
        />
      </div>
    </CardShell>
  );
}

export function ModelCard({
  model,
  service,
  language,
  index,
  inUse,
  expanded,
  renaming,
  renameValue,
  onRenameChange,
  onRenameCommit,
  onRenameCancel,
  onRenameStart,
  onToggleExpand,
  onUse,
  onDelete,
}: {
  model: CatalogModel;
  service: ServiceName;
  language: "en" | "zh";
  index: number;
  inUse: boolean;
  expanded: boolean;
  renaming: boolean;
  renameValue: string;
  onRenameChange: (value: string) => void;
  onRenameCommit: () => void;
  onRenameCancel: () => void;
  onRenameStart: () => void;
  onToggleExpand: () => void;
  onUse: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const name =
    (model.name || "").trim() ||
    (language === "zh" ? `模型 ${index + 1}` : `Model ${index + 1}`);
  const detail =
    service === "llm"
      ? model.context_window
        ? t("{{n}} ctx", { n: model.context_window })
        : undefined
      : service === "embedding"
        ? model.dimension
          ? t("{{n}} dim", { n: model.dimension })
          : undefined
        : service === "tts"
          ? model.voice || undefined
          : undefined;

  return (
    <CardShell expanded={expanded} inUse={inUse} onOpen={onToggleExpand}>
      <NameRow
        name={name}
        renaming={renaming}
        renameValue={renameValue}
        onRenameChange={onRenameChange}
        onRenameCommit={onRenameCommit}
        onRenameCancel={onRenameCancel}
        onRenameStart={onRenameStart}
        expanded={expanded}
        onToggleExpand={onToggleExpand}
        expandLabel={t("Edit model")}
      />
      <div className="flex min-w-0 items-center gap-2">
        <p className="min-w-0 flex-1 truncate font-mono text-[10.5px] text-[var(--muted-foreground)]/80">
          {model.model || t("No model id yet")}
        </p>
        <button
          type="button"
          aria-label={t("Delete")}
          onClick={(event) => {
            event.stopPropagation();
            onDelete();
          }}
          className="shrink-0 rounded-md p-1 text-[var(--muted-foreground)]/0 transition-colors hover:bg-[var(--accent)] hover:text-red-500 focus-visible:text-red-500 group-hover:text-[var(--muted-foreground)]/70 max-sm:text-[var(--muted-foreground)]/70"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
      <UseRow inUse={inUse} onUse={onUse} detail={detail} />
    </CardShell>
  );
}
