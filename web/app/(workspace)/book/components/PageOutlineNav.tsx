"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  AlignLeft,
  BookOpen,
  ChevronRight,
  Code2,
  FileText,
  Film,
  Image as ImageIcon,
  Layers,
  ListChecks,
  Loader2,
  type LucideIcon,
  MessageCircle,
  MousePointerClick,
  Sparkles,
  Sticker,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Block, BlockType, BlockStatus } from "@/lib/book-types";

const TYPE_ICON: Record<BlockType, LucideIcon> = {
  text: AlignLeft,
  section: BookOpen,
  callout: Sparkles,
  quiz: ListChecks,
  user_note: FileText,
  figure: ImageIcon,
  interactive: MousePointerClick,
  animation: Film,
  code: Code2,
  timeline: Layers,
  flash_cards: Sticker,
  deep_dive: MessageCircle,
  concept_graph: Layers,
};

const TYPE_LABEL_EN: Record<BlockType, string> = {
  text: "Text",
  section: "Section",
  callout: "Callout",
  quiz: "Quiz",
  user_note: "Note",
  figure: "Figure",
  interactive: "Interactive",
  animation: "Animation",
  code: "Code",
  timeline: "Timeline",
  flash_cards: "Flash cards",
  deep_dive: "Deep dive",
  concept_graph: "Concept graph",
};

function shortLabel(block: Block, fallback: string): string {
  const title = (block.title || "").trim();
  if (title) return title;
  const params = (block.params || {}) as Record<string, unknown>;
  const focus = typeof params.focus === "string" ? params.focus.trim() : "";
  if (focus) return focus;
  const role = typeof params.role === "string" ? params.role.trim() : "";
  if (role) return `${fallback} · ${role}`;
  const variant =
    typeof params.variant === "string" ? params.variant.trim() : "";
  if (variant) return `${fallback} · ${variant}`;
  return fallback;
}

function statusDotClass(status: BlockStatus): string {
  switch (status) {
    case "ready":
      return "bg-emerald-500";
    case "generating":
      return "bg-amber-400 animate-pulse";
    case "pending":
      return "bg-[var(--muted-foreground)]/40";
    case "error":
      return "bg-rose-500";
    case "hidden":
      return "bg-[var(--muted-foreground)]/20";
    default:
      return "bg-[var(--muted-foreground)]/40";
  }
}

export interface PageOutlineNavProps {
  blocks: Block[];
  scrollContainer?: HTMLElement | null;
  language?: string;
}

