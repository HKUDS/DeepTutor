"use client";

import {
  cloneElement,
  isValidElement,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactElement,
} from "react";
import { cn } from "./styles";

export interface TooltipProps {
  label: string;
  children: ReactElement<{ "aria-describedby"?: string }>;
  side?: "top" | "right" | "bottom" | "left";
  delay?: number;
  disabled?: boolean;
}

const positions = {
  top: "bottom-full left-1/2 mb-2 -translate-x-1/2",
  right: "left-full top-1/2 ml-2 -translate-y-1/2",
  bottom: "left-1/2 top-full mt-2 -translate-x-1/2",
  left: "right-full top-1/2 mr-2 -translate-y-1/2",
};

export function Tooltip({
  label,
  children,
  side = "bottom",
  delay = 180,
  disabled = false,
}: TooltipProps) {
  const id = useId();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [visible, setVisible] = useState(false);

  const clear = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  }, []);
  const show = useCallback(
    (immediate = false) => {
      clear();
      if (disabled) return;
      if (immediate) setVisible(true);
      else timer.current = setTimeout(() => setVisible(true), delay);
    },
    [clear, delay, disabled],
  );
  const hide = useCallback(() => {
    clear();
    setVisible(false);
  }, [clear]);

  useEffect(() => clear, [clear]);

  if (!isValidElement(children)) return children;

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => show(false)}
      onMouseLeave={hide}
      onFocusCapture={() => show(true)}
      onBlurCapture={hide}
      onKeyDown={(event) => {
        if (event.key === "Escape") hide();
      }}
    >
      {cloneElement(children, {
        "aria-describedby": visible ? id : children.props["aria-describedby"],
      })}
      {visible ? (
        <span
          id={id}
          role="tooltip"
          className={cn(
            "pointer-events-none absolute z-[90] max-w-64 whitespace-nowrap rounded-lg bg-foreground px-2.5 py-1.5 text-xs font-medium text-background shadow-lg",
            positions[side],
          )}
        >
          {label}
        </span>
      ) : null}
    </span>
  );
}

export default Tooltip;
