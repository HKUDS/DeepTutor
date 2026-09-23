"use client";

import {
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import {
  placeTooltip,
  type TooltipPosition,
  type TooltipSide,
} from "./tooltip-position";

export default function TooltipLayer({
  anchorRef,
  id,
  label,
  description,
  side,
  onMount,
}: {
  anchorRef: RefObject<HTMLSpanElement | null>;
  id: string;
  label: string;
  description?: string;
  side: TooltipSide;
  onMount: () => void;
}) {
  const tooltipRef = useRef<HTMLSpanElement>(null);
  const [position, setPosition] = useState<TooltipPosition | null>(null);

  useLayoutEffect(() => {
    onMount();
    const update = () => {
      if (!anchorRef.current || !tooltipRef.current) return;
      setPosition(
        placeTooltip(
          anchorRef.current.getBoundingClientRect(),
          tooltipRef.current.getBoundingClientRect(),
          side,
          window.innerWidth,
          window.innerHeight,
        ),
      );
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [anchorRef, onMount, side]);

  return createPortal(
    <span
      ref={tooltipRef}
      id={id}
      role="tooltip"
      data-side={position?.side ?? side}
      style={
        position
          ? { left: position.left, top: position.top }
          : { left: 0, top: 0 }
      }
      className={`pointer-events-none fixed z-[1000] max-w-72 rounded-lg bg-[var(--foreground)] px-2.5 py-1.5 text-left text-[11px] font-medium leading-snug text-[var(--background)] shadow-lg [overflow-wrap:anywhere] ${position ? "opacity-100" : "opacity-0"}`}
    >
      <span className="block">{label}</span>
      {description ? (
        <span className="mt-0.5 block font-normal opacity-80">
          {description}
        </span>
      ) : null}
    </span>,
    document.body,
  );
}
