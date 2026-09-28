"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { Search } from "lucide-react";

/**
 * Layout shell shared by the two registry workspaces (models and providers).
 *
 * Both pages are master–detail: a list rail that stays put while a long editor
 * scrolls next to it. They used to hand-roll it as a plain grid whose rail was
 * a `max-h` box in normal flow — so the list was cut mid-card with no scroll
 * affordance, and scrolling the page left the rail behind as a void. Here the
 * rail is a sticky, viewport-tall column that owns its own scrolling and shows
 * where the list continues.
 *
 * Note on tints: Tailwind 3 emits nothing for `<color>-[var(--token)]/NN`
 * because the tokens are hex literals it cannot split into channels, so every
 * tint below goes through color-mix.
 */

const CARD_BASE =
  "group relative w-full rounded-xl border px-3.5 py-3 text-left outline-none transition-[background-color,border-color,box-shadow,transform] duration-150 active:scale-[0.99] focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)]";

/** Row in a workspace rail. `active` is the row being edited, not the runtime default. */
export function workspaceCardClass(active: boolean): string {
  return `${CARD_BASE} ${
    active
      ? "border-[color-mix(in_srgb,var(--primary)_60%,var(--border))] bg-[color-mix(in_srgb,var(--primary)_8%,transparent)] ring-1 ring-[color-mix(in_srgb,var(--primary)_28%,transparent)]"
      : "border-[var(--border)] hover:border-[color-mix(in_srgb,var(--foreground)_18%,var(--border))] hover:bg-[color-mix(in_srgb,var(--accent)_60%,transparent)]"
  }`;
}

export function WorkspaceSplit({
  rail,
  detail,
}: {
  rail: ReactNode;
  detail: ReactNode;
}) {
  return (
    <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,286px)_minmax(0,1fr)] xl:gap-6">
      {rail}
      {detail}
    </div>
  );
}

/**
 * Tracks whether a scroll area continues past its top or bottom edge so the
 * rail can fade the cut instead of slicing a card in half.
 */
function useScrollEdges<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [edges, setEdges] = useState({ top: false, bottom: false });
  const measure = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const top = el.scrollTop > 2;
    const bottom = el.scrollHeight - el.clientHeight - el.scrollTop > 2;
    setEdges((current) =>
      current.top === top && current.bottom === bottom
        ? current
        : { top, bottom },
    );
  }, []);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    for (const child of Array.from(el.children)) observer.observe(child);
    return () => observer.disconnect();
  });
  return { ref, edges, measure };
}

/**
 * Height the scroll container actually leaves below `ref`, in px.
 *
 * A `100dvh` budget is wrong here: the settings save toolbar is a sibling
 * *below* the scroll container, so the moment there are unsaved changes the
 * container gets shorter while the viewport does not. The box then reached past
 * the visible area, which does not make it scrollable — it just hid the rest of
 * the list under the toolbar with no scrollbar to reveal it. Measuring the
 * container instead also tracks the rail pinning itself as the page scrolls.
 */
function useAvailableHeight<T extends HTMLElement>(
  ref: { current: T | null },
  enabled: boolean,
) {
  const [height, setHeight] = useState<number | null>(null);
  useEffect(() => {
    const box = ref.current;
    if (!enabled || !box) return;
    let scroller: HTMLElement | null = box.parentElement;
    while (scroller) {
      const overflow = getComputedStyle(scroller).overflowY;
      if (overflow === "auto" || overflow === "scroll") break;
      scroller = scroller.parentElement;
    }
    let frame = 0;
    const measure = () => {
      frame = 0;
      const limit = scroller
        ? scroller.getBoundingClientRect().bottom
        : window.innerHeight;
      const next = Math.round(limit - box.getBoundingClientRect().top - 16);
      setHeight((current) =>
        current !== null && Math.abs(current - next) < 2 ? current : next,
      );
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    schedule();
    const target: HTMLElement | Window = scroller ?? window;
    target.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    // Deliberately not observing the box itself: this hook sets its height.
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(schedule);
    if (observer && scroller) observer.observe(scroller);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      target.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      observer?.disconnect();
    };
  }, [enabled, ref]);
  return enabled ? height : null;
}

const WIDE_RAIL = "(min-width: 1280px)";

