"use client";

import {
  cloneElement,
  isValidElement,
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactElement,
} from "react";
import type { TooltipSide } from "./tooltip-position";

const loadTooltipLayer = () => import("./TooltipLayer");
const TooltipLayer = lazy(loadTooltipLayer);

function isNestedControl(target: EventTarget): boolean {
  return target instanceof Element &&
    Boolean(target.closest("button, a, input, select, textarea"));
}

export interface TooltipProps {
  label: string;
  description?: string;
  children: ReactElement<{ "aria-describedby"?: string }>;
  /** Choose a semantic wrapper when a span cannot contain the trigger. */
  as?: "span" | "div" | "li";
  className?: string;
  side?: TooltipSide;
  delay?: number;
  /** Suppress a tooltip while its trigger owns an open popover or menu. */
  suppressed?: boolean;
}

export function Tooltip({
  label,
  description,
  children,
  as: Wrapper = "span",
  className,
  side = "bottom",
  delay = 180,
  suppressed = false,
}: TooltipProps) {
  const id = useId();
  const wrapperRef = useRef<HTMLElement>(null);
  const setWrapperRef = useCallback((node: HTMLElement | null) => {
    wrapperRef.current = node;
  }, []);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hoverRef = useRef(false);
  const keyboardFocusRef = useRef(false);
  const pointerFocusRef = useRef(false);
  const touchRef = useRef(false);
  const [visible, setVisible] = useState(false);
  const [layerMounted, setLayerMounted] = useState(false);
  const renderedVisible = visible && !suppressed;
  const markLayerMounted = useCallback(() => setLayerMounted(true), []);

  const clearTimer = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
  }, []);
  const hide = useCallback(() => {
    clearTimer();
    touchRef.current = false;
    setVisible(false);
  }, [clearTimer]);
  const show = useCallback(
    (immediate: boolean) => {
      clearTimer();
      if (suppressed) return;
      void loadTooltipLayer();
      if (immediate) setVisible(true);
      else timerRef.current = setTimeout(() => setVisible(true), delay);
    },
    [clearTimer, delay, suppressed],
  );

  useEffect(() => {
    if (!suppressed) return;
    const timeout = window.setTimeout(hide, 0);
    return () => window.clearTimeout(timeout);
  }, [hide, suppressed]);
  useEffect(() => clearTimer, [clearTimer]);

  useEffect(() => {
    if (!renderedVisible) return;
    const dismissTouch = (event: PointerEvent) => {
      if (
        touchRef.current &&
        wrapperRef.current &&
        !wrapperRef.current.contains(event.target as Node)
      ) {
        hide();
      }
    };
    document.addEventListener("pointerdown", dismissTouch, true);
    return () => document.removeEventListener("pointerdown", dismissTouch, true);
  }, [hide, renderedVisible]);

  if (!isValidElement(children)) return children;
  const describedBy = [children.props["aria-describedby"], id]
    .filter(Boolean)
    .join(" ");
  const tooltipText = description ? `${label}. ${description}` : label;

  return (
    <Wrapper
      ref={setWrapperRef}
      className={Wrapper === "span" ? `inline-flex ${className ?? ""}` : className}
      onPointerEnter={(event) => {
        if (event.pointerType === "touch") return;
        if (Wrapper === "li" && isNestedControl(event.target)) return;
        hoverRef.current = true;
        show(false);
      }}
      onPointerOverCapture={(event) => {
        if (Wrapper !== "li" || !isNestedControl(event.target)) return;
        hoverRef.current = false;
        hide();
      }}
      onPointerLeave={(event) => {
        if (event.pointerType === "touch") return;
        hoverRef.current = false;
        if (!keyboardFocusRef.current) hide();
      }}
      onPointerDown={(event) => {
        pointerFocusRef.current = true;
        if (Wrapper === "li" && isNestedControl(event.target)) {
          hide();
          return;
        }
        if (event.pointerType !== "touch") return;
        touchRef.current = true;
        if (renderedVisible) hide();
        else {
          show(true);
          timerRef.current = setTimeout(hide, 3000);
        }
      }}
      onPointerUp={() => {
        queueMicrotask(() => {
          pointerFocusRef.current = false;
        });
      }}
      onFocusCapture={(event) => {
        if (Wrapper === "li" && isNestedControl(event.target)) {
          hide();
          return;
        }
        if (pointerFocusRef.current) return;
        keyboardFocusRef.current = true;
        show(true);
      }}
      onBlurCapture={(event) => {
        if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
        keyboardFocusRef.current = false;
        if (!hoverRef.current) hide();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") hide();
      }}
    >
      {cloneElement(children, { "aria-describedby": describedBy })}
      {!renderedVisible || !layerMounted ? (
        <span id={id} role="tooltip" className="sr-only">
          {tooltipText}
        </span>
      ) : null}
      {renderedVisible && typeof document !== "undefined"
        ? (
            <Suspense fallback={null}>
              <TooltipLayer
                anchorRef={wrapperRef}
                id={id}
                label={label}
                description={description}
                side={side}
                onMount={markLayerMounted}
              />
            </Suspense>
          )
        : null}
    </Wrapper>
  );
}

export { placeTooltip, type TooltipSide } from "./tooltip-position";

export default Tooltip;
