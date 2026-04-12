"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Loader2, Terminal } from "lucide-react";

interface ProcessLogsProps {
  logs: string[];
  executing: boolean;
  title?: string;
  emptyMessage?: string;
}

export default function ProcessLogs({
  logs,
  executing,
  title = "Process Logs",
  emptyMessage = "Waiting for output...",
}: ProcessLogsProps) {
  const [open, setOpen] = useState(true);
  const logContainerRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);

  useEffect(() => {
    if (executing && logs.length === 0) {
      stickToBottomRef.current = true;
    }
  }, [executing, logs.length]);

  useEffect(() => {
    const container = logContainerRef.current;
    if (!container || !open || !logs.length) return;
    if (!stickToBottomRef.current) return;
    container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  }, [logs.length, open]);

  if (!logs.length && !executing) return null;

  return (
    <details
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      className="group rounded-lg border border-[var(--border)] bg-[var(--card)]"
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-[13px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/50">
        <span className="inline-flex items-center gap-1.5">
          <Terminal size={13} strokeWidth={1.7} />
          {title}
          {logs.length > 0 && (
            <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-normal text-[var(--muted-foreground)]">
              {logs.length}
            </span>
          )}
        </span>
        <div className="flex items-center gap-2">
          {executing && <Loader2 size={12} className="animate-spin text-[var(--primary)]" />}
          <ChevronDown
            size={13}
            className="text-[var(--muted-foreground)] transition-transform group-open:rotate-180"
          />
        </div>
      </summary>
      <div className="border-t border-[var(--border)] bg-[var(--background)]">
        <div
          ref={logContainerRef}
          onScroll={(e) => {
            const container = e.currentTarget;
            const distanceFromBottom =
              container.scrollHeight - container.scrollTop - container.clientHeight;
            stickToBottomRef.current = distanceFromBottom <= 24;
          }}
          className="max-h-[220px] overflow-y-auto px-3 py-2.5 font-mono text-[11px] leading-[1.7] text-[var(--muted-foreground)]"
        >
          {logs.map((line, i) => (
            <div key={`log-${i}`} className="whitespace-pre-wrap break-all">
              <span className="mr-2 select-none text-[var(--border)]">
                {String(i + 1).padStart(3)}
              </span>
              {line}
            </div>
          ))}
          {executing && logs.length === 0 && (
            <div className="text-[var(--muted-foreground)]/60">{emptyMessage}</div>
          )}
        </div>
      </div>
    </details>
  );
}
