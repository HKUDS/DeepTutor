"use client";

/**
 * Pointer-driven vertical reordering for a list you can still click.
 *
 * Rows in the sidebar are primarily links and buttons, so the drag has to be a
 * second meaning of the same press rather than a mode you enter through a
 * handle. A press becomes a drag only after it travels a few pixels (after a
 * short hold on touch, where any travel is probably a scroll), and the click it
 * would otherwise have fired is swallowed on release. Anything marked
 * ``data-no-drag`` — a row's menu button, a disclosure caret, an open rename
 * field — keeps its press to itself.
 *
 * Built on pointer events rather than HTML5 drag-and-drop: that API cannot be
 * driven by touch, paints a ghost image nobody asked for, and offers no control
 * over how the rest of the list makes room.
 *
 * One press owns one drag, so the whole state machine lives inside the
 * pointerdown closure; only what the view needs to paint is lifted into state.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { moveItem } from "@/lib/sidebar-layout";

/** Travel that turns a mouse press into a drag. */
const POINTER_SLOP = 4;
/** Hold before a touch press becomes a drag instead of a scroll. */
const TOUCH_HOLD_MS = 320;
/** Travel that cancels a touch hold — the finger was scrolling after all. */
const TOUCH_SLOP = 10;
/** Distance from a scroll edge where the list starts following the pointer. */
const EDGE_ZONE = 36;
/** Auto-scroll speed at the very edge, in pixels per frame. */
const EDGE_MAX_SPEED = 18;

interface RowMetrics {
  height: number;
  /** Row midpoint in coordinates a scroll cannot invalidate. */
  center: number;
}

/** What the view needs to lay a drag out; null when nothing is moving. */
interface DragView {
  id: string;
  from: number;
  to: number;
  offset: number;
  height: number;
}

export interface DragSortOptions {
  /** Row ids in the order they are currently rendered. */
  ids: readonly string[];
  /** Receives the full reordered id list when a drag settles. */
  onReorder: (nextIds: string[]) => void;
  disabled?: boolean;
  /** The scrolling ancestor, so a drag can reach rows past the fold. */
  scrollRef?: React.RefObject<HTMLElement | null>;
}

export interface DragItemProps {
  ref: (element: HTMLElement | null) => void;
  onPointerDown: (event: React.PointerEvent) => void;
  onClickCapture: (event: React.MouseEvent) => void;
  onKeyDown: (event: React.KeyboardEvent) => void;
  onDragStartCapture: (event: React.DragEvent) => void;
  style: React.CSSProperties;
}

export interface DragSort {
  /** Id of the row being dragged right now, if any. */
  draggingId: string | null;
  /** Spread onto each row's wrapper element. */
  getItemProps: (id: string) => DragItemProps;
}

