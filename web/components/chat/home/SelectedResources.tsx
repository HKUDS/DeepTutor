"use client";
/* eslint-disable @next/next/no-img-element -- Local attachment previews use object URLs. */
import { useState } from "react";
import { AnimatePresence, m as motion, useReducedMotion } from "framer-motion";
import { Pin, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useResourceReuse, ResourceReuseControl } from "./ResourceReuse";
import type { ContextTreeItem } from "./ContextReferenceTree";
import type { ResourceKind } from "@/lib/resource-reuse";

const kinds: Record<string, ResourceKind> = {
  file: "attachments",
  book: "books",
  reading: "reading",
  nb: "notebooks",
  hist: "chat_history",
  agent: "my_agents",
  q: "question_bank",
  mem: "memory",
  kb: "knowledge",
  persona: "persona",
  collaborator: "agent",
  skill: "skills",
  mcp: "mcp",
};
export default function SelectedResources({
  items,
}: {
  items: ContextTreeItem[];
}) {
  const { t } = useTranslation();
  const reuse = useResourceReuse();
  const reduced = useReducedMotion();
  const [expanded, setExpanded] = useState(false);
  const [editFiles, setEditFiles] = useState(false);
  if (!items.length) return null;
  const visible = expanded ? items : items.slice(0, 4);
  return (
    <div className="px-3 pt-2.5 pb-1" aria-label={t("Selected resources")}>
      <div className="flex flex-wrap gap-1.5">
        <AnimatePresence initial={false}>
          {visible.map((item) => {
            const kind = kinds[item.key.split("-")[0]];
            const repeat = kind && reuse?.policy[kind];
            return (
              <motion.div
                key={item.key}
                layout="position"
                initial={{ opacity: 0, scale: reduced ? 1 : 0.96 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: reduced ? 1 : 0.96 }}
                transition={{ duration: reduced ? 0 : 0.14 }}
                className="inline-flex max-w-[240px] items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--muted)]/35 px-2 py-1 text-[11px]"
              >
                <button
                  type="button"
                  disabled={!item.onClick}
                  onClick={item.onClick}
                  title={`${item.kind} · ${item.label}`}
                  className="flex min-w-0 items-center gap-1.5 text-left disabled:cursor-default"
                >
                  {item.thumbnailUrl ? (
                    <img
                      src={item.thumbnailUrl}
                      alt=""
                      className="h-4 w-4 rounded object-cover"
                    />
                  ) : (
                    <item.icon
                      size={12}
                      className="shrink-0 text-[var(--primary)]"
                    />
                  )}
                  <span className="truncate">{item.label}</span>
                </button>
                <span
                  title={t(repeat ? "Every turn" : "This turn only")}
                  className="shrink-0 text-[var(--muted-foreground)]"
                >
                  {repeat ? (
                    <Pin size={11} />
                  ) : (
                    <span className="text-[10px]">{t("This turn only")}</span>
                  )}
                </span>
                {item.onRemove && (
                  <button
                    type="button"
                    aria-label={`${t("Remove")} ${item.label}`}
                    onClick={item.onRemove}
                    className="rounded p-0.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                  >
                    <X size={12} />
                  </button>
                )}
              </motion.div>
            );
          })}
        </AnimatePresence>
        {items.length > 4 && (
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="rounded-lg px-2 text-[11px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            {expanded ? t("Collapse") : `+${items.length - 4}`}
          </button>
        )}
        {items.some((item) => item.key.startsWith("file-")) && (
          <button
            type="button"
            onClick={() => setEditFiles(!editFiles)}
            className="rounded-lg px-2 text-[11px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            {t("Attachment options")}
          </button>
        )}
      </div>
      {editFiles && (
        <div className="mt-1.5">
          <ResourceReuseControl kind="attachments" />
        </div>
      )}
    </div>
  );
}
