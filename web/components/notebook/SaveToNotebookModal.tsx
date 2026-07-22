"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  Loader2,
  MessageSquare,
  NotebookPen,
  Sparkles,
  User,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import PickerShell from "@/components/common/PickerShell";
import PickerHeader from "@/components/common/PickerHeader";
import { apiFetch, apiUrl } from "@/lib/api";
import {
  listNotebooks,
  type NotebookSummary as RealNotebookSummary,
} from "@/lib/notebook-api";

type RecordType =
  | "solve"
  | "question"
  | "research"
  | "chat"
  | "co_writer"
  | "tutorbot";

export interface NotebookSavePayload {
  recordType: RecordType;
  title: string;
  userQuery: string;
  output: string;
  metadata?: Record<string, unknown>;
  kbName?: string | null;
}

export interface NotebookSaveMessage {
  role: "user" | "assistant" | "system";
  content: string;
  capability?: string;
}

interface SaveToNotebookModalProps {
  open: boolean;
  payload: NotebookSavePayload | null;
  /**
   * Optional list of chat messages. When provided, the modal switches to
   * "selection mode" and lets the user pick which messages to include in the
   * saved notebook record. The transcript / userQuery in the final request
   * are rebuilt from the selected subset, while other fields (recordType,
   * metadata, kbName) come from `payload`.
   */
  messages?: NotebookSaveMessage[] | null;
  onClose: () => void;
  onSaved?: (result: { summary: string }) => void;
}

function parseSseEvents(
  buffer: string,
): Array<{ payload: Record<string, unknown> }> {
  const events: Array<{ payload: Record<string, unknown> }> = [];
  const chunks = buffer.split("\n\n");
  for (let i = 0; i < chunks.length - 1; i += 1) {
    const lines = chunks[i]
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    const dataLine = lines.find((line) => line.startsWith("data:"));
    if (!dataLine) continue;
    try {
      const payload = JSON.parse(dataLine.slice(5).trim()) as Record<
        string,
        unknown
      >;
      events.push({ payload });
    } catch {
      continue;
    }
  }
  return events;
}

function roleLabelKey(role: NotebookSaveMessage["role"]): string {
  if (role === "user") return "User";
  if (role === "assistant") return "Assistant";
  return "System";
}

function buildTranscript(messages: NotebookSaveMessage[]): string {
  return messages
    .map((msg) => {
      const role =
        msg.role === "user"
          ? "User"
          : msg.role === "assistant"
            ? "Assistant"
            : "System";
      return `## ${role}\n${msg.content}`;
    })
    .join("\n\n");
}

function buildUserQuery(messages: NotebookSaveMessage[]): string {
  return messages
    .filter((msg) => msg.role === "user")
    .map((msg) => msg.content)
    .join("\n\n");
}

function deriveTitle(
  messages: NotebookSaveMessage[],
  fallback: string,
): string {
  const firstUser = messages.find((msg) => msg.role === "user");
  const candidate = firstUser?.content.trim();
  if (!candidate) return fallback;
  return candidate.slice(0, 80);
}

/**
 * Compute the indexes of the most recent N "turns". A turn is loosely
 * defined as a user message plus any assistant/system messages that follow
 * it until the next user message. When N exceeds the available turn count
 * we just return all message indexes.
 */
function indexesForLastTurns(
  messages: NotebookSaveMessage[],
  turnCount: number,
): number[] {
  if (messages.length === 0 || turnCount <= 0) return [];
  const userPositions: number[] = [];
  messages.forEach((msg, idx) => {
    if (msg.role === "user") userPositions.push(idx);
  });
  if (userPositions.length === 0) {
    return messages.map((_, idx) => idx);
  }
  const startUserIdx = Math.max(0, userPositions.length - turnCount);
  const startMessageIdx = userPositions[startUserIdx];
  const result: number[] = [];
  for (let i = startMessageIdx; i < messages.length; i += 1) result.push(i);
  return result;
}

