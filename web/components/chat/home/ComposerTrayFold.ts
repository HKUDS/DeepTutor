"use client";

import {
  animate,
  useMotionValue,
  useReducedMotion,
  type AnimationPlaybackControls,
} from "framer-motion";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { browserStorage } from "@/shared/storage";

/**
 * Whether the layer under the composer is folded away. One browser-local
 * preference for every composer: putting the tray away is a habit, not a
 * choice made again on each page.
 */
const FOLD_KEY = "deeptutor.composer-tray";
const FOLD_EVENT = "deeptutor:composer-tray";

function readFolded(): boolean {
  return typeof window !== "undefined" && browserStorage.readRaw("local", FOLD_KEY) === "folded";
}

function writeFolded(folded: boolean): void {
  if (readFolded() === folded) return;
  browserStorage.writeRaw("local", FOLD_KEY, folded ? "folded" : "open");
  window.dispatchEvent(new Event(FOLD_EVENT));
}

function subscribe(onChange: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key === FOLD_KEY) onChange();
  };
  window.addEventListener(FOLD_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(FOLD_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** Past this many pixels a press is a drag; short of it, a click. */
const SLOP = 4;
/** How far the sheet follows past either end, against growing resistance. */
const STRETCH = 12;
/** Seconds of release speed carried into where it lands, so a flick counts. */
const THROW = 0.12;
const SPRING = { type: "spring", stiffness: 560, damping: 42, restDelta: 0.001, restSpeed: 0.02 } as const;

/** Rubber band: the further past the end, the less each pixel moves it. */
function resist(overshoot: number): number {
  return (1 - 1 / ((overshoot * 0.55) / STRETCH + 1)) * STRETCH;
}

/** How far the sheet rises to fold, as the stylesheet sets it. */
function travelOf(element: HTMLElement): number {
  return parseFloat(getComputedStyle(element).getPropertyValue("--dt-tray-travel")) || 1;
}

interface Drag {
  startY: number;
  /** Where the sheet was when picked up, mid-flight included. */
  from: number;
  travel: number;
  moved: boolean;
}

/**
 * Folding the tray up behind the composer, by its grip.
 *
 * `reveal` runs from 0 (only the lip shows) to 1 (open) and drives the
 * stylesheet through `--dt-tray-reveal`; the layout box never changes, so
 * nothing around the composer moves while the sheet does. The sheet follows
 * the pointer, stretches a little past either end, and on release springs
 * to whichever end it was thrown toward. A click on the grip, or anywhere on
 * the folded lip, does the same in one step.
 *
 * `summoned` is a list in the tray opened from elsewhere (`/persona`): the
 * sheet comes out for it and goes back when it closes, without touching the
 * preference.
 */
export function useTrayFold(summoned: boolean) {
  const folded = useSyncExternalStore(subscribe, readFolded, () => false);
  const away = folded && !summoned;
  const reveal = useMotionValue(away ? 0 : 1);
  const reduced = useReducedMotion();
  const drag = useRef<Drag | null>(null);
  const flight = useRef<{ target: number; controls: AnimationPlaybackControls } | null>(null);
  const swallowClick = useRef(false);
  const [dragging, setDragging] = useState(false);

  const glide = useCallback(
    (target: 0 | 1, velocity = 0) => {
      flight.current?.controls.stop();
      const controls = animate(reveal, target, reduced ? { duration: 0 } : { ...SPRING, velocity });
      flight.current = { target, controls };
      void controls.then(() => {
        if (flight.current?.controls === controls) flight.current = null;
      });
    },
    [reduced, reveal],
  );

  const settle = useCallback(
    (open: boolean, velocity = 0) => {
      glide(open ? 1 : 0, velocity);
      writeFolded(!open);
    },
    [glide],
  );

  // A change made here is already in flight. One from elsewhere — another
  // composer, another tab, the stored value adopted after hydration — is
  // simply where the sheet is; only a summons is worth watching.
  const lastSummoned = useRef(summoned);
  useEffect(() => {
    const target = away ? 0 : 1;
    const summonChanged = lastSummoned.current !== summoned;
    lastSummoned.current = summoned;
    if (drag.current?.moved || flight.current?.target === target) return;
    if (summonChanged) {
      glide(target);
      return;
    }
    flight.current?.controls.stop();
    flight.current = null;
    reveal.jump(target);
  }, [away, glide, reveal, summoned]);

  // A press is followed on the window, not on the sheet: the folded lip is
  // 11px tall, so the first pixels of a pull already leave it, and a release
  // anywhere — outside the window included — must still end the press.
  const release = useRef<(() => void) | null>(null);
  useEffect(() => () => release.current?.(), []);

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    swallowClick.current = false;
    if (event.button !== 0) return;
    // The tray's own controls keep their clicks; the rest of the sheet is the handle.
    if (!away && (event.target as Element).closest(".dt-tray-menu")) return;
    release.current?.();
    const sheet = event.currentTarget;
    const pointer = event.pointerId;
    const current: Drag = { startY: event.clientY, from: reveal.get(), travel: travelOf(sheet), moved: false };
    drag.current = current;

    const onMove = (move: PointerEvent) => {
      if (move.pointerId !== pointer) return;
      if (!current.moved) {
        const dy = move.clientY - current.startY;
        if (Math.abs(dy) < SLOP) return;
        current.moved = true;
        // Counted from the end of the slop, so picking it up is not a jump.
        current.startY += Math.sign(dy) * SLOP;
        flight.current?.controls.stop();
        flight.current = null;
        try {
          // Held by the sheet from here on: its cursor, no hover elsewhere.
          sheet.setPointerCapture(pointer);
        } catch {
          // A pointer already gone refuses capture; the window still hears it.
        }
        setDragging(true);
      }
      move.preventDefault();
      const span = current.travel;
      const px = current.from * span + (move.clientY - current.startY);
      reveal.set((px > span ? span + resist(px - span) : px < 0 ? -resist(-px) : px) / span);
    };
    const onEnd = (end: PointerEvent) => {
      if (end.pointerId !== pointer) return;
      release.current?.();
      if (!current.moved) return;
      // The click that ends a drag is not a second gesture.
      swallowClick.current = true;
      setDragging(false);
      const velocity = end.type === "pointerup" ? reveal.getVelocity() : 0;
      settle(reveal.get() + velocity * THROW >= 0.5, velocity);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onEnd);
    window.addEventListener("pointercancel", onEnd);
    release.current = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onEnd);
      window.removeEventListener("pointercancel", onEnd);
      release.current = null;
      if (drag.current === current) drag.current = null;
    };
  };

  const onClick = (event: MouseEvent<HTMLDivElement>) => {
    if (swallowClick.current) {
      swallowClick.current = false;
      return;
    }
    const target = event.target as Element;
    if (target.closest(".dt-tray-grip") || (away && !target.closest(".dt-tray-menu"))) settle(away);
  };

  const onGripKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const open = event.key === "ArrowDown" ? true : event.key === "ArrowUp" ? false : null;
    if (open === null || open === !away) return;
    event.preventDefault();
    settle(open);
  };

  return {
    away,
    dragging,
    reveal,
    onGripKeyDown,
    sheet: { onPointerDown, onClick },
  };
}