export function useDragSort({
  ids,
  onReorder,
  disabled = false,
  scrollRef,
}: DragSortOptions): DragSort {
  const [view, setView] = useState<DragView | null>(null);

  // Live values the drag closure reads long after the render that created it.
  // A press always happens after the commit that set them, so an effect is
  // early enough — and writing refs during render is not allowed.
  const idsRef = useRef(ids);
  const onReorderRef = useRef(onReorder);
  useEffect(() => {
    idsRef.current = ids;
    onReorderRef.current = onReorder;
  });

  const elementsRef = useRef(new Map<string, HTMLElement>());
  const refCallbacksRef = useRef(
    new Map<string, (element: HTMLElement | null) => void>(),
  );
  const teardownRef = useRef<(() => void) | null>(null);
  /** Set once a press has actually moved something, so its click never fires. */
  const swallowClickRef = useRef(false);
  const pressedRef = useRef(false);

  const handlePointerDown = useCallback(
    (id: string) => (event: React.PointerEvent) => {
      if (disabled || pressedRef.current) return;
      if (event.pointerType === "mouse" && event.button !== 0) return;
      if ((event.target as HTMLElement | null)?.closest("[data-no-drag]"))
        return;
      const index = idsRef.current.indexOf(id);
      if (index < 0 || idsRef.current.length < 2) return;

      const pointerId = event.pointerId;
      const touch = event.pointerType === "touch";
      const startX = event.clientX;
      const startY = event.clientY;

      pressedRef.current = true;
      swallowClickRef.current = false;

      /** Non-null once the press has been promoted to a real drag. */
      let rows: RowMetrics[] | null = null;
      let originY = 0;
      let lastClientY = startY;
      let to = index;
      let holdTimer: number | null = null;
      let frame: number | null = null;

      const scrollTop = () => scrollRef?.current?.scrollTop ?? 0;

      const track = (clientY: number) => {
        if (!rows) return;
        if (rows.length !== idsRef.current.length) {
          // The list changed underneath the drag, so its geometry no longer
          // describes the screen. Let go rather than drop somewhere blind.
          teardown();
          return;
        }
        lastClientY = clientY;
        const offset = clientY + scrollTop() - originY;
        to = resolveTarget(rows, index, offset);
        setView({ id, from: index, to, offset, height: rows[index].height });
      };

      const followEdges = () => {
        const container = scrollRef?.current;
        if (!rows || !container) return;
        const box = container.getBoundingClientRect();
        let velocity = 0;
        if (lastClientY < box.top + EDGE_ZONE) {
          velocity = -edgeSpeed(box.top + EDGE_ZONE - lastClientY);
        } else if (lastClientY > box.bottom - EDGE_ZONE) {
          velocity = edgeSpeed(lastClientY - (box.bottom - EDGE_ZONE));
        }
        if (velocity !== 0 && scrollContainerBy(container, velocity)) {
          track(lastClientY);
        }
        frame = requestAnimationFrame(followEdges);
      };

      const activate = (clientY: number) => {
        const measured = measureRows(
          idsRef.current,
          elementsRef.current,
          scrollTop(),
        );
        if (!measured || index >= measured.length) {
          teardown();
          return;
        }
        rows = measured;
        originY = startY + scrollTop();
        swallowClickRef.current = true;
        document.body.style.userSelect = "none";
        document.body.style.cursor = "grabbing";
        if (scrollRef?.current) frame = requestAnimationFrame(followEdges);
        track(clientY);
      };

      const onMove = (moveEvent: PointerEvent) => {
        if (moveEvent.pointerId !== pointerId) return;
        if (rows) {
          moveEvent.preventDefault();
          track(moveEvent.clientY);
          return;
        }
        const dx = Math.abs(moveEvent.clientX - startX);
        const dy = Math.abs(moveEvent.clientY - startY);
        if (touch) {
          // A finger that travels before the hold elapses was scrolling.
          if (Math.max(dx, dy) > TOUCH_SLOP) teardown();
          return;
        }
        if (dy > POINTER_SLOP && dy > dx) activate(moveEvent.clientY);
      };

      const finish = (commit: boolean) => {
        const settled = rows !== null && to !== index;
        teardown();
        if (commit && settled) {
          onReorderRef.current(moveItem(idsRef.current, index, to));
        }
      };

      const onUp = (upEvent: PointerEvent) => {
        if (upEvent.pointerId !== pointerId) return;
        finish(true);
      };
      const onCancel = () => finish(false);
      const onKey = (keyEvent: KeyboardEvent) => {
        if (keyEvent.key !== "Escape") return;
        keyEvent.preventDefault();
        finish(false);
      };
      // Touch scrolling is passive by default, so an active drag has to say
      // explicitly that the page must hold still under the finger.
      const blockTouchScroll = (touchEvent: TouchEvent) => {
        if (rows) touchEvent.preventDefault();
      };

      function teardown() {
        rows = null;
        pressedRef.current = false;
        teardownRef.current = null;
        if (holdTimer !== null) window.clearTimeout(holdTimer);
        if (frame !== null) cancelAnimationFrame(frame);
        document.removeEventListener("pointermove", onMove);
        document.removeEventListener("pointerup", onUp);
        document.removeEventListener("pointercancel", onCancel);
        document.removeEventListener("keydown", onKey);
        document.removeEventListener("touchmove", blockTouchScroll);
        document.body.style.userSelect = "";
        document.body.style.cursor = "";
        setView(null);
      }

      teardownRef.current = teardown;
      document.addEventListener("pointermove", onMove, { passive: false });
      document.addEventListener("pointerup", onUp);
      document.addEventListener("pointercancel", onCancel);
      document.addEventListener("keydown", onKey);
      document.addEventListener("touchmove", blockTouchScroll, {
        passive: false,
      });

      if (touch) {
        holdTimer = window.setTimeout(() => {
          holdTimer = null;
          if (pressedRef.current) activate(startY);
        }, TOUCH_HOLD_MS);
      }
    },
    [disabled, scrollRef],
  );

  /** Keyboard equivalent of the drag, for anyone not using a pointer. */
  const handleKeyDown = useCallback(
    (id: string) => (event: React.KeyboardEvent) => {
      if (disabled || !event.altKey) return;
      const step =
        event.key === "ArrowUp" ? -1 : event.key === "ArrowDown" ? 1 : 0;
      if (step === 0) return;
      const index = idsRef.current.indexOf(id);
      const next = index + step;
      if (index < 0 || next < 0 || next >= idsRef.current.length) return;
      event.preventDefault();
      event.stopPropagation();
      onReorderRef.current(moveItem(idsRef.current, index, next));
    },
    [disabled],
  );

  const handleClickCapture = useCallback((event: React.MouseEvent) => {
    if (!swallowClickRef.current) return;
    swallowClickRef.current = false;
    event.preventDefault();
    event.stopPropagation();
  }, []);

  const getRef = useCallback((id: string) => {
    const cached = refCallbacksRef.current.get(id);
    if (cached) return cached;
    const callback = (element: HTMLElement | null) => {
      if (element) elementsRef.current.set(id, element);
      else elementsRef.current.delete(id);
    };
    refCallbacksRef.current.set(id, callback);
    return callback;
  }, []);

  useEffect(() => () => teardownRef.current?.(), []);

  const getItemProps = useCallback(
    (id: string): DragItemProps => {
      const index = idsRef.current.indexOf(id);
      const dragging = view?.id === id;
      return {
        ref: getRef(id),
        onPointerDown: handlePointerDown(id),
        onClickCapture: handleClickCapture,
        onKeyDown: handleKeyDown(id),
        // Links and images are natively draggable; that ghost-image drag would
        // race this one the moment a press on a nav row starts moving.
        onDragStartCapture: (event: React.DragEvent) => event.preventDefault(),
        style: {
          transform: shiftFor(view, index, dragging),
          transition:
            view && !dragging
              ? "transform 180ms cubic-bezier(0.2, 0, 0, 1)"
              : undefined,
          position: dragging ? "relative" : undefined,
          zIndex: dragging ? 30 : undefined,
          touchAction: dragging ? "none" : undefined,
        },
      };
    },
    [getRef, handleClickCapture, handleKeyDown, handlePointerDown, view],
  );

  return { draggingId: view?.id ?? null, getItemProps };
}

