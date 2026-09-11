import type { HTMLAttributes, ReactNode } from "react";
import { AlertCircle, CheckCircle2, Info, TriangleAlert } from "lucide-react";
import { cn } from "./styles";
import type { StatusTone } from "./StatusChip";

export interface InlineAlertProps extends HTMLAttributes<HTMLDivElement> {
  tone?: Exclude<StatusTone, "neutral">;
  title?: string;
  action?: ReactNode;
}

const toneStyles = {
  info: "border-info/20 bg-info-surface text-info-foreground",
  success: "border-success/20 bg-success-surface text-success-foreground",
  warning: "border-warning/20 bg-warning-surface text-warning-foreground",
  danger: "border-destructive/20 bg-destructive/10 text-destructive",
};

const icons = {
  info: Info,
  success: CheckCircle2,
  warning: TriangleAlert,
  danger: AlertCircle,
};

export function InlineAlert({
  tone = "info",
  title,
  action,
  children,
  className,
  ...props
}: InlineAlertProps) {
  const Icon = icons[tone];
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cn(
        "flex items-start gap-3 rounded-xl border px-4 py-3 text-sm",
        toneStyles[tone],
        className,
      )}
      {...props}
    >
      <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1">
        {title ? <p className="font-semibold">{title}</p> : null}
        <div className={cn("leading-5", title && "mt-0.5 opacity-90")}>
          {children}
        </div>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
