"use client";

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Tooltip } from "./Tooltip";
import { cn } from "./styles";

export interface IconButtonProps extends Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "children"
> {
  label: string;
  icon: ReactNode;
  size?: "sm" | "md" | "lg";
  tooltipSide?: "top" | "right" | "bottom" | "left";
}

const sizes = {
  sm: "h-8 w-8 rounded-lg",
  md: "h-10 w-10 rounded-xl",
  lg: "h-12 w-12 rounded-xl",
};

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  function IconButton(
    {
      label,
      icon,
      size = "md",
      tooltipSide = "bottom",
      className,
      type = "button",
      ...props
    },
    ref,
  ) {
    return (
      <Tooltip label={label} side={tooltipSide} disabled={props.disabled}>
        <button
          ref={ref}
          type={type}
          aria-label={label}
          className={cn(
            "inline-flex shrink-0 items-center justify-center text-muted-foreground transition-colors duration-[var(--motion-fast)] hover:bg-muted hover:text-foreground",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
            "disabled:pointer-events-none disabled:opacity-45",
            sizes[size],
            className,
          )}
          {...props}
        >
          {icon}
        </button>
      </Tooltip>
    );
  },
);
