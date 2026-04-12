"use client";

import { useCallback, useState } from "react";
import { Plus, Play, Trash2, Loader2, CheckCircle2 } from "lucide-react";
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
  const [items, setItems] = useState<OutlineItem[]>(initialOutline);
  const [localConfirmed, setLocalConfirmed] = useState(false);

  const locked = externalStatus === "researching" || externalStatus === "done" || localConfirmed;

  const updateItem = useCallback((index: number, field: keyof OutlineItem, value: string) => {
    setItems((prev) => prev.map((item, i) => (i === index ? { ...item, [field]: value } : item)));
  }, []);

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

  const validItems = locked ? initialOutline.filter((i) => i.title.trim()) : items;

  const statusLabel = (() => {
    if (externalStatus === "done") return "Research Complete";
    if (externalStatus === "researching" || localConfirmed) return "Researching…";
    return null;
  })();

  const StatusIcon = externalStatus === "done" ? CheckCircle2 : Loader2;

  return (
    <div className="my-2 rounded-lg border border-[var(--border)]/30 bg-[var(--background)] shadow-sm">
      <div className="border-b border-[var(--border)]/20 px-4 py-2.5">
        <div className="flex items-center justify-between">
          <h3 className="text-[13px] font-semibold text-[var(--foreground)]">
            Research Outline
          </h3>
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
        {!locked && (
          <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]/60">
            Review and edit the sub-topics below, then start the research. You can also type in the
            chat to regenerate the outline.
          </p>
        )}
      </div>

      <div className="space-y-0 divide-y divide-[var(--border)]/15">
        {validItems.map((item, index) => (
          <div
            key={index}
            className="group flex items-start gap-2 px-3 py-2.5 transition-colors hover:bg-[var(--muted-foreground)]/[0.02]"
          >
            <span className="mt-1.5 w-4 shrink-0 text-center text-[11px] font-medium tabular-nums text-[var(--muted-foreground)]/30">
              {index + 1}
            </span>
            <div className="min-w-0 flex-1 space-y-1">
              {locked ? (
                <>
                  <div className="text-[12px] font-medium text-[var(--foreground)]">
                    {item.title}
                  </div>
                  {item.overview && (
                    <div className="text-[11px] leading-relaxed text-[var(--muted-foreground)]/70">
                      {item.overview}
                    </div>
                  )}
                </>
              ) : (
                <>
                  <input
                    type="text"
                    value={item.title ?? ""}
                    onChange={(e) => updateItem(index, "title", e.target.value)}
                    placeholder="Sub-topic title..."
                    className="w-full bg-transparent text-[12px] font-medium text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]/30"
                  />
                  <textarea
                    value={item.overview ?? ""}
                    onChange={(e) => updateItem(index, "overview", e.target.value)}
                    placeholder="Research direction and focus..."
                    rows={2}
                    className="w-full resize-none bg-transparent text-[11px] leading-relaxed text-[var(--muted-foreground)]/70 outline-none placeholder:text-[var(--muted-foreground)]/25"
                  />
                </>
              )}
            </div>
            {!locked && items.length > 1 && (
              <button
                type="button"
                onClick={() => removeItem(index)}
                className="mt-1 shrink-0 rounded p-0.5 text-[var(--muted-foreground)]/20 opacity-0 transition-all hover:bg-red-500/10 hover:text-red-500/60 group-hover:opacity-100"
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
            Add sub-topic
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={items.every((i) => !i.title.trim())}
            className="flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[11px] font-medium text-[var(--primary-foreground)] transition-all hover:opacity-90 disabled:opacity-40"
          >
            <Play size={11} />
            Start Research
          </button>
        </div>
      )}
    </div>
  );
}
