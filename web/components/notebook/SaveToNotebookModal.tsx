"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { apiUrl } from "@/lib/api";
import { listCategories } from "@/lib/notebook-api";

type RecordType =
  | "solve"
  | "question"
  | "research"
  | "co_writer"
  | "chat"
  | "guided_learning";

interface NotebookSummary {
  id: string;
  name: string;
  color?: string;
  description?: string;
}

export interface NotebookSavePayload {
  recordType: RecordType;
  title: string;
  userQuery: string;
  output: string;
  metadata?: Record<string, unknown>;
  kbName?: string | null;
}

interface SaveToNotebookModalProps {
  open: boolean;
  payload: NotebookSavePayload | null;
  onClose: () => void;
  onSaved?: (result: { summary: string }) => void;
}

function parseSseEvents(buffer: string): Array<{ payload: Record<string, unknown> }> {
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
      const payload = JSON.parse(dataLine.slice(5).trim()) as Record<string, unknown>;
      events.push({ payload });
    } catch {
      continue;
    }
  }
  return events;
}

export default function SaveToNotebookModal({
  open,
  payload,
  onClose,
  onSaved,
}: SaveToNotebookModalProps) {
  const { t } = useTranslation();
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [title, setTitle] = useState("");
  const [summaryPreview, setSummaryPreview] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!open) {
      abortRef.current?.abort();
      return;
    }
    setTitle(payload?.title || "");
    setSummaryPreview("");
    setError("");
    setSelectedIds([]);
    void (async () => {
      try {
        const cats = await listCategories();
        setNotebooks(cats.map((c) => ({ id: String(c.id), name: c.name })));
      } catch {
        setNotebooks([]);
      }
    })();
  }, [open, payload]);

  const canSave = useMemo(
    () =>
      Boolean(
        payload &&
          title.trim() &&
          selectedIds.length > 0 &&
          payload.output.trim(),
      ),
    [payload, selectedIds.length, title],
  );

  const toggleNotebook = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    );
  };

  const handleSave = async () => {
    if (!payload || !canSave) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setIsLoading(true);
    setError("");
    setSummaryPreview("");

    try {
      const response = await fetch(apiUrl("/api/v1/notebook/add_record_with_summary"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          notebook_ids: selectedIds,
          record_type: payload.recordType,
          title: title.trim(),
          user_query: payload.userQuery,
          output: payload.output,
          metadata: payload.metadata || {},
          kb_name: payload.kbName || null,
        }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error("Failed to save to notebook.");
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
            throw new Error(String(event.payload.detail || "Failed to save to notebook."));
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

      throw new Error("Notebook save stream ended unexpectedly.");
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : "Failed to save to notebook.");
      setIsLoading(false);
    }
  };

  if (!open || !payload) return null;

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-md">
      <div className="w-full max-w-2xl rounded-[22px] border border-slate-200 bg-white shadow-[0_22px_70px_rgba(15,23,42,0.24)] dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 dark:border-slate-700">
          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-indigo-500">
              {t("Notebook Output")}
            </div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              {t("Save to Notebook")}
            </h2>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {t("Select one or more notebooks. A summary will be generated automatically.")}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-5 bg-slate-50/70 px-5 py-5 dark:bg-slate-950/35">
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-200">
              {t("Title")}
            </label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:focus:ring-indigo-900/40"
            />
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">
                {t("Notebooks")}
              </label>
              {selectedIds.length > 0 && (
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {selectedIds.length} selected
                </span>
              )}
            </div>
            <div className="max-h-64 space-y-2 overflow-y-auto rounded-xl border border-slate-200 bg-white p-2 dark:border-slate-800 dark:bg-slate-900">
              {notebooks.length === 0 ? (
                <div className="px-3 py-6 text-center text-sm text-slate-400 dark:text-slate-500">
                  {t("No notebooks found.")}
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
                          ? "border-indigo-200 bg-indigo-50 dark:border-indigo-800 dark:bg-indigo-950/25"
                          : "border-transparent hover:border-slate-200 hover:bg-slate-50 dark:hover:border-slate-700 dark:hover:bg-slate-800/70"
                      }`}
                    >
                      <div
                        className="mt-1 h-3 w-3 rounded-full"
                        style={{ backgroundColor: notebook.color || "#6366f1" }}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium text-slate-800 dark:text-slate-100">
                          {notebook.name}
                        </div>
                        {notebook.description && (
                          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                            {notebook.description}
                          </p>
                        )}
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </div>

          <div>
            <div className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              {t("Summary preview")}
            </div>
            <div className="min-h-24 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
              {summaryPreview || (
                <span className="text-slate-400 dark:text-slate-500">
                  {t("The generated summary will appear here during saving.")}
                </span>
              )}
            </div>
          </div>

          {error && (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
              {error}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-slate-200 px-5 py-4 dark:border-slate-700">
          <button
            onClick={onClose}
            className="rounded-xl px-4 py-2 text-sm text-slate-600 transition hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            {t("Cancel")}
          </button>
          <button
            onClick={handleSave}
            disabled={!canSave || isLoading}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-indigo-400 to-fuchsia-400 px-4 py-2 text-sm font-medium text-white transition hover:from-indigo-500 hover:to-fuchsia-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
            {t("Save")}
          </button>
        </div>
      </div>
    </div>
  );
}
