"use client";

import { browserStorage } from "@/shared/storage";

/**
 * The workspace feature list — the part of the sidebar a learner owns.
 *
 * Every learner uses a different half of DeepTutor, so the shipped list is a
 * starting point rather than a layout: rows can be dragged into the order the
 * work actually happens in, and the ones this learner never opens fold away
 * into "More" instead of sitting in the way. The arrangement is a per-machine
 * view preference (``lib/sidebar-layout.ts``), and no feature is ever lost —
 * folding moves it one click away, it does not remove it, and the collapsed
 * rail keeps its own way to reach the folded ones.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { createPortal } from "react-dom";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ChevronDown,
  Lock,
  MoreHorizontal,
  RotateCcw,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { useCapabilityAccess } from "@/components/access/CapabilityAccessContext";
import {
  NAV_BY_HREF,
  PRIMARY_NAV_HREFS,
  isNavActive,
} from "@/components/sidebar/nav-entries";
import { Tooltip } from "@/components/ui/Tooltip";
import { useDragSort, type DragSort } from "@/hooks/useDragSort";
import { placeMenu, type FloatingMenuPosition } from "@/lib/floating-menu";
import {
  DEFAULT_NAV_LAYOUT,
  readNavLayout,
  reorderNavSection,
  resolveNavLayout,
  setNavCollapsed,
  writeNavLayout,
  type SidebarNavLayout,
} from "@/lib/sidebar-layout";

const MORE_EXPANDED_KEY = "deeptutor.sidebar.moreExpanded";
/** One curve and one duration for every part of the "More" disclosure, so the
 *  caret, the height and the count settle on the same beat. The curve is a
 *  fast-out/long-settle ease — the same shape sheet UIs use — which reads as
 *  crisper than ``ease-out`` at this size. */
const EASE_CLASS =
  "duration-[220ms] ease-[cubic-bezier(0.32,0.72,0,1)] motion-reduce:transition-none";
const MENU_WIDTH = 210;

interface RowMenu {
  href: string;
  folded: boolean;
  position: FloatingMenuPosition;
}

interface SidebarNavProps {
  /** Icon-only rail. Rows there are not arrangeable — see the rail branch. */
  collapsed: boolean;
  /** Home resets to a fresh session rather than just navigating. */
  onHomeClick: (event: React.MouseEvent) => void;
  /** Dismisses the mobile drawer on in-place navigation. */
  onNavigate: (event: React.MouseEvent) => void;
}

