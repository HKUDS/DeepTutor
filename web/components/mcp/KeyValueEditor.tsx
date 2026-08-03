"use client";

import { Lock, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { inputClass, labelClass } from "@/components/mcp/styles";
import type { McpKvPair } from "@/lib/mcp-api";

/**
 * A stored credential arrives as ``${secret:server/field}``: the value itself is
 * never returned to this page. Detected here so the row can say so.
 */
export function isStoredCredential(value: string): boolean {
  return value.startsWith("${secret:") && value.endsWith("}");
}

/**
 * Editable key/value rows (environment variables, HTTP headers).
 *
 * Values are masked: on a self-configured server a header or env value is, in
 * practice, always the credential, and the backend stores it apart from the
 * config for exactly that reason.
 */
export default function KeyValueEditor({
  label,
  pairs,
  onChange,
  keyPlaceholder,
  valuePlaceholder,
}: {
  label: string;
  pairs: McpKvPair[];
  onChange: (pairs: McpKvPair[]) => void;
  keyPlaceholder: string;
  valuePlaceholder: string;
}) {
  const { t } = useTranslation();
  const update = (idx: number, patch: Partial<McpKvPair>) => {
    onChange(pairs.map((p, i) => (i === idx ? { ...p, ...patch } : p)));
  };
  const remove = (idx: number) => {
    onChange(pairs.filter((_, i) => i !== idx));
  };
  const add = () => {
    onChange([...pairs, { key: "", value: "" }]);
  };
  return (
    <div>
      <label className={labelClass}>{label}</label>
      <div className="space-y-2">
        {pairs.map((pair, idx) => (
          <div key={idx} className="flex items-center gap-2">
            <input
              className={`${inputClass} font-mono`}
              value={pair.key}
              onChange={(e) => update(idx, { key: e.target.value })}
              placeholder={keyPlaceholder}
              spellCheck={false}
              autoComplete="off"
            />
            {isStoredCredential(pair.value) ? (
              // A saved credential comes back as a reference, never as its
              // value. Showing the placeholder as editable text would invite
              // saving it *as* the credential, so the row reads as configured
              // and offers a deliberate replace instead.
              <div
                className={`${inputClass} flex items-center justify-between gap-2 text-[var(--muted-foreground)]`}
              >
                <span className="inline-flex items-center gap-1.5">
                  <Lock className="h-3 w-3" />
                  {t("Configured")}
                </span>
                <button
                  type="button"
                  onClick={() => update(idx, { value: "" })}
                  className="rounded px-1.5 text-[11px] hover:text-[var(--foreground)]"
                >
                  {t("Replace")}
                </button>
              </div>
            ) : (
              <input
                className={`${inputClass} font-mono`}
                type="password"
                value={pair.value}
                onChange={(e) => update(idx, { value: e.target.value })}
                placeholder={valuePlaceholder}
                spellCheck={false}
                autoComplete="off"
              />
            )}
            <button
              type="button"
              onClick={() => remove(idx)}
              aria-label={t("Remove")}
              className="shrink-0 rounded-md p-2 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-red-500"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={add}
          className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1.5 text-[11.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <Plus className="h-3 w-3" />
          {t("Add row")}
        </button>
      </div>
    </div>
  );
}
