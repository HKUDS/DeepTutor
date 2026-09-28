"use client";

import type { ReactNode } from "react";
import { m as motion, useReducedMotion } from "framer-motion";

/** Shared spring for the composer's icon-only selectors. */
export default function ToolbarLabel({
  expanded,
  children,
  fullWidth = false,
}: {
  expanded: boolean;
  children: ReactNode;
  fullWidth?: boolean;
}) {
  const reducedMotion = useReducedMotion();
  return (
    <motion.span
      aria-hidden="true"
      data-toolbar-label
      initial={false}
      animate={{
        width: expanded ? "auto" : 0,
        marginLeft: expanded ? 6 : 0,
        opacity: expanded ? 1 : 0,
      }}
      transition={
        reducedMotion
          ? { duration: 0 }
          : {
              type: "spring",
              duration: 0.4,
              bounce: 0.16,
              opacity: { duration: expanded ? 0.18 : 0.12 },
            }
      }
      className="inline-flex min-w-0 overflow-hidden whitespace-nowrap"
    >
      <span
        className={`inline-flex shrink-0 items-center gap-1 ${fullWidth ? "max-w-[min(32rem,calc(100vw-160px))] whitespace-normal [overflow-wrap:anywhere]" : "max-w-[180px]"}`}
      >
        {children}
      </span>
    </motion.span>
  );
}
