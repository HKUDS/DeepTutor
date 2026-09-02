"use client";

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ChevronDown,
  ChevronRight,
  LayoutGrid,
  Search,
  X,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  isSettingsCategoryVisible,
  isSettingsLeafVisible,
  SETTINGS_CATEGORIES,
  SETTINGS_HUB_HREF,
  settingsAnchorHref,
  type Lang,
  type SettingsLeaf,
} from "@/features/settings/navigation/settings-nav";
import { useSettingsAccess } from "@/features/settings/navigation/SettingsAccessProvider";
import type { SettingsAccess } from "@/features/settings/navigation/settings-access";
import {
  requestSettingsSection,
  scrollToSettingsSection,
} from "@/features/settings/navigation/settings-scroll";
import {
  serviceReadiness,
  useSettings,
} from "@/features/settings/store/SettingsStore";

/**
 * Same-document settings navigation. When already on `/settings`, update the
 * fragment and scroll; otherwise navigate to the canonical document first.
 */
function goToLeaf(
  href: string,
  pathname: string,
  router: ReturnType<typeof useRouter>,
  setActiveSection: (key: string | null) => void,
): boolean {
  const hashIndex = href.indexOf("#");
  if (hashIndex === -1) {
    router.push(href);
    return false;
  }
  const base = href.slice(0, hashIndex);
  const key = href.slice(hashIndex + 1);
  if (base !== pathname) {
    router.push(href);
    return false;
  }
  window.history.replaceState(null, "", href);
  // This document can be tens of thousands of pixels tall. Jumping directly
  // avoids tracking every intermediate section and overwriting the target hash.
  scrollToSettingsSection(key, "auto");
  requestSettingsSection(key);
  setActiveSection(key);
  return true;
}

/**
 * The settings navigator — one persistent column, every page one click away.
 *
 * Settings used to be a folder tree: the hub listed seven categories, four of
 * those opened a second grid, and the leaf was the third click. Changing two
 * things in different categories meant walking back up to the root in between,
 * because nothing but a breadcrumb ever showed where else you could go. Every
 * comparable product — VS Code, Slack, GitHub, Stripe, Dify, Open WebUI —
 * keeps the whole map on screen instead, and so does this.
 *
 * Search filters to matching pages rather than opening a separate results
 * view: with two dozen pages the question is almost always "which page is that
 * on", and the answer is more useful in place.
 */

type Row = { leaf: SettingsLeaf; category: Lang };

type Group = {
  key: string;
  label: Lang;
  href: string;
  icon: LucideIcon;
  rows: Row[];
  standalone: boolean;
};

/**
 * The same map both layouts render. A category with children contributes its
 * leaves; one without is itself a row, so a single-page category never costs
 * an extra level of nesting.
 */
function useGroups(access: SettingsAccess): Group[] {
  return useMemo(
    () =>
      SETTINGS_CATEGORIES.filter((category) =>
        isSettingsCategoryVisible(category, access),
      ).map((category) => ({
        key: category.key,
        label: category.label,
        href: category.href,
        icon: category.icon,
        rows: (
          category.children ?? [
            {
              key: category.key,
              href: category.href,
              label: category.label,
              blurb: category.blurb,
              icon: category.icon,
              tile: "",
            } satisfies SettingsLeaf,
          ]
        )
          .filter((leaf) => isSettingsLeafVisible(leaf, access))
          .map((leaf) => ({ leaf, category: category.label }) satisfies Row),
        standalone: !category.children,
      })),
    [access],
  );
}

/**
 * Narrow-screen navigator.
 *
 * The column is hidden below `md`, and the breadcrumb it replaced is gone, so
 * without this a phone landing on a settings page has no way back to any other
 * one. A native select is the right control here: it groups, it is one tap,
 * and the platform renders it better than anything reimplemented.
 */
