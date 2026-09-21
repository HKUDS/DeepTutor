"use client";

import {
  AnimatePresence,
  m as motion,
  useAnimationControls,
  useReducedMotion,
} from "framer-motion";
import { pickerFlight } from "@/lib/picker-origin";
import ToolbarLabel from "./ToolbarLabel";
import { useLingerExpand } from "@/hooks/use-linger-expand";
import { ResourceReuseControl } from "./ResourceReuse";
import type { ResourceKind } from "@/lib/resource-reuse";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import {
  ArrowLeft,
  ChevronRight,
  Layers,
  Search,
  X,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useOutsideClick } from "@/hooks/use-outside-click";

export interface ComposerResourceItem {
  key: string;
  label: string;
  icon: LucideIcon;
  count: number;
  summary?: string;
  group: "Reference materials" | "Answer preferences" | "Tools";
  node: ReactNode;
  onClear?: () => void;
  resetLabel?: string;
}

export default function ComposerResources({
  items,
  open,
  onOpenChange,
  requestedKey,
  onBack,
  triggerRef,
  panelRef,
  materials,
  selectedCount = 0,
}: {
  selectedCount?: number;
  items: ComposerResourceItem[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  requestedKey?: string;
  onBack: () => void;
  triggerRef: RefObject<HTMLButtonElement | null>;
  panelRef: RefObject<HTMLDivElement | null>;
  materials: (query: string) => ReactNode;
}) {
  const { t } = useTranslation();
  const reduceMotion = useReducedMotion();
  const id = useId();
  const { expanded, triggerProps } = useLingerExpand(open);
  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const backRef = useRef<HTMLButtonElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const originRef = useRef<DOMRect | null>(null);
  const navigationRef = useRef(0);
  const returningRef = useRef(false);
  const surfaceControls = useAnimationControls();
  const contentControls = useAnimationControls();
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [position, setPosition] = useState<{
    left: number;
    top: number;
    width: number;
    maxHeight: number;
  } | null>(null);
  const current = items.find(
    (item) => item.key === (requestedKey || selectedKey),
  );
  const configured = selectedCount > 0 || items.some((item) => item.count > 0);
  const close = () => {
    navigationRef.current += 1;
    returningRef.current = false;
    originRef.current = null;
    onOpenChange(false);
    setSelectedKey(null);
    setQuery("");
  };
  useOutsideClick(rootRef, open, close);
  useLayoutEffect(() => {
    if (!open) return;
    let anchor: { left: number; top: number } | null = null;
    const place = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      const panel = panelRef.current;
      if (!rect || !panel) return;
      const mobile = window.innerWidth < 768;
      const width = mobile ? window.innerWidth - 24 : 336;
      const left = mobile
        ? 12
        : Math.max(12, Math.min(rect.left, window.innerWidth - width - 12));
      panel.style.width = `${width}px`;
      const height = Math.min(
        42 + (bodyRef.current?.scrollHeight ?? 0),
        window.innerHeight - 24,
      );
      const top = Math.max(
        12,
        Math.min(
          mobile ? window.innerHeight - height - 12 : rect.top - height - 8,
          window.innerHeight - height - 12,
        ),
      );
      anchor = { left: rect.left, top: rect.top };
      setPosition({
        left,
        top,
        width,
        maxHeight: window.innerHeight - top - 12,
      });
    };
    // Measure before paint. Layout projection must not animate from the
    // unmeasured origin. Keep this anchor while navigating or filtering;
    // content-height changes must not move the header under the pointer.
    place();
    const followScroll = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (
        rect &&
        anchor &&
        (rect.left !== anchor.left || rect.top !== anchor.top)
      )
        place();
    };
    window.addEventListener("resize", place);
    window.addEventListener("scroll", followScroll, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", followScroll, true);
    };
  }, [open, triggerRef, panelRef]);
  const currentKey = current?.key;
  const positioned = position !== null;
  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!open || !positioned || !panel) return;
    returningRef.current = false;
    panel.style.transform = "none";
    const origin = currentKey ? originRef.current : null;
    const target = panel.getBoundingClientRect();
    const anchored =
      !reduceMotion && origin && origin.width > 0 && origin.height > 0;
    surfaceControls.set({
      ...(anchored
        ? pickerFlight(origin, target)
        : { x: 0, y: 0, scaleX: 1, scaleY: 1 }),
      opacity: anchored || reduceMotion ? 1 : 0,
    });
    contentControls.set({ opacity: anchored ? 0 : 1 });
    void surfaceControls.start(
      { x: 0, y: 0, scaleX: 1, scaleY: 1, opacity: 1 },
      anchored
        ? { type: "spring", duration: 0.42, bounce: 0.05, velocity: 0 }
        : { type: "tween", duration: reduceMotion ? 0 : 0.14 },
    );
    void contentControls.start(
      { opacity: 1 },
      { duration: reduceMotion ? 0 : 0.16, delay: anchored ? 0.1 : 0 },
    );
    return () => {
      navigationRef.current += 1;
      surfaceControls.stop();
      contentControls.stop();
    };
  }, [
    open,
    positioned,
    currentKey,
    reduceMotion,
    panelRef,
    surfaceControls,
    contentControls,
  ]);
  useEffect(() => {
    if (!open || !positioned) return;
    if (bodyRef.current) bodyRef.current.scrollTop = 0;
    if (currentKey) backRef.current?.focus({ preventScroll: true });
    else searchRef.current?.focus({ preventScroll: true });
  }, [open, currentKey, positioned]);

  const back = async () => {
    if (returningRef.current) return;
    returningRef.current = true;
    const navigation = ++navigationRef.current;
    const panel = panelRef.current;
    const origin = originRef.current;
    if (
      !reduceMotion &&
      panel &&
      origin &&
      origin.width > 0 &&
      origin.height > 0
    ) {
      // Finish against the untransformed layout even when Back interrupts entry.
      const target = new DOMRect(
        panel.offsetLeft,
        panel.offsetTop,
        panel.offsetWidth,
        panel.offsetHeight,
      );
      void contentControls.start({ opacity: 0 }, { duration: 0.08 });
      await surfaceControls.start(
        { ...pickerFlight(origin, target), opacity: 0 },
        {
          duration: 0.24,
          ease: [0.4, 0, 0.2, 1],
          opacity: { duration: 0.1, delay: 0.12 },
        },
      );
    }
    if (navigation !== navigationRef.current) return;
    returningRef.current = false;
    setSelectedKey(null);
    onBack();
  };
  return (
    <div ref={rootRef} className="relative shrink-0">
      <button
        ref={triggerRef}
        {...triggerProps}
        aria-label={t("Resources")}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => (open ? close() : onOpenChange(true))}
        className={`inline-flex h-8 items-center rounded-lg px-2 text-[14px] font-medium transition-colors hover:bg-[var(--muted)] ${configured ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]"}`}
      >
        <span className="relative shrink-0">
          <Layers size={16} strokeWidth={1.7} />
          {configured && (
            <span
              className="absolute -right-1 -top-0.5 h-1.5 w-1.5 rounded-full bg-[var(--primary)]"
              aria-label={t("Configured")}
            />
          )}
        </span>
        <ToolbarLabel expanded={expanded}>
          <span>{t("Resources")}</span>
          <ChevronRight
            size={13}
            className={`shrink-0 transition-transform duration-200 ${open ? "rotate-90" : ""}`}
          />
        </ToolbarLabel>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            key="resource-overlay"
            className="contents"
            exit={{ opacity: 0 }}
            transition={{ duration: reduceMotion ? 0 : 0.12 }}
          >
            <div
              className="fixed inset-0 z-[59] bg-black/20 md:hidden"
              onClick={close}
              aria-hidden="true"
            />
            <motion.div
              initial={{ opacity: 0 }}
              animate={surfaceControls}
              exit={{ opacity: 0 }}
              transition={{ duration: reduceMotion ? 0 : 0.14 }}
              ref={panelRef}
              id={id}
              role="dialog"
              aria-label={t("Resources")}
              style={{
                ...position,
                visibility: position ? "visible" : "hidden",
              }}
              className="fixed left-3 top-3 z-[60] flex w-[calc(100vw-24px)] max-h-[calc(100dvh-24px)] flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--popover)] shadow-[0_8px_40px_rgba(0,0,0,0.14)] md:w-[336px]"
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  event.stopPropagation();
                  if (current) back();
                  else {
                    close();
                    triggerRef.current?.focus();
                  }
                }
                if (event.key === "Tab") {
                  const elements = Array.from(
                    event.currentTarget.querySelectorAll<HTMLElement>("*"),
                  );
                  const focusable = elements.filter(
                    (element) =>
                      element.tabIndex >= 0 &&
                      !element.matches(":disabled") &&
                      !element.hidden,
                  );
                  const first = focusable[0];
                  const last = focusable[focusable.length - 1];
                  if (event.shiftKey && document.activeElement === first) {
                    event.preventDefault();
                    last?.focus();
                  } else if (
                    !event.shiftKey &&
                    document.activeElement === last
                  ) {
                    event.preventDefault();
                    first?.focus();
                  }
                }
              }}
            >
              <motion.div
                animate={contentControls}
                className="flex h-10 shrink-0 items-center gap-2 border-b border-[var(--border)] px-2"
              >
                {current && (
                  <button
                    ref={backRef}
                    type="button"
                    onClick={back}
                    aria-label={t("Back")}
                    className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-[var(--muted)]"
                  >
                    <ArrowLeft size={16} />
                  </button>
                )}
                <span className="flex-1 px-2 text-[14px] font-medium">
                  {current?.label || t("Resources")}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    close();
                    triggerRef.current?.focus();
                  }}
                  aria-label={t("Close")}
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                >
                  <X size={16} />
                </button>
              </motion.div>
              <div
                ref={bodyRef}
                className="min-h-0 overflow-y-auto overscroll-contain"
              >
                <motion.div
                  key={current?.key || "overview"}
                  animate={contentControls}
                >
                  {current ? (
                    <div key={current.key}>
                      {current.onClear && (
                        <div className="flex items-center justify-between gap-2 bg-[var(--muted)]/30 px-3 py-2 text-xs text-[var(--muted-foreground)]">
                          <span>{current.summary || t("Default")}</span>
                          <button
                            type="button"
                            onClick={current.onClear}
                            className="rounded-md px-2 py-1 hover:bg-[var(--muted)]"
                          >
                            {current.resetLabel || t("Reset")}
                          </button>
                        </div>
                      )}
                      <div className="px-2 py-1.5">
                        <ResourceReuseControl
                          kind={current.key as ResourceKind}
                        />
                      </div>
                      {current.node}
                    </div>
                  ) : (
                    <>
                      <div className="flex items-center gap-2 px-3 py-2">
                        <Search
                          size={15}
                          className="text-[var(--muted-foreground)]"
                        />
                        <input
                          ref={searchRef}
                          value={query}
                          onChange={(e) => setQuery(e.target.value)}
                          aria-label={t("Search resource types")}
                          placeholder={t("Search resource types")}
                          className="min-w-0 flex-1 bg-transparent text-[13px] outline-none"
                        />
                      </div>
                      {(
                        [
                          "Reference materials",
                          "Answer preferences",
                          "Tools",
                        ] as const
                      ).map((group) => {
                        const rows = items.filter(
                          (item) =>
                            item.group === group &&
                            `${item.label} ${item.summary || ""}`
                              .toLowerCase()
                              .includes(query.toLowerCase().trim()),
                        );
                        return (
                          <section
                            key={group}
                            className="border-t border-[var(--border)]/60 py-1"
                          >
                            <h3 className="px-4 py-1 text-[11px] font-medium text-[var(--muted-foreground)]">
                              {t(group)}
                            </h3>
                            {group === "Reference materials" &&
                              materials(query)}
                            {rows.map((item) => (
                              <button
                                key={item.key}
                                type="button"
                                onClick={(event) => {
                                  originRef.current =
                                    event.currentTarget.getBoundingClientRect();
                                  setSelectedKey(item.key);
                                }}
                                aria-pressed={item.count > 0}
                                className={`flex min-h-9 w-full items-center gap-2 px-3 py-1.5 text-left transition-colors active:scale-[0.99] ${item.count > 0 ? "bg-[var(--primary)]/[0.07] text-[var(--primary)]" : "hover:bg-[var(--muted)]/60"}`}
                              >
                                <item.icon
                                  size={15}
                                  strokeWidth={1.7}
                                  className="shrink-0 text-[var(--muted-foreground)]"
                                />
                                <span className="flex-1 text-[13px]">
                                  {item.label}
                                </span>
                                <span
                                  className={`max-w-[120px] truncate rounded-md px-1.5 py-0.5 text-[11px] ${item.count > 0 ? "bg-[var(--primary)]/10 font-medium text-[var(--primary)]" : "text-[var(--muted-foreground)]"}`}
                                >
                                  {item.summary ||
                                    (item.count
                                      ? `${item.count}`
                                      : t("Default"))}
                                </span>
                                <ChevronRight
                                  size={14}
                                  className="text-[var(--muted-foreground)]"
                                />
                              </button>
                            ))}
                          </section>
                        );
                      })}
                    </>
                  )}
                </motion.div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
