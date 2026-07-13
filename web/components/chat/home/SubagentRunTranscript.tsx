"use client";

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { StreamEvent } from "@/lib/unified-ws";
import { getTraceMeta } from "./TracePanels";

/**
 * A connected subagent's native run, rendered close to how its own CLI shows it:
 * each of DeepTutor's questions heads a round, then the agent's reply streams as
 * "●"-bulleted steps — its messages in a neutral bullet, tool calls in an amber
 * bullet — with command output in a muted block (collapsed when long). Text and
 * reasoning stream token-by-token: deltas sharing a merge id collapse to one row
 * that grows in place, so the answer types out and renders exactly once.
 *
 * Set in a Monaco/CJK monospace face (the CLI aesthetic) and the app's theme
 * tokens, so it matches the side viewer and follows light/dark theme.
 */
const MONO_FONT =
  'Monaco, Menlo, Consolas, "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", monospace';
const RESULT_PREVIEW_LINES = 3;

export default function SubagentRunTranscript({
  events,
  className = "",
}: {
  events: StreamEvent[];
  className?: string;
}) {
  const visible = useMemo(() => {
    // Events sharing a merge id collapse to ONE evolving row, rendered at the
    // first occurrence's position with the latest content. This drives two
    // things uniformly: a fill-in tool (web search shows "web search" on start,
    // fills in its query on finish) and token-level streaming (each text/think
    // delta carries the cumulative text under one id, so the row types out and
    // the final block finalizes it in place — the answer renders exactly once).
    const latestByMerge = new Map<string, StreamEvent>();
    for (const e of events) {
      const id = getTraceMeta(e).subagent_merge_id;
      if (id) latestByMerge.set(id, e);
    }
    const seenMerge = new Set<string>();
    const out: StreamEvent[] = [];
    for (const e of events) {
      const mergeId = getTraceMeta(e).subagent_merge_id;
      if (mergeId) {
        if (seenMerge.has(mergeId)) continue;
        seenMerge.add(mergeId);
        out.push(latestByMerge.get(mergeId) ?? e);
        continue;
      }
      out.push(e);
    }
    return out;
  }, [events]);

  return (
    <div
      className={`space-y-2.5 px-4 py-3.5 text-[13px] ${className}`}
      style={{ fontFamily: MONO_FONT }}
    >
      {visible.length === 0 ? (
        <div className="text-[var(--muted-foreground)]/70">…</div>
      ) : (
        visible.map((event, idx) => (
          <SubagentLine
            key={`sa-${idx}`}
            channel={String(getTraceMeta(event).subagent_channel || "log")}
            text={event.content}
          />
        ))
      )}
    </div>
  );
}

/** A "●"-bulleted step line (the agent's messages and tool calls). */
function BulletLine({
  bulletClass,
  children,
}: {
  bulletClass: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex gap-2 leading-[1.65] text-[var(--foreground)]">
      <span
        className={`mt-[3px] shrink-0 text-[10px] leading-[1.5] ${bulletClass}`}
      >
        ●
      </span>
      <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">
        {children}
      </span>
    </div>
  );
}

function SubagentLine({ channel, text }: { channel: string; text: string }) {
  const { t } = useTranslation();
  switch (channel) {
    case "question":
    case "user_question":
      // Heads each round: the question DeepTutor (or the user, from the sidebar)
      // put to the agent.
      return (
        <div className="mt-1 border-t border-[var(--border)]/60 pt-2.5 first:mt-0 first:border-t-0 first:pt-0">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--primary)]">
            {channel === "user_question" ? t("You ask") : t("DeepTutor asks")}
          </div>
          <div className="whitespace-pre-wrap break-words leading-[1.6] text-[var(--foreground)]">
            {text}
          </div>
        </div>
      );
    case "text":
    case "result":
      return (
        <BulletLine bulletClass="text-[var(--foreground)]/70">
          {text}
        </BulletLine>
      );
    case "tool":
      return (
        <BulletLine bulletClass="text-amber-500">
          <span className="break-all">{text}</span>
        </BulletLine>
      );
    case "reasoning":
      return (
        <div className="whitespace-pre-wrap break-words pl-4 text-[12px] italic leading-[1.6] text-[var(--muted-foreground)]">
          {text}
        </div>
      );
    case "tool_result":
      return <ToolResultBlock text={text} />;
    case "error":
      return (
        <div className="whitespace-pre-wrap break-words pl-4 leading-[1.55] text-red-600 dark:text-red-400">
          {text}
        </div>
      );
    default:
      return (
        <div className="whitespace-pre-wrap break-all pl-4 text-[12px] leading-[1.55] text-[var(--muted-foreground)]/70">
          {text}
        </div>
      );
  }
}

function ToolResultBlock({ text }: { text: string }) {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const [open, setOpen] = useState(false);
  const lines = text.split("\n");
  const overflow = lines.length > RESULT_PREVIEW_LINES;
  const shown =
    open || !overflow ? lines : lines.slice(0, RESULT_PREVIEW_LINES);
  const hidden = lines.length - RESULT_PREVIEW_LINES;
  return (
    <div className="ml-4 rounded-md border border-[var(--border)]/60 bg-[var(--muted)]/50 px-2.5 py-1.5">
      <pre
        className={`m-0 whitespace-pre-wrap break-all text-[12px] leading-[1.55] text-[var(--muted-foreground)] ${
          open ? "" : "max-h-20 overflow-hidden"
        }`}
        style={{ fontFamily: MONO_FONT }}
      >
        {shown.join("\n")}
      </pre>
      {overflow && (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="mt-1 text-[11px] text-[var(--muted-foreground)]/80 transition-colors hover:text-[var(--foreground)]"
        >
          {open
            ? zh
              ? "收起"
              : "collapse"
            : zh
              ? `… 展开 +${hidden} 行`
              : `… +${hidden} lines`}
        </button>
      )}
    </div>
  );
}