export function SidebarNav({
  collapsed,
  onHomeClick,
  onNavigate,
}: SidebarNavProps) {
  const pathname = usePathname();
  const { t } = useTranslation();
  const { has } = useCapabilityAccess();

  const [layout, setLayout] = useState<SidebarNavLayout>(DEFAULT_NAV_LAYOUT);
  const [moreExpanded, setMoreExpanded] = useState(false);
  const [menu, setMenu] = useState<RowMenu | null>(null);
  const [railMenu, setRailMenu] = useState<FloatingMenuPosition | null>(null);
  const menuRootRef = useRef<HTMLDivElement>(null);
  const menuAnchorRef = useRef<HTMLElement | null>(null);

  // Hydrate after first paint so the server and the client agree on the
  // shipped order, then settle into this machine's arrangement.
  useEffect(() => {
    if (typeof window === "undefined") return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLayout(readNavLayout());
    setMoreExpanded(browserStorage.readRaw("local", MORE_EXPANDED_KEY) === "1");
  }, []);

  const resolved = useMemo(
    () => resolveNavLayout(PRIMARY_NAV_HREFS, layout),
    [layout],
  );
  /** Always edit the resolved order: the stored one may still be empty. */
  const editable = useMemo<SidebarNavLayout>(
    () => ({ order: resolved.order, collapsed: resolved.collapsed }),
    [resolved],
  );

  const applyLayout = useCallback((next: SidebarNavLayout) => {
    setLayout(next);
    writeNavLayout(next);
  }, []);

  const showMore = useCallback((next: boolean) => {
    setMoreExpanded(next);
    if (typeof window !== "undefined") {
      browserStorage.writeRaw("local", MORE_EXPANDED_KEY, next ? "1" : "0");
    }
  }, []);

  const closeMenus = useCallback(() => {
    setMenu(null);
    setRailMenu(null);
    menuAnchorRef.current = null;
  }, []);

  const visibleDrag = useDragSort({
    ids: resolved.visible,
    disabled: collapsed,
    onReorder: (next) =>
      applyLayout(reorderNavSection(editable, resolved.visible, next)),
  });
  const foldedDrag = useDragSort({
    ids: resolved.collapsed,
    disabled: collapsed,
    onReorder: (next) =>
      applyLayout(reorderNavSection(editable, resolved.collapsed, next)),
  });

  useEffect(() => {
    if (!menu && !railMenu) return;
    const closeOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        !menuRootRef.current?.contains(target) &&
        !menuAnchorRef.current?.contains(target)
      ) {
        closeMenus();
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeMenus();
    };
    const closeOnViewportChange = (event: Event) => {
      const target = event.target;
      if (target instanceof Node && menuRootRef.current?.contains(target))
        return;
      closeMenus();
    };
    document.addEventListener("mousedown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", closeMenus);
    window.addEventListener("scroll", closeOnViewportChange, true);
    return () => {
      document.removeEventListener("mousedown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("resize", closeMenus);
      window.removeEventListener("scroll", closeOnViewportChange, true);
    };
  }, [closeMenus, menu, railMenu]);

  const lockedTooltip = t("Locked — contact your administrator to get access.");
  const isLocked = (href: string) => {
    const requires = NAV_BY_HREF.get(href)?.requires;
    return requires ? !has(requires) : false;
  };

  /* ---- Icon-only rail ----
   * No arranging here: the rail is 60px of icons with no room for a menu or a
   * drop target. It honours the order and the folding, and reaches the folded
   * features through one overflow button so nothing becomes unreachable. */
  if (collapsed) {
    return (
      <nav className="mt-1 flex w-full flex-col items-center gap-1 px-1.5">
        {resolved.visible.map((href) => (
          <RailRow
            key={href}
            href={href}
            active={isNavActive(pathname, href)}
            locked={isLocked(href)}
            lockedTooltip={lockedTooltip}
            onHomeClick={onHomeClick}
          />
        ))}
        {resolved.collapsed.length > 0 ? (
          <Tooltip label={t("More")} side="right">
            <button
              type="button"
              onClick={(event) => {
                if (railMenu) {
                  closeMenus();
                  return;
                }
                menuAnchorRef.current = event.currentTarget;
                setRailMenu(
                  placeMenu(
                    event.currentTarget.getBoundingClientRect(),
                    MENU_WIDTH,
                  ),
                );
              }}
              aria-label={t("More")}
              aria-haspopup="menu"
              aria-expanded={Boolean(railMenu)}
              className={`flex h-9 w-9 items-center justify-center rounded-xl transition-all duration-150 ${
                railMenu
                  ? "bg-[var(--accent)] text-[var(--foreground)]"
                  : "text-[var(--foreground)]/60 hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]"
              }`}
            >
              <MoreHorizontal size={18} strokeWidth={1.6} />
            </button>
          </Tooltip>
        ) : null}
        {railMenu && typeof document !== "undefined"
          ? createPortal(
              <FloatingPanel
                ref={menuRootRef}
                position={railMenu}
                label={t("More")}
              >
                {resolved.collapsed.map((href) => {
                  const entry = NAV_BY_HREF.get(href);
                  if (!entry) return null;
                  const locked = isLocked(href);
                  const Icon = entry.icon;
                  return locked ? (
                    <span
                      key={href}
                      aria-disabled
                      className="flex cursor-not-allowed items-center gap-2 rounded-lg px-2 py-1.5 text-[var(--muted-foreground)]/45"
                    >
                      <Icon size={14} strokeWidth={1.6} />
                      <span className="min-w-0 flex-1 truncate">
                        {t(entry.label)}
                      </span>
                      <Lock size={11} strokeWidth={1.8} />
                    </span>
                  ) : (
                    <Link
                      key={href}
                      href={href}
                      onClick={(event) => {
                        closeMenus();
                        if (href === "/chat") onHomeClick(event);
                        else onNavigate(event);
                      }}
                      role="menuitem"
                      className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
                    >
                      <Icon size={14} strokeWidth={1.6} />
                      <span className="min-w-0 flex-1 truncate">
                        {t(entry.label)}
                      </span>
                    </Link>
                  );
                })}
              </FloatingPanel>,
              document.body,
            )
          : null}
      </nav>
    );
  }

  /* ---- Expanded list ---- */
  const openRowMenu =
    (href: string, folded: boolean) => (event: React.MouseEvent) => {
      event.preventDefault();
      event.stopPropagation();
      if (menu?.href === href) {
        closeMenus();
        return;
      }
      const anchor = event.currentTarget as HTMLElement;
      menuAnchorRef.current = anchor;
      setRailMenu(null);
      setMenu({
        href,
        folded,
        position: placeMenu(anchor.getBoundingClientRect(), MENU_WIDTH),
      });
    };

  const renderRow = (href: string, drag: DragSort, folded: boolean) => {
    const entry = NAV_BY_HREF.get(href);
    if (!entry) return null;
    const active = isNavActive(pathname, href);
    const locked = isLocked(href);
    const dragging = drag.draggingId === href;
    const menuOpen = menu?.href === href;
    const Icon = entry.icon;
    const { style, ...handlers } = drag.getItemProps(href);
    const label = t(entry.label);
    const body = (
      <Fragment key={`${href}-content`}>
        <Icon size={16} strokeWidth={active ? 1.9 : 1.5} className="shrink-0" />
        <span className="min-w-0 flex-1 truncate">{label}</span>
        {locked ? (
          <Lock size={13} strokeWidth={1.8} className="shrink-0" />
        ) : null}
      </Fragment>
    );
    const rowClass =
      "flex items-center gap-2.5 rounded-lg py-2 pl-3 pr-8 text-[13.5px] transition-colors";

    return (
      <div
        {...handlers}
        key={href}
        style={style as CSSProperties}
        className={`group/nav relative rounded-lg ${
          dragging
            ? "bg-[var(--secondary)] shadow-lg ring-1 ring-[var(--border)]/70"
            : ""
        }`}
      >
        {locked ? (
          <Tooltip
            key={`${href}-destination`}
            label={label}
            description={lockedTooltip}
            side="right"
          >
            <div
              aria-label={`${label} — ${lockedTooltip}`}
              aria-disabled
              className={`${rowClass} cursor-not-allowed text-[var(--muted-foreground)]/40`}
            >
              {body}
            </div>
          </Tooltip>
        ) : (
          <Link
            key={`${href}-destination`}
            href={href}
            draggable={false}
            onClick={href === "/chat" ? onHomeClick : onNavigate}
            className={`${rowClass} ${
              active
                ? "bg-[var(--accent)] font-medium text-[var(--foreground)]"
                : "text-[var(--foreground)]/85 hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]"
            }`}
          >
            {body}
          </Link>
        )}
        <button
          key={`${href}-arrange`}
          type="button"
          data-no-drag
          onClick={openRowMenu(href, folded)}
          aria-label={t("Arrange {{feature}}", { feature: label })}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          className={`absolute right-1 top-1/2 -translate-y-1/2 rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)]/70 hover:text-[var(--foreground)] ${
            menuOpen
              ? "opacity-100"
              : "opacity-0 focus-visible:opacity-100 group-hover/nav:opacity-100"
          }`}
        >
          <MoreHorizontal size={13} />
        </button>
      </div>
    );
  };

  return (
    <nav className="px-2 pt-1">
      <div className="space-y-px">
        {resolved.visible.map((href) => (
          <Fragment key={href}>{renderRow(href, visibleDrag, false)}</Fragment>
        ))}
      </div>

      {resolved.collapsed.length > 0 ? (
        <div className="mt-1">
          {/* A group heading, not a ninth feature: it sits a step down from the
              rows above it in size, weight and hover, and its caret rides a
              16px slot so the label still lands on the same 38px text column
              the features do. */}
          <button
            type="button"
            onClick={() => showMore(!moreExpanded)}
            aria-expanded={moreExpanded}
            // Grey by default, foreground on hover. The colour IS the hover
            // feedback here: `[var(--x)]/NN` emits no rule at all (the theme
            // vars are hex, so Tailwind cannot mix an alpha into them), which
            // is why the feature rows above have no hover state — a repo-wide
            // issue, not one to fix behind this heading alone.
            className="group/more flex w-full items-center gap-2.5 rounded-lg px-3 py-1.5 text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            <span className="flex w-4 shrink-0 items-center justify-center">
              <ChevronDown
                size={13}
                strokeWidth={1.8}
                className={`${EASE_CLASS} transition-transform ${
                  moreExpanded ? "" : "-rotate-90"
                }`}
              />
            </span>
            <span className="min-w-0 flex-1 truncate text-left">
              {t("More")}
            </span>
            {/* Fades and shrinks away rather than vanishing — the count answers
                "how much is hidden", a question the open group answers itself. */}
            <span
              aria-hidden={moreExpanded}
              className={`${EASE_CLASS} shrink-0 text-[10.5px] tabular-nums transition-all ${
                moreExpanded
                  ? "scale-75 opacity-0"
                  : "opacity-45 group-hover/more:opacity-70"
              }`}
            >
              {resolved.collapsed.length}
            </span>
          </button>
          <div
            className={`${EASE_CLASS} grid transition-[grid-template-rows] ${
              moreExpanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
            }`}
          >
            {/* Clipping is what gives the row its height animation, but it
                would also shear the row lifted out of this list by a drag —
                so the drag turns it off, by which point the group is open and
                there is nothing left to clip. */}
            <div
              className={
                foldedDrag.draggingId ? "overflow-visible" : "overflow-hidden"
              }
            >
              {/* The rows fade in a beat after the group starts opening, so it
                  reads as a door opening rather than a block appearing. */}
              <div
                className={`space-y-px pt-px transition-opacity duration-150 motion-reduce:transition-none ${
                  moreExpanded ? "opacity-100 delay-[80ms]" : "opacity-0"
                }`}
              >
                {resolved.collapsed.map((href) => (
                  <Fragment key={href}>
                    {renderRow(href, foldedDrag, true)}
                  </Fragment>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {menu && typeof document !== "undefined"
        ? createPortal(
            <FloatingPanel
              ref={menuRootRef}
              position={menu.position}
              label={t("Arrange sidebar")}
            >
              <MenuRow
                icon={menu.folded ? ArrowUpFromLine : ArrowDownToLine}
                label={menu.folded ? t("Move out of More") : t("Move to More")}
                onClick={() => {
                  applyLayout(
                    setNavCollapsed(editable, menu.href, !menu.folded),
                  );
                  // Folding something shows where it went; unfolding leaves the
                  // group open so the next one is one click away.
                  showMore(true);
                  closeMenus();
                }}
              />
              {resolved.customized ? (
                <>
                  <div className="my-1 border-t border-[var(--border)]/70" />
                  <MenuRow
                    icon={RotateCcw}
                    label={t("Reset sidebar order")}
                    onClick={() => {
                      applyLayout(DEFAULT_NAV_LAYOUT);
                      closeMenus();
                    }}
                  />
                </>
              ) : null}
            </FloatingPanel>,
            document.body,
          )
        : null}
    </nav>
  );
}

function RailRow({
  href,
  active,
  locked,
  lockedTooltip,
  onHomeClick,
}: {
  href: string;
  active: boolean;
  locked: boolean;
  lockedTooltip: string;
  onHomeClick: (event: React.MouseEvent) => void;
}) {
  const { t } = useTranslation();
  const entry = NAV_BY_HREF.get(href);
  if (!entry) return null;
  const Icon = entry.icon;
  const label = t(entry.label);
  const description = locked
    ? lockedTooltip
    : entry.tooltipKey
      ? t(entry.tooltipKey)
      : undefined;

  if (locked) {
    return (
      <Tooltip label={label} description={description} side="right">
        <div
          aria-label={`${label} — ${lockedTooltip}`}
          aria-disabled
          className="relative flex h-9 w-9 cursor-not-allowed items-center justify-center rounded-xl text-[var(--muted-foreground)]/40"
        >
          <Icon size={18} strokeWidth={1.6} />
          <Lock
            size={10}
            strokeWidth={2}
            className="absolute bottom-1 right-1 text-[var(--muted-foreground)]/70"
          />
        </div>
      </Tooltip>
    );
  }

  return (
    <Tooltip label={label} description={description} side="right">
      <Link
        href={href}
        onClick={href === "/chat" ? onHomeClick : undefined}
        aria-label={label}
        className={`relative flex h-9 w-9 items-center justify-center rounded-xl transition-all duration-150 ${
          active
            ? "bg-[var(--accent)] text-[var(--foreground)] shadow-sm"
            : "text-[var(--foreground)]/85 hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]"
        }`}
      >
        <Icon size={18} strokeWidth={active ? 2 : 1.6} />
      </Link>
    </Tooltip>
  );
}

function FloatingPanel({
  ref,
  position,
  label,
  children,
}: {
  ref: React.RefObject<HTMLDivElement | null>;
  position: FloatingMenuPosition;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div
      ref={ref}
      role="menu"
      aria-label={label}
      style={{
        left: position.left,
        top: position.top,
        maxHeight: position.maxHeight,
        transform: position.openUpward ? "translateY(-100%)" : undefined,
        transformOrigin: position.openUpward ? "bottom" : "top",
      }}
      className="fixed z-[100] overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--popover)] p-1.5 text-[12px] shadow-xl"
    >
      <div style={{ width: MENU_WIDTH - 12 }}>{children}</div>
    </div>
  );
}

function MenuRow({
  icon: Icon,
  label,
  onClick,
}: {
  icon: typeof RotateCcw;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
    >
      <Icon size={13} strokeWidth={1.7} className="shrink-0" />
      <span className="min-w-0 flex-1 truncate">{label}</span>
    </button>
  );
}
