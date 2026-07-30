"use client";

import { useTranslation } from "react-i18next";

import type { McpTool } from "@/lib/mcp-api";

export default function McpToolList({ tools }: { tools: McpTool[] }) {
  const { t } = useTranslation();
  return (
    <div className="border-t border-[var(--border)]/40 bg-[var(--background)]/40 px-5 py-4">
      <div className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-[var(--muted-foreground)]/80">
        {t("Exposed tools")}
      </div>
      <ul className="space-y-1.5">
        {tools.map((tool) => (
          <li key={tool.name} className="flex items-baseline gap-2">
            <span className="font-mono text-[12px] text-[var(--foreground)]">
              {tool.name}
            </span>
            {tool.description && (
              <span className="text-[12px] text-[var(--muted-foreground)]">
                — {tool.description}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
