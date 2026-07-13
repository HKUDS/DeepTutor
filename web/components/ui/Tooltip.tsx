"use client";

import {
  ReactNode,
  useState,
  useCallback,
  useEffect,
  useRef,
  useId,
} from "react";

interface TooltipProps {
  label: string;
  description?: string;
  children: ReactNode;
  side?: "right" | "bottom";
}

export function Tooltip({
  label,
  description,
  children,
  side = "right",
}: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tooltipId = useId();

  const showTooltip = useCallback(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => setVisible(true), 300);
  }, []);

  const showNow = useCallback(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setVisible(true);
  }, []);

  const hideTooltip = useCallback(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setVisible(false);
  }, []);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  return (
    <div
      className="dt-tooltip-wrapper"
      onMouseEnter={showTooltip}
      onMouseLeave={hideTooltip}
      onFocus={showNow}
      onBlur={hideTooltip}
      aria-describedby={visible ? tooltipId : undefined}
    >
      {children}
      {visible && (
        <div
          id={tooltipId}
          className="dt-tooltip-content"
          data-side={side}
          role="tooltip"
        >
          <div className="dt-tooltip-label">{label}</div>
          {description && <div className="dt-tooltip-desc">{description}</div>}
        </div>
      )}
    </div>
  );
}
