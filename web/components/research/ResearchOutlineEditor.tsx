"use client";

import { useCallback, useState } from "react";
import {
  ChevronDown,
  Plus,
  Play,
  Trash2,
  Loader2,
  CheckCircle2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { OutlineItem } from "@/lib/research-types";

type OutlineStatus = "editing" | "researching" | "done";

interface ResearchOutlineEditorProps {
  outline: OutlineItem[];
  topic: string;
  onConfirm: (outline: OutlineItem[]) => void;
  status?: OutlineStatus;
}

export default function ResearchOutlineEditor({
  outline: initialOutline,
  topic,
  onConfirm,
  status: externalStatus,
}: ResearchOutlineEditorProps) {
  const { t } = useTranslation();
  const [items, setItems] = useState<OutlineItem[]>(initialOutline);
  const [localConfirmed, setLocalConfirmed] = useState(false);
  // Auto-collapse once the research is underway / done, but let the user
  // re-expand by clicking the summary header. While editing, stays open.
  // ``userToggled`` latches on the first user click so subsequent
  // status-change re-renders don't keep slamming the card closed.
  const [collapsed, setCollapsed] = useState(false);
  const [userToggled, setUserToggled] = useState(false);

  const locked =
    externalStatus === "researching" ||
    externalStatus === "done" ||
    localConfirmed;

  const displayCollapsed = locked && (userToggled ? collapsed : true);

  const toggleCollapsed = useCallback(() => {
    const wasAutoCollapsed = locked && !userToggled;
    setUserToggled(true);
    setCollapsed((c) => (wasAutoCollapsed ? false : !c));
  }, [locked, userToggled]);

  const updateItem = useCallback(
    (index: number, field: keyof OutlineItem, value: string) => {
      setItems((prev) =>
        prev.map((item, i) =>
          i === index ? { ...item, [field]: value } : item,
        ),
      );
    },
    [],
  );

  const removeItem = useCallback((index: number) => {
    setItems((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const addItem = useCallback(() => {
    setItems((prev) => [...prev, { title: "", overview: "" }]);
  }, []);

  const handleConfirm = useCallback(() => {
    const valid = items.filter((item) => item.title.trim());
    if (valid.length === 0) return;
    setLocalConfirmed(true);
    onConfirm(valid);
  }, [items, onConfirm]);

  const validItems = locked
    ? initialOutline.filter((i) => i.title.trim())
    : items;

  const statusLabel = (() => {
    if (externalStatus === "done") return "Research Complete";
    if (externalStatus === "researching" || localConfirmed)
      return "Researching…";
    return null;
  })();

  const StatusIcon = externalStatus === "done" ? CheckCircle2 : Loader2;

  const headerClickable = locked;

  return (
    <div className="my-2 rounded-lg border border-[var(--border)]/30 bg-[var(--background)] shadow-sm">
      <button
        type="button"
        disabled={!headerClickable}
        onClick={headerClickable ? toggleCollapsed : undefined}
        className={`block w-full text-left ${displayCollapsed ? "" : "border-b border-[var(--border)]/20"} px-4 py-2 ${
          headerClickable
            ? "cursor-pointer transition-colors hover:bg-[var(--muted-foreground)]/[0.025]"
            : "cursor-default"
        }`}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {headerClickable && (
              <ChevronDown
                size={12}
                className={`shrink-0 text-[var(--muted-foreground)]/50 transition-transform ${
                  displayCollapsed ? "-rotate-90" : ""
                }`}
              />
            )}
            <h3 className="text-[13px] font-semibold text-[var(--foreground)]">
              {t("Research Outline")}
            </h3>
            {displayCollapsed && validItems.length > 0 && (
              <span className="text-[11px] text-[var(--muted-foreground)]/45">
                · {validItems.length} {t("sub-topics")}
              </span>
            )}
          </div>
          {statusLabel && (
            <span className="flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]/60">
              <StatusIcon
                size={12}
                className={externalStatus === "done" ? "" : "animate-spin"}
              />
              {statusLabel}
            </span>
          )}
        </div>
        {!locked && !collapsed && (
          <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]/60">
            Review and edit the sub-topics below, then start the research. You
            can also type in the chat to regenerate the outline.
          </p>
        )}
      </button>
      {!displayCollapsed && (
        <>
          <div className="space-y-0 divide-y divide-[var(--border)]/15">
            {validItems.map((item, index) => (
              <div
                key={index}
                className="group flex items-start gap-2 px-3 py-1.5 transition-colors hover:bg-[var(--muted-foreground)]/[0.02]"
              >
                <span className="mt-[3px] w-4 shrink-0 text-center text-[11px] font-medium tabular-nums leading-tight text-[var(--muted-foreground)]/30">
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1 space-y-0.5">
                  {locked ? (
                    <>
                      <div className="text-[12px] font-medium leading-snug text-[var(--foreground)]">
                        {item.title}
                      </div>
                      {item.overview && (
                        <div className="text-[11px] leading-snug text-[var(--muted-foreground)]/70">
                          {item.overview}
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      <input
                        type="text"
                        value={item.title ?? ""}
                        onChange={(e) =>
                          updateItem(index, "title", e.target.value)
                        }
                        placeholder={t("Sub-topic title...")}
                        className="w-full bg-transparent text-[12px] font-medium leading-snug text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]/30"
                      />
                      <textarea
                        value={item.overview ?? ""}
                        onChange={(e) =>
                          updateItem(index, "overview", e.target.value)
                        }
                        placeholder={t("Research direction and focus...")}
                        rows={1}
                        className="w-full resize-none bg-transparent text-[11px] leading-snug text-[var(--muted-foreground)]/70 outline-none placeholder:text-[var(--muted-foreground)]/25"
                        style={
                          { fieldSizing: "content" } as React.CSSProperties
                        }
                      />
                    </>
                  )}
                </div>
                {!locked && items.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeItem(index)}
                    className="mt-0.5 shrink-0 rounded p-0.5 text-[var(--muted-foreground)]/20 opacity-0 transition-all hover:bg-red-500/10 hover:text-red-500/60 group-hover:opacity-100"
                  >
                    <Trash2 size={12} />
                  </button>
                )}
              </div>
            ))}
          </div>

          {!locked && (
            <div className="flex items-center justify-between border-t border-[var(--border)]/20 px-4 py-2">
              <button
                type="button"
                onClick={addItem}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-[var(--muted-foreground)]/50 transition-colors hover:bg-[var(--muted-foreground)]/5 hover:text-[var(--muted-foreground)]/70"
              >
                <Plus size={12} />
                {t("Add sub-topic")}
              </button>
              <button
                type="button"
                onClick={handleConfirm}
                disabled={items.every((i) => !i.title.trim())}
                className="flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[11px] font-medium text-[var(--primary-foreground)] transition-all hover:opacity-90 disabled:opacity-40"
              >
                <Play size={11} />
                {t("Start Research")}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
