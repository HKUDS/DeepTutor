"use client";

import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { browserStorage } from "@/shared/storage";

const WIDTH_KEY = "deeptutor.sidebar.width";
const MIN_WIDTH = 220;
const MAX_WIDTH = 480;
const DEFAULT_WIDTH = 220;

function clampWidth(width: number, max: number) {
  return Math.round(Math.max(MIN_WIDTH, Math.min(max, width)));
}

export function useSidebarResize(disabled: boolean) {
  const [preferredWidth, setPreferredWidth] = useState(DEFAULT_WIDTH);
  const [max, setMax] = useState(MAX_WIDTH);
  const [resizing, setResizing] = useState(false);
  const drag = useRef<{
    pointerId: number;
    startX: number;
    startWidth: number;
  } | null>(null);
  const width = clampWidth(preferredWidth, max);

  useEffect(() => {
    const stored = Number(browserStorage.readRaw("local", WIDTH_KEY));
    if (Number.isFinite(stored) && stored > 0) {
      // Hydrate after mount to keep the initial render consistent with SSR.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setPreferredWidth(clampWidth(stored, MAX_WIDTH));
    }
    const updateBounds = () =>
      setMax(
        Math.max(
          MIN_WIDTH,
          Math.min(MAX_WIDTH, Math.floor(window.innerWidth * 0.45)),
        ),
      );
    updateBounds();
    window.addEventListener("resize", updateBounds);
    return () => window.removeEventListener("resize", updateBounds);
  }, []);

  useEffect(() => {
    if (!resizing || disabled) return;
    const { cursor, userSelect } = document.body.style;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    return () => {
      document.body.style.cursor = cursor;
      document.body.style.userSelect = userSelect;
    };
  }, [resizing, disabled]);

  const saveWidth = (next: number) => {
    const bounded = clampWidth(next, max);
    setPreferredWidth(bounded);
    browserStorage.writeRaw("local", WIDTH_KEY, String(bounded));
  };
  const finishDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (drag.current?.pointerId !== event.pointerId) return;
    drag.current = null;
    setResizing(false);
  };

  return {
    width,
    min: MIN_WIDTH,
    max,
    resizing,
    handleProps: {
      onPointerDown: (event: PointerEvent<HTMLDivElement>) => {
        if (disabled || event.button !== 0) return;
        event.preventDefault();
        event.currentTarget.focus();
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startWidth: width,
        };
        setResizing(true);
      },
      onPointerMove: (event: PointerEvent<HTMLDivElement>) => {
        const current = drag.current;
        if (disabled || !current || current.pointerId !== event.pointerId)
          return;
        saveWidth(current.startWidth + event.clientX - current.startX);
      },
      onPointerUp: finishDrag,
      onPointerCancel: finishDrag,
      onLostPointerCapture: finishDrag,
      onDoubleClick: () => saveWidth(DEFAULT_WIDTH),
      onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => {
        if (disabled) return;
        const step = event.shiftKey ? 40 : 10;
        const next = {
          ArrowLeft: width - step,
          ArrowRight: width + step,
          Home: MIN_WIDTH,
          End: max,
        }[event.key];
        if (next === undefined) return;
        event.preventDefault();
        saveWidth(next);
      },
    },
  };
}
