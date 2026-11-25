import type { HTMLAttributes } from "react";
import { cn } from "./styles";

export function Skeleton({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn("dt-skeleton rounded-lg bg-muted", className)}
      {...props}
    />
  );
}