/**
 * Snapshot every row's geometry in coordinates the scroll position cannot
 * invalidate, so auto-scrolling mid-drag does not shift the drop target.
 * Returns null when a row is missing or unlaid — better no drag than a wrong one.
 */
function measureRows(
  ids: readonly string[],
  elements: ReadonlyMap<string, HTMLElement>,
  scrollTop: number,
): RowMetrics[] | null {
  const rows: RowMetrics[] = [];
  for (const id of ids) {
    const element = elements.get(id);
    if (!element) return null;
    const box = element.getBoundingClientRect();
    if (box.height === 0) return null;
    rows.push({
      height: box.height,
      center: box.top + scrollTop + box.height / 2,
    });
  }
  return rows;
}

/**
 * Where the dragged row would land, by walking outward while its leading edge
 * is past the neighbour's midpoint. Measured against the pre-drag geometry,
 * which is what keeps the answer stable while the other rows animate.
 *
 * Edge-against-midpoint, not centre-against-centre: with centres, landing a
 * row on the first slot meant dragging it strictly *above* the first row's
 * centre — drop it right onto that row and it settled one slot short. Half a
 * row of travel now commits the swap, which is both what the eye expects and
 * what every other sortable list does.
 */
function resolveTarget(
  rows: readonly RowMetrics[],
  from: number,
  offset: number,
): number {
  const half = rows[from].height / 2;
  const leadingTop = rows[from].center - half + offset;
  const leadingBottom = rows[from].center + half + offset;
  let to = from;
  if (offset > 0) {
    while (to < rows.length - 1 && leadingBottom > rows[to + 1].center) to += 1;
  } else {
    while (to > 0 && leadingTop < rows[to - 1].center) to -= 1;
  }
  return to;
}

/** Scroll the container, reporting whether it actually moved. */
function scrollContainerBy(container: HTMLElement, delta: number): boolean {
  const before = container.scrollTop;
  container.scrollTop = before + delta;
  return container.scrollTop !== before;
}

/** How far a row slides to make room for the one being dragged over it. */
function shiftFor(
  view: DragView | null,
  index: number,
  dragging: boolean,
): string | undefined {
  if (!view) return undefined;
  if (dragging) return `translateY(${view.offset}px)`;
  if (view.to > view.from && index > view.from && index <= view.to) {
    return `translateY(${-view.height}px)`;
  }
  if (view.to < view.from && index >= view.to && index < view.from) {
    return `translateY(${view.height}px)`;
  }
  return "translateY(0px)";
}

function edgeSpeed(depth: number): number {
  return Math.min(
    EDGE_MAX_SPEED,
    Math.max(2, (depth / EDGE_ZONE) * EDGE_MAX_SPEED),
  );
}
