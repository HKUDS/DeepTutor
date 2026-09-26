"use client";

import {
  Check,
  ChevronDown,
  ChevronRight,
  PencilLine,
  Plus,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import ProviderIcon from "@/components/common/ProviderIcon";
import type { AppLanguage } from "@/i18n/languages";
import type {
  CatalogModel,
  CatalogProfile,
  ServiceName,
} from "@/features/settings/store/SettingsStore";

/** Provider disclosure rows contain connection fields and their model cards.
 * Opening an editor and selecting a runtime model are separate actions;
 * every selection remains a draft until the user applies it. */

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
    <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
      {children}
    </div>
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
  editing = false,
  editorId,
  children,
}: {
  expanded: boolean;
  editing?: boolean;
  editorId?: string;
  inUse: boolean;
  onOpen?: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`group relative flex min-h-[86px] flex-col justify-between gap-2 rounded-xl border p-3 transition-[background-color,border-color,transform] duration-150 ${
        editing
          ? "border-[var(--primary)] bg-[color-mix(in_srgb,var(--primary)_6%,var(--card))] ring-1 ring-[var(--primary)]"
          : expanded
            ? "border-[var(--foreground)]/25 bg-[var(--accent)]/40"
            : inUse
              ? "border-[var(--border)] bg-[var(--accent)]/25"
              : "border-[var(--border)]/70"
      } ${
        onOpen && !editing
          ? "cursor-pointer hover:border-[var(--foreground)]/40 hover:bg-[var(--accent)]/45 active:scale-[0.995]"
          : ""
      }`}
      onClick={onOpen}
      aria-current={editing ? "true" : undefined}
      aria-controls={editorId}
      role={onOpen ? "button" : undefined}
      tabIndex={onOpen ? 0 : undefined}
      onKeyDown={
        onOpen
          ? (event) => {
              if (event.target !== event.currentTarget) return;
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onOpen();
              }
            }
          : undefined
      }
    >
      {children}
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
  status,
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
  status?: React.ReactNode;
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
      {status}
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

/** Labels describe the selection in the draft, before it is applied. */
export function UseRow({
  inUse,
  onUse,
  detail,
  selectLabel,
  selectedLabel,
}: {
  inUse: boolean;
  selectLabel?: string;
  selectedLabel?: string;
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
          {selectedLabel ?? t("Selected")}
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
          {selectLabel ?? t("Select")}
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
  /** Whether this provider's connection fields and models are expanded. */
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
    <div
      className={`flex items-center gap-3 px-4 py-3 ${open ? "bg-[var(--muted)]/40" : ""}`}
    >
      <button
        type="button"
        onClick={onOpen}
        aria-expanded={open}
        className="flex min-w-0 flex-1 items-center gap-3 text-left"
      >
        <ChevronRight
          size={15}
          className={`shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <ProviderIcon provider={provider} size={20} />
        <span className="min-w-0 flex-1">
          <span className="block break-words text-sm font-medium">
            {profile.name}
          </span>
          <span className="block truncate text-xs text-[var(--muted-foreground)]">
            {endpoint || t("Provider default endpoint")}
          </span>
        </span>
        <span className="shrink-0 text-xs text-[var(--muted-foreground)]">
          {t("{{count}} models", { count })}
        </span>
      </button>
      {renaming ? (
        <NameRow
          name={profile.name}
          renaming
          renameValue={renameValue}
          onRenameChange={onRenameChange}
          onRenameCommit={onRenameCommit}
          onRenameCancel={onRenameCancel}
          onRenameStart={onRenameStart}
        />
      ) : (
        <button
          type="button"
          onClick={onRenameStart}
          className="min-h-9 px-1 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        >
          {t("Rename")}
        </button>
      )}
      {service === "search" ? (
        <UseRow inUse={inUse} onUse={onUse} />
      ) : (
        inUse && (
          <Check
            size={15}
            aria-label={t("Selected")}
            className="shrink-0"
          />
        )
      )}
    </div>
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
  editorId,
}: {
  model: CatalogModel;
  editorId?: string;
  service: ServiceName;
  language: AppLanguage;
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
    `${t("Model")} ${index + 1}`;
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
    <CardShell
      expanded={expanded}
      editing={expanded}
      editorId={editorId}
      inUse={inUse}
      onOpen={onToggleExpand}
    >
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
        status={
          expanded ? (
            <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-[var(--primary)] px-2 py-0.5 text-[10px] font-medium text-[var(--primary-foreground)]">
              <PencilLine className="h-3 w-3" aria-hidden="true" />
              {t("Configuring")}
            </span>
          ) : undefined
        }
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
      <UseRow
        inUse={inUse}
        onUse={onUse}
        detail={detail}
        selectLabel={t("Set as default")}
        selectedLabel={t("Default model")}
      />
    </CardShell>
  );
}
