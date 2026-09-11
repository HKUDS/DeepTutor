import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "./styles";

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

export interface StatusChipProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: StatusTone;
  icon?: ReactNode;
}

const tones: Record<StatusTone, string> = {
  neutral: "bg-muted text-muted-foreground",
  info: "bg-info-surface text-info-foreground",
  success: "bg-success-surface text-success-foreground",
  warning: "bg-warning-surface text-warning-foreground",
  danger: "bg-destructive/10 text-destructive",
};

export function StatusChip({
  tone = "neutral",
  icon,
  children,
  className,
  ...props
}: StatusChipProps) {
  return (
    <span
      className={cn(
        "inline-flex min-h-6 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium leading-none",
        tones[tone],
        className,
      )}
      {...props}
    >
      {icon}
      {children}
    </span>
  );
}
