import { Brain, Database, Search } from "lucide-react";
import type { ModelAccess, ModelAccessItem } from "../types";
import { AssignedBadge } from "./AssignedBadge";

const rows = [
  ["llm", "LLM", Brain],
  ["embedding", "Embedding", Database],
  ["search", "Search", Search],
] as const;

function itemLabel(item: ModelAccessItem): string {
  return item.model || item.provider || item.name || "Assigned model";
}

export function ModelAccessSummary({ access }: { access: ModelAccess }) {
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-semibold text-[var(--foreground)]">Model access</h2>
          <p className="mt-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
            Your administrator manages these model endpoints. Keys stay on the server and are never shown here.
          </p>
        </div>
        <AssignedBadge />
      </div>
      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        {rows.map(([key, label, Icon]) => {
          const items = access[key] || [];
          return (
            <div key={key} className="rounded-xl border border-[var(--border)]/70 bg-[var(--background)]/40 p-4">
              <div className="flex items-center gap-2 text-[12px] font-medium text-[var(--muted-foreground)]">
                <Icon className="h-3.5 w-3.5" />
                {label}
              </div>
              {items.length ? (
                <div className="mt-3 space-y-2">
                  {items.map((item, index) => (
                    <div key={`${item.profile_id}-${item.model_id}-${index}`} className="text-[13px] text-[var(--foreground)]">
                      <div className="truncate font-medium">{itemLabel(item)}</div>
                      <div className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
                        {item.available === false ? "Unavailable" : "Ready"}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-3 text-[12px] text-[var(--muted-foreground)]">Not assigned yet</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
