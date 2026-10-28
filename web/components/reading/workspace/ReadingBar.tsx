"use client";

import "./reading-bar.css";

import {
  Expand,
  FileText,
  Maximize2,
  Minimize2,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  SquarePen,
} from "lucide-react";
import { useCallback, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import Tooltip from "@/shared/ui/Tooltip";
import { FeatureCrumb, InstanceCrumb, type CrumbItem } from "@/components/layout/LocationCrumbs";
import { useShelfFeature } from "@/components/sidebar/PageBar";
import { fetchReadingCollectionIndex, type ReadingWorkspaceTab } from "@/lib/reading-workspace-api";
import { READING_HOME, readingCollectionRoute } from "@/lib/learning-routes";
import type { WorkspaceMenuItem } from "@/components/reading/workspace-menu-context";
import { PageToolButtons, ReadAloudButton } from "./ReadAloudButton";
import { WorkspaceMenu } from "./WorkspaceMenu";

const ICON_BUTTON =
  "flex size-7 shrink-0 items-center justify-center rounded-md transition hover:bg-[var(--muted)] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent";

function BarButton({
  label,
  onClick,
  active = false,
  disabled = false,
  pressed,
  expanded,
  children,
}: {
  label: string;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
  pressed?: boolean;
  expanded?: boolean;
  children: ReactNode;
}) {
  return (
    <Tooltip label={label}>
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={label}
        aria-pressed={pressed}
        aria-expanded={expanded}
        className={`${ICON_BUTTON} ${
          active
            ? "text-[var(--primary)]"
            : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        }`}
      >
        {children}
      </button>
    </Tooltip>
  );
}

/**
 * The reading workspace's one row of chrome, over the document only.
 *
 * Its left half is the location every page states, 「沉浸式阅读 / the
 * collection / the document」: the feature opens onto the other features of
 * the learning shelf, the collection onto the other collections (double-click
 * renames it, as does its menu; its folder page is at the bottom), the document onto the other
 * files in it (adding one is at the top). The reader pane hands its place,
 * history and bookmark up into `docSlot`, after the document. The right half
 * is what can be done with it. The companion keeps its own controls on its
 * own sheet; only the switch that brings it back lives here, and only while
 * it is away.
 */
export function ReadingBar({
  backHref,
  collectionId,
  title,
  onRename,
  onAdd,
  documents,
  activeDocumentId,
  onSwitchDocument,
  navigatorOpen,
  onToggleNavigator,
  docSlot,
  notice,
  materialReady,
  busy,
  onQuiz,
  learning,
  onToggleLearning,
  menuSections,
  collection,
  companionOpen,
  onOpenCompanion,
}: {
  backHref: string;
  collectionId: string;
  title: string;
  onRename: () => void;
  onAdd: () => void;
  documents: ReadingWorkspaceTab[];
  activeDocumentId: string | null;
  onSwitchDocument: (tab: ReadingWorkspaceTab) => void;
  navigatorOpen: boolean;
  onToggleNavigator: () => void;
  docSlot: (node: HTMLDivElement | null) => void;
  notice?: string | null;
  materialReady: boolean;
  busy: boolean;
  onQuiz: () => void;
  learning: boolean;
  onToggleLearning: () => void;
  menuSections: Parameters<typeof WorkspaceMenu>[0]["sections"];
  collection: WorkspaceMenuItem[];
  companionOpen: boolean;
  onOpenCompanion: () => void;
}) {
  const { t } = useTranslation();
  const feature = useShelfFeature(READING_HOME);
  const loadCollections = useCallback(
    async (): Promise<CrumbItem[]> =>
      (await fetchReadingCollectionIndex()).map((collection) => ({
        id: collection.workspace_id,
        label: collection.title || t("Untitled collection"),
        href: readingCollectionRoute(collection.workspace_id),
      })),
    [t],
  );
  const documentItems = useCallback(
    async (): Promise<CrumbItem[]> =>
      documents.map((tab) => ({
        id: tab.material.material_id,
        label: tab.material.title || tab.material.filename,
        icon: FileText,
      })),
    [documents],
  );
  const activeDocument = documents.find((tab) => tab.material.material_id === activeDocumentId);
  return (
    <header className="dt-reading-bar flex h-12 min-w-0 shrink-0 items-center gap-1 bg-[var(--background)] px-3">
      {/* The outline opens on the left, so its switch lives on the left. */}
      <BarButton
        label={navigatorOpen ? t("Collapse contents") : t("Expand contents")}
        onClick={onToggleNavigator}
        active={navigatorOpen}
        expanded={navigatorOpen}
      >
        {navigatorOpen ? <PanelLeftClose size={14} /> : <PanelLeftOpen size={14} />}
      </BarButton>
      <nav aria-label={t("navigation.location")} className="dt-reading-crumbs ml-0.5 flex min-w-0 shrink items-center">
        {feature && <span className="dt-reading-feature hidden md:contents"><FeatureCrumb section={feature.section} page={feature.page} /></span>}
        <span className="dt-reading-collection hidden min-w-0 max-w-[220px] shrink-[2] items-center md:inline-flex">
          <InstanceCrumb
            label={title || t("Untitled collection")}
            menuLabel={t("Collections")}
            currentId={collectionId}
            load={loadCollections}
            onRename={onRename}
            all={{ label: t("Open folder"), href: backHref }}
          />
        </span>
        <span className="flex min-w-0 shrink items-center">
          <InstanceCrumb
            label={activeDocument?.material.title || activeDocument?.material.filename || t("Immersive reading")}
            icon={FileText}
            menuLabel={t("Materials in this collection")}
            currentId={activeDocumentId}
            load={documentItems}
            onSelect={(item) => {
              const tab = documents.find((candidate) => candidate.material.material_id === item.id);
              if (tab) onSwitchDocument(tab);
            }}
            create={{ label: t("Add material"), onSelect: onAdd }}
          />
        </span>
      </nav>
      {/* The open document's place, history and bookmark render here. */}
      <div ref={docSlot} className="dt-reader-head-slot ml-1 flex shrink-0 items-center gap-1" />

      <div className="ml-auto flex shrink-0 items-center gap-0.5">
        {notice && (
          <span className="hidden max-w-[220px] truncate px-2 text-[10px] text-[var(--muted-foreground)] 2xl:inline">
            {notice}
          </span>
        )}
        <ReadAloudButton disabled={!materialReady} />
        <PageToolButtons disabled={!materialReady || busy} onQuiz={onQuiz} />
        <BarButton
          label={t(learning ? "Exit learning mode" : "Fullscreen learning")}
          onClick={onToggleLearning}
          active={learning}
          pressed={learning}
        >
          {learning ? <Minimize2 size={14} /> : <Expand size={14} />}
        </BarButton>
        <WorkspaceMenu sections={menuSections} collection={collection} />
        {!companionOpen && (
          <BarButton label={t("Open the companion")} onClick={onOpenCompanion} expanded={false}>
            <PanelRightOpen size={14} />
          </BarButton>
        )}
      </div>
    </header>
  );
}

/**
 * The top of the companion's sheet: what it is, and its own three controls —
 * start over, take the whole width, put it away.
 */
export function CompanionHead({
  title,
  canStartOver,
  onStartOver,
  focus,
  onClose,
}: {
  title?: string;
  canStartOver: boolean;
  onStartOver: () => void;
  /** Present only where the companion can take the reader's width. */
  focus?: { active: boolean; toggle: () => void };
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="dt-companion-head flex h-12 shrink-0 items-center gap-1 pl-4 pr-2">
      <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-[var(--foreground)]">
        {title?.trim() || t("Reading companion title")}
      </span>
      <BarButton label={t("New conversation")} onClick={onStartOver} disabled={!canStartOver}>
        <SquarePen size={14} />
      </BarButton>
      {focus && (
        <BarButton
          label={focus.active ? t("Exit companion focus") : t("Focus reading companion")}
          onClick={focus.toggle}
          active={focus.active}
          pressed={focus.active}
        >
          {focus.active ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </BarButton>
      )}
      <BarButton label={t("Put the companion away")} onClick={onClose} expanded>
        <PanelRightClose size={14} />
      </BarButton>
    </div>
  );
}