export function SettingsNavCompact() {
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const { t, i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = (value: Lang) => (zh ? value.zh : value.en);
  const access = useSettingsAccess();
  const groups = useGroups(access);
  const { activeSection, setActiveSection } = useSettings();
  const currentValue =
    pathname === SETTINGS_HUB_HREF
      ? settingsAnchorHref(activeSection ?? "overview")
      : pathname;

  return (
    <div className="relative md:hidden">
      <select
        value={currentValue}
        aria-label={t("Settings sections")}
        onChange={(event) =>
          goToLeaf(event.target.value, pathname, router, setActiveSection)
        }
        className="w-full appearance-none rounded-lg border border-[var(--border)] bg-[var(--background)] py-2 pl-3 pr-8 text-[13px] font-medium text-[var(--foreground)] outline-none"
      >
        <option value={settingsAnchorHref("overview")}>{t("Overview")}</option>
        {groups.map((group) =>
          group.standalone ? (
            <option
              key={group.key}
              value={settingsAnchorHref(group.rows[0]?.leaf.key ?? group.key)}
            >
              {tr(group.label)}
            </option>
          ) : (
            <optgroup key={group.key} label={tr(group.label)}>
              {group.rows.map(({ leaf }) => (
                <option key={leaf.key} value={settingsAnchorHref(leaf.key)}>
                  {tr(leaf.label)}
                </option>
              ))}
            </optgroup>
          ),
        )}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
    </div>
  );
}

export default function SettingsNav() {
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const { t, i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((value: Lang) => (zh ? value.zh : value.en), [zh]);
  const {
    catalog,
    catalogEditable,
    diagnosticsResults,
    activeSection,
    setActiveSection,
  } = useSettings();

  const [query, setQuery] = useState("");
  const access = useSettingsAccess();
  const groups = useGroups(access);

  const needle = query.trim().toLowerCase();
  const matches = useCallback(
    (row: Row) =>
      !needle ||
      [
        row.leaf.label.en,
        row.leaf.label.zh,
        row.leaf.blurb.en,
        row.leaf.blurb.zh,
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    [needle],
  );

  const visible = groups
    .map((group) => ({ ...group, rows: group.rows.filter(matches) }))
    .filter((group) => group.rows.length > 0);

  // Only the failure state earns a mark here: "not configured yet" is the
  // normal state of most of these services and would dot half the column.
  const failing = useCallback(
    (leaf: SettingsLeaf) =>
      leaf.service !== undefined &&
      catalogEditable === true &&
      serviceReadiness(catalog, leaf.service, diagnosticsResults) === "failed",
    [catalog, catalogEditable, diagnosticsResults],
  );

  // The active section opens its group. A search match also opens every
  // matching group so the requested row is never hidden by a collapse.
  const [manualExpanded, setManualExpanded] = useState<Record<string, boolean>>(
    {},
  );
  const groupIsActive = useCallback(
    (group: Group) =>
      activeSection === group.key ||
      group.rows.some(({ leaf }) => leaf.key === activeSection),
    [activeSection],
  );
  const isExpanded = useCallback(
    (group: Group) =>
      manualExpanded[group.key] ??
      (groupIsActive(group) || (needle !== "" && group.rows.length > 0)),
    [groupIsActive, manualExpanded, needle],
  );

  const navigateInDocument = useCallback(
    (key: string, event: React.MouseEvent<HTMLAnchorElement>) => {
      if (
        goToLeaf(settingsAnchorHref(key), pathname, router, setActiveSection)
      ) {
        event.preventDefault();
      }
    },
    [pathname, router, setActiveSection],
  );

  return (
    <nav
      aria-label={t("Settings sections")}
      className="flex h-full w-[212px] shrink-0 flex-col overflow-y-auto px-1 pb-8"
    >
      <div className="relative mb-2">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]/50" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("Search settings")}
          aria-label={t("Search settings")}
          className="w-full rounded-lg bg-[var(--accent)]/60 py-1.5 pl-8 pr-7 text-[13px] text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)]/50 focus:bg-[var(--accent)]"
        />
        {query && (
          <button
            type="button"
            onClick={() => setQuery("")}
            aria-label={t("Clear")}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            <X className="h-3 w-3" />
          </button>
        )}
      </div>

      <Row
        href={settingsAnchorHref("overview")}
        label={t("Overview")}
        icon={LayoutGrid}
        active={
          pathname === SETTINGS_HUB_HREF &&
          (activeSection === null || activeSection === "overview")
        }
        tourId="tour-nav-overview"
        onClick={(event) => navigateInDocument("overview", event)}
      />

      {visible.length === 0 && (
        <p className="px-2.5 pt-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
          {t("No settings match “{{query}}”.", { query: query.trim() })}
        </p>
      )}

      {visible.map((group) =>
        group.standalone ? (
          <div key={group.key} className="mt-3.5 first:mt-3">
            <Row
              href={settingsAnchorHref(group.rows[0]!.leaf.key)}
              label={tr(group.rows[0]!.leaf.label)}
              icon={group.rows[0]!.leaf.icon}
              active={activeSection === group.rows[0]!.leaf.key}
              failing={failing(group.rows[0]!.leaf)}
              hint={tr(group.rows[0]!.leaf.blurb)}
              tourId={`tour-nav-${group.key}`}
              onClick={(event) =>
                navigateInDocument(group.rows[0]!.leaf.key, event)
              }
            />
          </div>
        ) : (
          <div key={group.key} className="mt-3.5 first:mt-3">
            <CategoryHeaderRow
              href={settingsAnchorHref(group.key)}
              label={tr(group.label)}
              icon={group.icon}
              active={groupIsActive(group)}
              expanded={isExpanded(group)}
              onToggle={() =>
                setManualExpanded((prev) => ({
                  ...prev,
                  [group.key]: !isExpanded(group),
                }))
              }
              tourId={`tour-nav-${group.key}`}
              onClick={(event) => navigateInDocument(group.key, event)}
            />
            {isExpanded(group) && (
              <div className="mt-0.5 space-y-px pl-4">
                {group.rows.map(({ leaf }) => (
                  <Row
                    key={leaf.key}
                    href={settingsAnchorHref(leaf.key)}
                    label={tr(leaf.label)}
                    icon={leaf.icon}
                    active={activeSection === leaf.key}
                    failing={failing(leaf)}
                    hint={tr(leaf.blurb)}
                    onClick={(event) => navigateInDocument(leaf.key, event)}
                  />
                ))}
              </div>
            )}
          </div>
        ),
      )}
    </nav>
  );
}

/**
 * A category with children, promoted to the same tier as a single-leaf
 * category (Appearance, Network, …) rather than a smaller, unclickable label
 * above them — it links to the merged page, and a separate chevron button
 * (a sibling, not nested in the link, since a button cannot nest inside an
 * anchor) collapses the list of leaves under it.
 */
function CategoryHeaderRow({
  href,
  label,
  icon: Icon,
  active,
  expanded,
  onToggle,
  tourId,
  onClick,
}: {
  href: string;
  label: string;
  icon: LucideIcon;
  active: boolean;
  expanded: boolean;
  onToggle: () => void;
  tourId?: string;
  onClick?: (event: React.MouseEvent<HTMLAnchorElement>) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-0.5">
      <Link
        href={href}
        data-tour={tourId}
        onClick={onClick}
        aria-current={active ? "page" : undefined}
        className={`flex min-w-0 flex-1 items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] leading-tight transition-colors ${
          active
            ? "bg-[var(--accent)] font-medium text-[var(--foreground)]"
            : "text-[var(--foreground)]/70 hover:bg-[var(--accent)]/50 hover:text-[var(--foreground)]"
        }`}
      >
        <Icon size={15} className={`shrink-0 ${active ? "" : "opacity-70"}`} />
        <span className="min-w-0 flex-1 truncate">{label}</span>
      </Link>
      <button
        type="button"
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          onToggle();
        }}
        aria-label={expanded ? t("Collapse") : t("Expand")}
        aria-expanded={expanded}
        className="shrink-0 rounded-lg p-1.5 text-[var(--muted-foreground)]/60 transition-colors hover:bg-[var(--accent)]/50 hover:text-[var(--foreground)]"
      >
        <ChevronRight
          className={`h-3.5 w-3.5 transition-transform ${expanded ? "rotate-90" : ""}`}
        />
      </button>
    </div>
  );
}