/** True at the breakpoint where the rail becomes a sticky, self-scrolling column. */
function useWideRail(): boolean {
  return useSyncExternalStore(
    useCallback((onChange: () => void) => {
      const query =
        typeof window.matchMedia === "function"
          ? window.matchMedia(WIDE_RAIL)
          : null;
      // Older Safari has no `addEventListener` on a MediaQueryList, and neither
      // do test stubs; a rail that cannot subscribe just keeps the narrow cap.
      if (typeof query?.addEventListener !== "function") return () => {};
      query.addEventListener("change", onChange);
      return () => query.removeEventListener("change", onChange);
    }, []),
    () =>
      typeof window.matchMedia === "function" &&
      window.matchMedia(WIDE_RAIL).matches,
    () => false,
  );
}

export function WorkspaceRail({
  action,
  search,
  filter,
  children,
  empty,
}: {
  action?: ReactNode;
  search: {
    label: string;
    value: string;
    onChange: (value: string) => void;
    placeholder: string;
  };
  filter?: ReactNode;
  children: ReactNode;
  /** Shown in place of the list when it has nothing to show. */
  empty?: ReactNode;
}) {
  const { ref, edges, measure } = useScrollEdges<HTMLDivElement>();
  // Below `xl` the rail sits above the detail pane and keeps its short fixed cap;
  // only the sticky column is worth measuring.
  const available = useAvailableHeight(ref, useWideRail() && !empty);
  return (
    <div className="flex min-w-0 flex-col gap-2.5 xl:sticky xl:top-4">
      {action}
      <div className="relative">
        <Search
          size={14}
          aria-hidden
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
        />
        <input
          type="search"
          aria-label={search.label}
          value={search.value}
          onChange={(event) => search.onChange(event.target.value)}
          placeholder={search.placeholder}
          className="w-full rounded-lg border border-[var(--border)] bg-transparent py-2 pl-8 pr-3 text-[13px] outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-[color-mix(in_srgb,var(--muted-foreground)_60%,transparent)] hover:border-[color-mix(in_srgb,var(--foreground)_22%,var(--border))] focus:border-[var(--ring)] focus:ring-2 focus:ring-[color-mix(in_srgb,var(--ring)_16%,transparent)]"
        />
      </div>
      {filter}
      {empty ? (
        <div className="rounded-xl border border-dashed border-[var(--border)] px-4 py-6 text-[13px] leading-relaxed text-[var(--muted-foreground)]">
          {empty}
        </div>
      ) : (
        <div className="relative min-h-0">
          {/* The cap belongs on the scroll box itself. It used to be `flex-1`
              here and `max-h-none` on the box, but the box's parent is not a
              flex container, so nothing bounded it: the list grew to its full
              content height, ran past the fold and never showed a scrollbar. */}
          <div
            ref={ref}
            onScroll={measure}
            style={
              available === null
                ? undefined
                : { maxHeight: `${Math.max(available, 220)}px` }
            }
            className="flex max-h-[24rem] min-h-0 flex-col gap-2 overflow-y-auto overscroll-contain pb-0.5 pr-0.5 [scrollbar-gutter:stable] xl:max-h-[calc(100dvh-15rem)]"
          >
            {children}
          </div>
          {/* Fades, not hard cuts: the list is allowed to run past its box, but
              it has to look like it continues rather than like it broke. */}
          <span
            aria-hidden
            className={`pointer-events-none absolute inset-x-0 top-0 h-5 bg-gradient-to-b from-[var(--background)] to-transparent transition-opacity duration-150 ${edges.top ? "opacity-100" : "opacity-0"}`}
          />
          <span
            aria-hidden
            className={`pointer-events-none absolute inset-x-0 bottom-0 h-6 bg-gradient-to-t from-[var(--background)] to-transparent transition-opacity duration-150 ${edges.bottom ? "opacity-100" : "opacity-0"}`}
          />
        </div>
      )}
    </div>
  );
}

/** Placeholder for the detail pane before anything is picked. */
export function WorkspaceDetailEmpty({
  icon,
  title,
  hint,
}: {
  icon: ReactNode;
  title: string;
  hint?: string;
}) {
  return (
    <div className="flex min-h-[18rem] flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-[var(--border)] px-8 py-12 text-center">
      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--muted)_65%,transparent)] text-[var(--muted-foreground)]">
        {icon}
      </span>
      <p className="text-[13.5px] font-medium">{title}</p>
      {hint && (
        <p className="max-w-[38ch] text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
          {hint}
        </p>
      )}
    </div>
  );
}

/** Heading for a group of fields inside a detail pane. */
export function WorkspaceFieldGroup({
  title,
  action,
  children,
  className = "",
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`space-y-3 ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[color-mix(in_srgb,var(--border)_70%,transparent)] pb-2">
        <h4 className="text-[12px] font-semibold tracking-tight">{title}</h4>
        {action}
      </div>
      {children}
    </section>
  );
}
