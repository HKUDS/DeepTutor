"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowUp, Loader2 } from "lucide-react";

import SubagentRunTranscript from "@/components/chat/home/SubagentRunTranscript";
import { getTraceMeta } from "@/components/chat/home/TracePanels";
import { streamSubagentMessage } from "@/lib/subagents-api";
import type { StreamEvent } from "@/lib/unified-ws";

/**
 * A connected subagent's run tab: the streamed transcript plus an input box to
 * message the agent directly. Sent messages resume the SAME live session
 * DeepTutor consults (shared via the cross-turn registry), so the agent keeps
 * full context — the sidebar and the chat loop talk to one agent session.
 *
 * Events from the chat loop arrive as ``tabEvents`` (refreshed by the parent);
 * sidebar-originated events live in local state and are concatenated, so the
 * transcript shows the whole exchange in order.
 */
export default function SubagentTabBody({
  tabEvents,
  sessionId,
}: {
  tabEvents: StreamEvent[];
  sessionId: string | null;
}) {
  const { t } = useTranslation();
  const [localEvents, setLocalEvents] = useState<StreamEvent[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seqRef = useRef(0);

  // The connection's name/kind come from the streamed events' metadata.
  const { name } = useMemo(() => {
    for (let i = tabEvents.length - 1; i >= 0; i--) {
      const meta = getTraceMeta(tabEvents[i]);
      if (meta.subagent_name) {
        return { name: String(meta.subagent_name) };
      }
    }
    return { name: "" };
  }, [tabEvents]);

  const allEvents = useMemo(
    () => [...tabEvents, ...localEvents],
    [tabEvents, localEvents],
  );

  const append = useCallback(
    (channel: string, text: string, mergeId?: string) => {
      const event: StreamEvent = {
        type: "progress",
        source: "subagent",
        stage: "",
        content: text,
        metadata: {
          trace_kind: "subagent_event",
          subagent_channel: channel,
          subagent_name: name,
          ...(mergeId ? { subagent_merge_id: mergeId } : {}),
        },
        timestamp: seqRef.current++,
      };
      setLocalEvents((prev) => [...prev, event]);
    },
    [name],
  );

  const send = useCallback(async () => {
    const message = draft.trim();
    if (!message || busy || !name) return;
    setDraft("");
    setError(null);
    setBusy(true);
    try {
      for await (const line of streamSubagentMessage(name, {
        chat_session_id: sessionId ?? "",
        message,
      })) {
        if (line.done) break;
        if (line.channel) append(line.channel, line.text ?? "", line.merge_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [draft, busy, name, sessionId, append]);

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <SubagentRunTranscript events={allEvents} className="min-h-full" />
      </div>
      <div className="shrink-0 border-t border-[var(--border)] bg-[var(--background)] px-3 py-2.5">
        {error && (
          <div className="mb-1.5 text-[11.5px] text-red-600 dark:text-red-400">
            {error}
          </div>
        )}
        <div className="flex items-end gap-2">
          <textarea
            rows={1}
            value={draft}
            disabled={busy || !name}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder={
              name
                ? t("Message {{name}} directly…", { name })
                : t("Message the agent directly…")
            }
            className="max-h-32 min-h-[36px] flex-1 resize-none rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)]/50 focus:border-[var(--ring)] disabled:opacity-60"
          />
          <button
            type="button"
            onClick={() => void send()}
            disabled={busy || !draft.trim() || !name}
            aria-label={t("Send")}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--foreground)] text-[var(--background)] transition-opacity disabled:opacity-40"
          >
            {busy ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <ArrowUp size={16} />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