/**
 * One row, in the app sidebar's language rather than an invented one: the same
 * icon + label pairing, radius, padding and accent-tinted active state that
 * `SidebarShell` uses, a half-step smaller because this is second-level
 * navigation. Without the icon the column was a wall of text with nothing to
 * aim at, and every page already declares one in `settings-nav.ts`.
 */
function Row({
  href,
  label,
  icon: Icon,
  active,
  failing,
  hint,
  tourId,
  onClick,
}: {
  href: string;
  label: string;
  icon?: LucideIcon;
  active: boolean;
  failing?: boolean;
  /** The one-line description the old sub-hub tiles showed under each name. */
  hint?: string;
  /** Only the first row of a group carries it, so the tour lands on the group. */
  tourId?: string;
  /** A merged-category leaf intercepts the click to scroll in place instead
   *  of navigating, when it is already the page on screen. */
  onClick?: (event: React.MouseEvent<HTMLAnchorElement>) => void;
}) {
  return (
    <Link
      href={href}
      data-tour={tourId}
      title={hint}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={`flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] leading-tight transition-colors ${
        active
          ? "bg-[var(--accent)] font-medium text-[var(--foreground)]"
          : "text-[var(--foreground)]/70 hover:bg-[var(--accent)]/50 hover:text-[var(--foreground)]"
      }`}
    >
      {Icon && (
        <Icon size={15} className={`shrink-0 ${active ? "" : "opacity-70"}`} />
      )}
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {failing && (
        <span
          aria-hidden
          className="h-1.5 w-1.5 shrink-0 rounded-full bg-red-400"
        />
      )}
    </Link>
  );
}