export default function PageOutlineNav({
  blocks,
  scrollContainer,
  language: _language,
}: PageOutlineNavProps) {
  const { t } = useTranslation();
  const headerText = t("On this page");
  const collapseTip = t("Hide outline");
  const expandTip = t("Show outline");

  // Default: expanded; PageReader keys this component by page id.
  const [collapsed, setCollapsed] = useState(false);

  // Track which block is currently in view for active highlight.
  const [activeId, setActiveId] = useState<string | null>(null);
  const visibleBlocks = useMemo(
    () => blocks.filter((b) => b.status !== "hidden"),
    [blocks],
  );

  useEffect(() => {
    if (!scrollContainer || visibleBlocks.length === 0) return;
    const ids = visibleBlocks.map((b) => `block-${b.id}`);
    const elements = ids
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => !!el);
    if (elements.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        // Pick the entry closest to the top of the viewport that is intersecting.
        const intersecting = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (intersecting.length > 0) {
          const id = intersecting[0].target.id.replace(/^block-/, "");
          setActiveId(id);
        }
      },
      {
        root: scrollContainer,
        rootMargin: "-20% 0px -65% 0px",
        threshold: 0,
      },
    );
    elements.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [scrollContainer, visibleBlocks]);

  const handleJump = (blockId: string) => {
    const el = document.getElementById(`block-${blockId}`);
    if (!el) return;
    setActiveId(blockId);
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  if (visibleBlocks.length === 0) return null;

  // Smooth easing tuned to feel natural — same curve framer-motion uses for
  // its `easeOut` token, just expressed as a CSS bezier.
  const EASE = "cubic-bezier(0.22, 1, 0.36, 1)";

  return (
    <div
      className="pointer-events-none absolute right-0 top-1/2 z-20 -translate-y-1/2"
      style={{ transition: `transform 320ms ${EASE}` }}
    >
      {/* Single morphing card. Width / border-radius / x-translate transition
          between slim-handle and full-nav, while the inner nav drives the
          card's height naturally via max-height (so it never balloons past
          its own content). */}
      <div
        className={[
          "pointer-events-auto relative overflow-hidden border border-[var(--border)] bg-[var(--card)]/85 shadow-md backdrop-blur",
          collapsed ? "w-6 rounded-l-md border-r-0" : "w-56 rounded-xl",
        ].join(" ")}
        style={{
          transition: [
            `width 320ms ${EASE}`,
            `border-radius 320ms ${EASE}`,
            `transform 320ms ${EASE}`,
            `box-shadow 200ms ease-out`,
          ].join(", "),
          transform: collapsed ? "translateX(0)" : "translateX(-12px)",
        }}
      >
        {/* ── Expanded content: full outline list. Stays in flow so its
            height drives the parent card; collapses to 64px (matches
            handle height) via max-height when hidden. The fixed inner
            width keeps content laid out during the width transition; the
            parent overflow:hidden clips it cleanly. */}
        <nav
          aria-label={headerText}
          aria-hidden={collapsed}
          className={[
            "flex w-56 flex-col text-[12.5px]",
            collapsed ? "pointer-events-none" : "pointer-events-auto",
          ].join(" ")}
          style={{
            maxHeight: collapsed ? "64px" : "min(70vh, 520px)",
            opacity: collapsed ? 0 : 1,
            transform: collapsed ? "translateX(8px)" : "translateX(0)",
            transition: collapsed
              ? `max-height 320ms ${EASE}, opacity 140ms ease-out, transform 220ms ${EASE}`
              : `max-height 320ms ${EASE}, opacity 220ms ease-out 100ms, transform 320ms ${EASE} 60ms`,
          }}
        >
          <div className="flex items-center justify-between gap-2 border-b border-[var(--border)] px-3 py-2">
            <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-[var(--muted-foreground)]">
              <Layers className="h-3 w-3" />
              <span>{headerText}</span>
            </div>
            <button
              type="button"
              onClick={() => setCollapsed(true)}
              title={collapseTip}
              aria-label={collapseTip}
              className="rounded p-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)] hover:text-[var(--foreground)]"
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>

          <ol className="flex-1 overflow-y-auto px-1.5 py-1.5">
            {visibleBlocks.map((block, idx) => {
              const Icon = TYPE_ICON[block.type] || FileText;
              const fallbackLabel = t(TYPE_LABEL_EN[block.type] || block.type);
              const label = shortLabel(block, fallbackLabel);
              const isActive = block.id === activeId;
              const isError = block.status === "error";
              const isLoading =
                block.status === "pending" || block.status === "generating";

              return (
                <li key={block.id}>
                  <button
                    type="button"
                    onClick={() => handleJump(block.id)}
                    className={[
                      "group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors duration-150",
                      isActive
                        ? "bg-[var(--primary)]/10 text-[var(--foreground)]"
                        : "text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)]",
                    ].join(" ")}
                  >
                    <span
                      className={[
                        "shrink-0 transition-colors",
                        isActive
                          ? "text-[var(--primary)]"
                          : "text-[var(--muted-foreground)] group-hover:text-[var(--foreground)]",
                      ].join(" ")}
                    >
                      {isLoading ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : isError ? (
                        <AlertCircle className="h-3.5 w-3.5 text-rose-500" />
                      ) : (
                        <Icon className="h-3.5 w-3.5" />
                      )}
                    </span>
                    <span className="flex min-w-0 flex-1 items-center gap-1.5">
                      <span className="shrink-0 text-[10.5px] tabular-nums text-[var(--muted-foreground)]/70">
                        {String(idx + 1).padStart(2, "0")}
                      </span>
                      <span
                        className="truncate"
                        title={`${fallbackLabel} · ${label}`}
                      >
                        {label}
                      </span>
                    </span>
                    <span
                      className={[
                        "shrink-0 h-1.5 w-1.5 rounded-full",
                        statusDotClass(block.status),
                      ].join(" ")}
                    />
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>

        {/* ── Collapsed handle: chevron-only button overlays the same card  */}
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          title={expandTip}
          aria-label={expandTip}
          aria-hidden={!collapsed}
          tabIndex={collapsed ? 0 : -1}
          className={[
            "group absolute inset-0 flex items-center justify-center text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]",
            collapsed ? "pointer-events-auto" : "pointer-events-none",
          ].join(" ")}
          style={{
            opacity: collapsed ? 1 : 0,
            transform: collapsed ? "translateX(0)" : "translateX(-6px)",
            transition: collapsed
              ? `opacity 220ms ease-out 120ms, transform 320ms ${EASE} 80ms`
              : `opacity 140ms ease-out, transform 220ms ${EASE}`,
          }}
        >
          <ChevronRight className="h-3.5 w-3.5 rotate-180 transition-transform duration-200 group-hover:-translate-x-0.5" />
        </button>
      </div>
    </div>
  );
}