export default function SaveToNotebookModal({
  open,
  payload,
  messages,
  onClose,
  onSaved,
}: SaveToNotebookModalProps) {
  const { t } = useTranslation();
  const [notebooks, setNotebooks] = useState<RealNotebookSummary[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [title, setTitle] = useState("");
  const [titleEdited, setTitleEdited] = useState(false);
  const [summaryPreview, setSummaryPreview] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingNotebooks, setIsLoadingNotebooks] = useState(false);
  const [error, setError] = useState("");
  const [selectedMessageIdx, setSelectedMessageIdx] = useState<Set<number>>(
    new Set(),
  );
  const abortRef = useRef<AbortController | null>(null);

  const hasMessageSelection = Array.isArray(messages) && messages.length > 0;

  useEffect(() => {
    if (!open) {
      abortRef.current?.abort();
      return;
    }
    setSummaryPreview("");
    setError("");
    setSelectedIds([]);
    setTitleEdited(false);
    if (hasMessageSelection && messages) {
      setSelectedMessageIdx(new Set(messages.map((_, idx) => idx)));
      setTitle(deriveTitle(messages, payload?.title || ""));
    } else {
      setSelectedMessageIdx(new Set());
      setTitle(payload?.title || "");
    }
    setIsLoadingNotebooks(true);
    void (async () => {
      try {
        const list = await listNotebooks();
        setNotebooks(list);
      } catch {
        setNotebooks([]);
      } finally {
        setIsLoadingNotebooks(false);
      }
    })();
  }, [open, payload, messages, hasMessageSelection]);

  const orderedSelectedMessages = useMemo<NotebookSaveMessage[]>(() => {
    if (!hasMessageSelection || !messages) return [];
    const indexes = Array.from(selectedMessageIdx).sort((a, b) => a - b);
    return indexes
      .map((idx) => messages[idx])
      .filter((msg): msg is NotebookSaveMessage => Boolean(msg));
  }, [hasMessageSelection, messages, selectedMessageIdx]);

  // When the user hasn't manually edited the title yet, keep it in sync
  // with the first selected user message so it stays meaningful as the
  // selection changes.
  useEffect(() => {
    if (!open || !hasMessageSelection || titleEdited) return;
    const next = deriveTitle(orderedSelectedMessages, payload?.title || "");
    setTitle(next);
  }, [
    open,
    hasMessageSelection,
    titleEdited,
    orderedSelectedMessages,
    payload?.title,
  ]);

  const effectiveOutput = useMemo(() => {
    if (hasMessageSelection) {
      return buildTranscript(orderedSelectedMessages);
    }
    return payload?.output || "";
  }, [hasMessageSelection, orderedSelectedMessages, payload?.output]);

  const effectiveUserQuery = useMemo(() => {
    if (hasMessageSelection) {
      return buildUserQuery(orderedSelectedMessages);
    }
    return payload?.userQuery || "";
  }, [hasMessageSelection, orderedSelectedMessages, payload?.userQuery]);

  const canSave = useMemo(
    () =>
      Boolean(
        payload &&
        title.trim() &&
        selectedIds.length > 0 &&
        effectiveOutput.trim() &&
        (!hasMessageSelection || orderedSelectedMessages.length > 0),
      ),
    [
      payload,
      title,
      selectedIds.length,
      effectiveOutput,
      hasMessageSelection,
      orderedSelectedMessages.length,
    ],
  );

  const toggleNotebook = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    );
  };

  const toggleMessage = (idx: number) => {
    setSelectedMessageIdx((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  };

  const selectAllMessages = () => {
    if (!messages) return;
    setSelectedMessageIdx(new Set(messages.map((_, idx) => idx)));
  };

  const clearMessages = () => {
    setSelectedMessageIdx(new Set());
  };

  const selectLastTurns = (turnCount: number) => {
    if (!messages) return;
    setSelectedMessageIdx(new Set(indexesForLastTurns(messages, turnCount)));
  };

  const handleSave = async () => {
    if (!payload || !canSave) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setIsLoading(true);
    setError("");
    setSummaryPreview("");

    const metadata: Record<string, unknown> = { ...(payload.metadata || {}) };
    if (hasMessageSelection && messages) {
      metadata.message_count = orderedSelectedMessages.length;
      metadata.total_message_count = messages.length;
      metadata.selected_message_indexes = Array.from(selectedMessageIdx).sort(
        (a, b) => a - b,
      );
    }

    try {
      const response = await apiFetch(
        apiUrl("/api/v1/notebook/add_record_with_summary"),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            notebook_ids: selectedIds,
            record_type: payload.recordType,
            title: title.trim(),
            user_query: effectiveUserQuery,
            output: effectiveOutput,
            metadata,
            kb_name: payload.kbName || null,
          }),
          signal: controller.signal,
        },
      );

      if (!response.ok || !response.body) {
        throw new Error(t("Failed to save to notebook."));
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalSummary = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lastSeparator = buffer.lastIndexOf("\n\n");
        if (lastSeparator === -1) continue;

        const consumable = buffer.slice(0, lastSeparator + 2);
        buffer = buffer.slice(lastSeparator + 2);

        for (const event of parseSseEvents(consumable)) {
          const type = String(event.payload.type || "");
          if (type === "summary_chunk") {
            const chunk = String(event.payload.content || "");
            finalSummary += chunk;
            setSummaryPreview(finalSummary);
          } else if (type === "error") {
            throw new Error(
              String(event.payload.detail || t("Failed to save to notebook.")),
            );
          } else if (type === "result") {
            const summary = String(event.payload.summary || finalSummary);
            setSummaryPreview(summary);
            onSaved?.({ summary });
            setIsLoading(false);
            onClose();
            return;
          }
        }
      }

      throw new Error(t("Notebook save stream ended unexpectedly."));
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(
        err instanceof Error ? err.message : t("Failed to save to notebook."),
      );
      setIsLoading(false);
    }
  };

  // payload may be null while the parent is preparing the save context.
  // Treat that as "not open" so the shell never renders without content.
  const isOpen = open && !!payload;

  const totalMessages = messages?.length ?? 0;
  const selectedMessageCount = selectedMessageIdx.size;
  const allMessagesSelected =
    totalMessages > 0 && selectedMessageCount === totalMessages;

  return (
    <PickerShell
      open={isOpen}
      onClose={onClose}
      labelledBy="save-to-notebook-title"
      zIndex={80}
      className="p-4 backdrop-blur-md"
      backdropClass="bg-[var(--background)]/65"
    >
      <div className="surface-card flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] text-[var(--card-foreground)] shadow-[0_22px_70px_rgba(0,0,0,0.18)]">
        <PickerHeader
          icon={NotebookPen}
          titleId="save-to-notebook-title"
          title={t("Save to Notebook")}
          subtitle={
            hasMessageSelection
              ? t(
                  "Choose which messages to include, pick one or more notebooks, and a summary will be generated automatically.",
                )
              : t(
                  "Select one or more notebooks. A summary will be generated automatically.",
                )
          }
          onClose={onClose}
        />

        <div className="flex-1 space-y-5 overflow-y-auto bg-[var(--background)]/40 px-5 py-5">
          <div>
            <label className="mb-2 block text-sm font-medium text-[var(--foreground)]">
              {t("Title")}
            </label>
            <input
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
                setTitleEdited(true);
              }}
              className="w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-2.5 text-sm text-[var(--foreground)] outline-none transition focus:border-[var(--primary)]/60 focus:ring-2 focus:ring-[var(--primary)]/15"
            />
          </div>

          {hasMessageSelection && messages && (
            <div>
              <div className="mb-2 flex items-center justify-between gap-2">
                <label className="block text-sm font-medium text-[var(--foreground)]">
                  {t("Messages to include")}
                </label>
                <span className="text-xs text-[var(--muted-foreground)]">
                  {t("{{selected}} of {{total}} selected", {
                    selected: selectedMessageCount,
                    total: totalMessages,
                  })}
                </span>
              </div>
              <div className="mb-2 flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  onClick={selectAllMessages}
                  disabled={allMessagesSelected}
                  className="rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--primary)]/40 hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {t("Select all")}
                </button>
                <button
                  type="button"
                  onClick={clearMessages}
                  disabled={selectedMessageCount === 0}
                  className="rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--primary)]/40 hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {t("Clear")}
                </button>
                <button
                  type="button"
                  onClick={() => selectLastTurns(1)}
                  className="rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--primary)]/40 hover:text-[var(--foreground)]"
                >
                  {t("Last turn")}
                </button>
                <button
                  type="button"
                  onClick={() => selectLastTurns(3)}
                  className="rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--primary)]/40 hover:text-[var(--foreground)]"
                >
                  {t("Last 3 turns")}
                </button>
              </div>
              <div className="max-h-72 space-y-1.5 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--card)] p-2">
                {messages.map((msg, idx) => {
                  const selected = selectedMessageIdx.has(idx);
                  const Icon =
                    msg.role === "user"
                      ? User
                      : msg.role === "assistant"
                        ? Sparkles
                        : MessageSquare;
                  const preview = msg.content.replace(/\s+/g, " ").trim();
                  const empty = preview.length === 0;
                  return (
                    <button
                      key={idx}
                      type="button"
                      onClick={() => toggleMessage(idx)}
                      className={`flex w-full items-start gap-3 rounded-lg border px-3 py-2 text-left transition ${
                        selected
                          ? "border-[var(--primary)]/40 bg-[var(--primary)]/8"
                          : "border-transparent hover:border-[var(--border)] hover:bg-[var(--muted)]/40"
                      }`}
                    >
                      <span
                        className={`mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-md border transition-colors ${
                          selected
                            ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                            : "border-[var(--border)] text-transparent"
                        }`}
                      >
                        <Check className="h-3 w-3" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="mb-0.5 flex items-center gap-1.5 text-[11px] font-medium text-[var(--muted-foreground)]">
                          <Icon className="h-3 w-3" />
                          <span>{t(roleLabelKey(msg.role))}</span>
                          <span className="text-[var(--muted-foreground)]/60">
                            ·
                          </span>
                          <span>#{idx + 1}</span>
                        </div>
                        <p
                          className={`line-clamp-2 text-xs leading-5 ${
                            empty
                              ? "italic text-[var(--muted-foreground)]/70"
                              : "text-[var(--foreground)]/85"
                          }`}
                        >
                          {empty ? t("(empty message)") : preview}
                        </p>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          <div>
            <div className="mb-2 flex items-center justify-between">
              <label className="block text-sm font-medium text-[var(--foreground)]">
                {t("Notebooks")}
              </label>
              {selectedIds.length > 0 && (
                <span className="text-xs text-[var(--muted-foreground)]">
                  {selectedIds.length} {t("selected")}
                </span>
              )}
            </div>
            <div className="max-h-64 space-y-2 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--card)] p-2">
              {isLoadingNotebooks ? (
                <div className="flex items-center justify-center px-3 py-8">
                  <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
                </div>
              ) : notebooks.length === 0 ? (
                <div className="flex flex-col items-center gap-2 px-3 py-6 text-center text-sm text-[var(--muted-foreground)]">
                  <NotebookPen className="h-5 w-5 text-[var(--muted-foreground)]/60" />
                  <span>{t("No notebooks found.")}</span>
                  <span className="text-[11px] text-[var(--muted-foreground)]/80">
                    {t("Create one from the Knowledge → Notebooks page.")}
                  </span>
                </div>
              ) : (
                notebooks.map((notebook) => {
                  const selected = selectedIds.includes(notebook.id);
                  return (
                    <button
                      key={notebook.id}
                      onClick={() => toggleNotebook(notebook.id)}
                      className={`flex w-full items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition ${
                        selected
                          ? "border-[var(--primary)]/40 bg-[var(--primary)]/8"
                          : "border-transparent hover:border-[var(--border)] hover:bg-[var(--muted)]/40"
                      }`}
                    >
                      <div
                        className="mt-1 h-3 w-3 shrink-0 rounded-full"
                        style={{
                          backgroundColor: notebook.color || "var(--primary)",
                        }}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-sm font-medium text-[var(--foreground)]">
                            {notebook.name}
                          </div>
                          <span
                            className={`flex h-4.5 w-4.5 shrink-0 items-center justify-center rounded-md border transition-colors ${
                              selected
                                ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                                : "border-[var(--border)] text-transparent"
                            }`}
                            style={{ width: 18, height: 18 }}
                          >
                            <Check className="h-3 w-3" />
                          </span>
                        </div>
                        {notebook.description && (
                          <p className="mt-1 line-clamp-2 text-xs text-[var(--muted-foreground)]">
                            {notebook.description}
                          </p>
                        )}
                        <div className="mt-1 text-[11px] text-[var(--muted-foreground)]/85">
                          {notebook.record_count ?? 0} {t("records")}
                        </div>
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </div>

          <div>
            <div className="mb-2 text-sm font-medium text-[var(--foreground)]">
              {t("Summary preview")}
            </div>
            <div className="min-h-24 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-sm leading-6 text-[var(--foreground)]/85">
              {summaryPreview || (
                <span className="text-[var(--muted-foreground)]">
                  {t("The generated summary will appear here during saving.")}
                </span>
              )}
            </div>
          </div>

          {error && (
            <div className="rounded-xl border border-[var(--destructive)]/30 bg-[var(--destructive)]/8 px-4 py-3 text-sm text-[var(--destructive)]">
              {error}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[var(--border)] bg-[var(--card)] px-5 py-4">
          <button
            onClick={onClose}
            className="rounded-xl px-4 py-2 text-sm text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            {t("Cancel")}
          </button>
          <button
            onClick={handleSave}
            disabled={!canSave || isLoading}
            className="btn-primary inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
            {t("Save")}
          </button>
        </div>
      </div>
    </PickerShell>
  );
}
