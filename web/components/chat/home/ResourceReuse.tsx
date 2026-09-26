"use client";
import { createContext, useContext, useMemo, useState } from "react";
import { Pin } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  DEFAULT_RESOURCE_REUSE,
  type ResourceKind,
  type ResourceReuse,
} from "@/lib/resource-reuse";

export function useResourceReusePolicy(scope: string, continuityKey?: number) {
  const [byScope, setByScope] = useState<Record<string, ResourceReuse>>({});
  const [previous, setPrevious] = useState({ scope, continuityKey });
  // A draft acquires a server ID after its first send. Preserve its policy
  // only when the same first message identifies that conversation.
  if (previous.scope !== scope || previous.continuityKey !== continuityKey) {
    setPrevious({ scope, continuityKey });
    if (
      previous.scope.startsWith("draft") &&
      previous.scope !== scope &&
      continuityKey !== undefined &&
      previous.continuityKey === continuityKey &&
      byScope[previous.scope] &&
      !byScope[scope]
    ) {
      setByScope((old) => ({ ...old, [scope]: old[previous.scope] }));
    }
  }
  const policy = byScope[scope] ?? DEFAULT_RESOURCE_REUSE;
  return useMemo(
    () => ({
      policy,
      setEveryTurn: (kind: ResourceKind, enabled: boolean) =>
        setByScope((old) => ({
          ...old,
          [scope]: {
            ...(old[scope] ?? DEFAULT_RESOURCE_REUSE),
            [kind]: enabled,
          },
        })),
    }),
    [policy, scope],
  );
}
export const ResourceReuseContext = createContext<ReturnType<
  typeof useResourceReusePolicy
> | null>(null);
export function useResourceReuse() {
  return useContext(ResourceReuseContext);
}
export function ResourceReuseControl({ kind }: { kind: ResourceKind }) {
  const context = useResourceReuse();
  const { t } = useTranslation();
  if (!context) return null;
  const enabled = context.policy[kind];
  return (
    <label
      title={t("Include these resources every turn")}
      className={`inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] leading-4 transition-colors focus-within:ring-2 focus-within:ring-[var(--primary)]/30 ${enabled ? "border-[var(--primary)]/20 bg-[var(--primary)]/5 text-[var(--primary)]" : "border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--muted)]/50"}`}
    >
      <input
        type="checkbox"
        aria-label={t("Include these resources every turn")}
        checked={enabled}
        onChange={(e) => context.setEveryTurn(kind, e.target.checked)}
        className="peer sr-only"
      />
      <Pin size={12} strokeWidth={1.7} />
      <span>{t(enabled ? "Every turn" : "This turn only")}</span>
      <span
        aria-hidden="true"
        className="relative ml-1 h-3.5 w-6 rounded-full transition-colors"
        style={{
          backgroundColor: enabled ? "var(--primary)" : "var(--border)",
        }}
      >
        <span
          className={`absolute top-0.5 h-2.5 w-2.5 rounded-full bg-white shadow-sm transition-transform duration-150 motion-reduce:transition-none ${enabled ? "translate-x-3" : "translate-x-0.5"}`}
        />
      </span>
    </label>
  );
}
