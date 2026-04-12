"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  ArrowRight,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Database,
  ExternalLink,
  FileUp,
  GraduationCap,
  Loader2,
  MessageSquare,
  NotebookPen,
  PenLine,
  Plus,
  Search,
  Star,
  Trash2,
  Upload,
} from "lucide-react";
import { apiUrl, wsUrl } from "@/lib/api";
import {
  invalidateKnowledgeCaches,
  listKnowledgeBases,
  listRagProviders,
} from "@/lib/knowledge-api";
import {
  getNotebookDetail,
  invalidateNotebookCaches,
  listNotebooks,
} from "@/lib/notebook-api";

const MarkdownRenderer = dynamic(() => import("@/components/common/MarkdownRenderer"), {
  ssr: false,
});
const ProcessLogs = dynamic(() => import("@/components/common/ProcessLogs"), {
  ssr: false,
});

interface ProgressInfo {
  task_id?: string;
  stage?: string;
  message?: string;
  current?: number;
  total?: number;
  percent?: number;
  progress_percent?: number;
}

interface KnowledgeBase {
  name: string;
  is_default?: boolean;
  status?: string;
  progress?: ProgressInfo;
  statistics?: {
    raw_documents?: number;
    rag_provider?: string;
    needs_reindex?: boolean;
    status?: string;
    progress?: ProgressInfo;
  };
}

interface NotebookInfo {
  id: string;
  name: string;
  description?: string;
  record_count?: number;
  color?: string;
  icon?: string;
  updated_at?: number;
}

interface NotebookRecord {
  id: string;
  type: string;
  title: string;
  summary?: string;
  user_query?: string;
  output: string;
  metadata?: Record<string, unknown>;
  created_at?: number;
}

interface NotebookDetail extends NotebookInfo {
  records: NotebookRecord[];
}

interface RAGProvider {
  id: string;
  name: string;
  description: string;
}

interface KnowledgeTaskResponse {
  task_id?: string;
}

interface ProcessState {
  taskId: string | null;
  label: string;
  logs: string[];
  executing: boolean;
  error: string | null;
}

type ProcessKind = "create" | "upload";

const EMPTY_PROCESS_STATE: ProcessState = {
  taskId: null,
  label: "",
  logs: [],
  executing: false,
  error: null,
};

const resolveKbStatus = (kb: KnowledgeBase): string => kb.status ?? kb.statistics?.status ?? "unknown";

const kbNeedsReindex = (kb: KnowledgeBase): boolean =>
  Boolean(kb.statistics?.needs_reindex) || resolveKbStatus(kb) === "needs_reindex";

const kbIsUploadable = (kb: KnowledgeBase): boolean =>
  resolveKbStatus(kb) === "ready" && !kbNeedsReindex(kb);

export default function KnowledgePage() {
  const router = useRouter();
  const { t } = useTranslation();
  const [tab, setTab] = useState<"knowledge" | "notebooks">("knowledge");
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [notebooks, setNotebooks] = useState<NotebookInfo[]>([]);
  const [providers, setProviders] = useState<RAGProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [uploadingKb, setUploadingKb] = useState<string | null>(null);
  const [progressMap, setProgressMap] = useState<Record<string, ProgressInfo>>({});
  const [newKbName, setNewKbName] = useState("");
  const [newKbFiles, setNewKbFiles] = useState<File[]>([]);
  const [selectedProvider, setSelectedProvider] = useState("llamaindex");
  const [uploadTarget, setUploadTarget] = useState("");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [newNotebookName, setNewNotebookName] = useState("");
  const [newNotebookDescription, setNewNotebookDescription] = useState("");
  const [selectedNotebookId, setSelectedNotebookId] = useState<string | null>(null);
  const [selectedNotebook, setSelectedNotebook] = useState<NotebookDetail | null>(null);
  const [loadingNotebookDetail, setLoadingNotebookDetail] = useState(false);
  const [expandedRecordId, setExpandedRecordId] = useState<string | null>(null);
  const [createProcess, setCreateProcess] = useState<ProcessState>(EMPTY_PROCESS_STATE);
  const [uploadProcess, setUploadProcess] = useState<ProcessState>(EMPTY_PROCESS_STATE);
  const socketsRef = useRef<Record<string, WebSocket>>({});
  const logSourcesRef = useRef<Record<ProcessKind, EventSource | null>>({
    create: null,
    upload: null,
  });
  const createFileRef = useRef<HTMLInputElement>(null);
  const uploadFileRef = useRef<HTMLInputElement>(null);

  const getProcessSetter = (kind: ProcessKind) =>
    kind === "create" ? setCreateProcess : setUploadProcess;

  const closeTaskLogStream = (kind: ProcessKind) => {
    logSourcesRef.current[kind]?.close();
    logSourcesRef.current[kind] = null;
  };

  const closeProgressSocket = (kbName: string) => {
    socketsRef.current[kbName]?.close();
    delete socketsRef.current[kbName];
  };

  const closeAllProgressSockets = () => {
    Object.values(socketsRef.current).forEach((socket) => socket.close());
    socketsRef.current = {};
  };

  const openTaskLogStream = (kind: ProcessKind, taskId: string, label: string) => {
    closeTaskLogStream(kind);
    const setProcess = getProcessSetter(kind);
    setProcess({
      taskId,
      label,
      logs: [],
      executing: true,
      error: null,
    });

    const source = new EventSource(apiUrl(`/api/v1/knowledge/tasks/${taskId}/stream`));
    logSourcesRef.current[kind] = source;

    let settled = false;

    source.addEventListener("log", (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data) as { line?: string };
        if (!payload.line) return;
        setProcess((prev) => ({
          ...prev,
          taskId,
          label,
          logs: [...prev.logs, payload.line!],
        }));
      } catch {
        // Ignore malformed log events.
      }
    });

    source.addEventListener("complete", () => {
      settled = true;
      setProcess((prev) => ({ ...prev, taskId, label, executing: false }));
      closeTaskLogStream(kind);
    });

    source.addEventListener("failed", (event) => {
      settled = true;
      let detail = "Task failed";
      try {
        const payload = JSON.parse((event as MessageEvent).data) as { detail?: string };
        detail = payload.detail || detail;
      } catch {
        // Ignore malformed failure events.
      }
      setProcess((prev) => ({
        ...prev,
        taskId,
        label,
        executing: false,
        error: detail,
      }));
      closeTaskLogStream(kind);
    });

    source.onerror = () => {
      if (settled) return;
      setProcess((prev) => {
        if (!prev.executing) return prev;
        return {
          ...prev,
          taskId,
          label,
          executing: false,
          error: prev.error || "Process log stream disconnected.",
        };
      });
      closeTaskLogStream(kind);
    };
  };

  const loadAll = async () => {
    setLoading(true);
    setPageError(null);
    try {
      const [kbs, providerData, nextNotebooks] = await Promise.all([
        listKnowledgeBases(),
        listRagProviders(),
        listNotebooks(),
      ]);
      setKnowledgeBases(kbs);
      setProviders(
        providerData.length
          ? providerData
          : [
              {
                id: "llamaindex",
                name: "LlamaIndex",
                description: "Pure vector retrieval, fastest processing speed.",
              },
            ],
      );
      setNotebooks(nextNotebooks);
      if (!selectedNotebookId && nextNotebooks.length > 0) {
        void loadNotebookDetail(nextNotebooks[0].id);
      } else if (selectedNotebookId) {
        const stillExists = nextNotebooks.some((item: NotebookInfo) => item.id === selectedNotebookId);
        if (stillExists) {
          void loadNotebookDetail(selectedNotebookId);
        } else {
          setSelectedNotebookId(null);
          setSelectedNotebook(null);
        }
      }

      const preferredUploadTarget =
        kbs.find((kb: KnowledgeBase) => kb.is_default && kbIsUploadable(kb))?.name ??
        kbs.find((kb: KnowledgeBase) => kbIsUploadable(kb))?.name ??
        "";
      setUploadTarget((prev) => {
        if (prev && kbs.some((kb: KnowledgeBase) => kb.name === prev && kbIsUploadable(kb))) {
          return prev;
        }
        return preferredUploadTarget;
      });

      for (const kb of kbs) {
        const status = kb.status ?? kb.statistics?.status;
        const progress = kb.progress ?? kb.statistics?.progress;
        if (status && status !== "ready" && status !== "error") {
          setProgressMap((prev) => ({ ...prev, [kb.name]: progress || prev[kb.name] || {} }));
          subscribeProgress(kb.name);
        }
      }
    } catch (error) {
      setPageError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
    return () => {
      closeAllProgressSockets();
      closeTaskLogStream("create");
      closeTaskLogStream("upload");
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const subscribeProgress = (kbName: string, expectedTaskId?: string) => {
    closeProgressSocket(kbName);

    const query = expectedTaskId ? `?task_id=${encodeURIComponent(expectedTaskId)}` : "";
    const socket = new WebSocket(wsUrl(`/api/v1/knowledge/${kbName}/progress/ws${query}`));
    socketsRef.current[kbName] = socket;

    socket.onmessage = (event) => {
      try {
        const rawData = JSON.parse(event.data) as {
          type?: string;
          data?: ProgressInfo;
          message?: string;
        };
        const progress =
          rawData?.type === "progress" && rawData.data ? rawData.data : (rawData as ProgressInfo);
        if (!progress || typeof progress !== "object") return;
        if (expectedTaskId && progress.task_id && progress.task_id !== expectedTaskId) return;

        setProgressMap((prev) => ({ ...prev, [kbName]: progress }));
        const stage = progress.stage;
        if (stage === "completed" || stage === "error") {
          closeProgressSocket(kbName);
          void loadAll();
        }
      } catch {
        // Ignore malformed progress events.
      }
    };

    socket.onerror = () => {
      closeProgressSocket(kbName);
    };

    socket.onclose = () => {
      delete socketsRef.current[kbName];
    };
  };

  const createKnowledgeBase = async () => {
    if (!newKbName.trim() || !newKbFiles.length) return;
    const kbName = newKbName.trim();
    const fileCount = newKbFiles.length;
    setCreating(true);
    try {
      const form = new FormData();
      form.append("name", kbName);
      form.append("rag_provider", selectedProvider);
      newKbFiles.forEach((file) => form.append("files", file));

      const res = await fetch(apiUrl("/api/v1/knowledge/create"), {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Failed to create knowledge base");
      }

      const data = (await res.json()) as KnowledgeTaskResponse;
      invalidateKnowledgeCaches();
      if (data.task_id) {
        openTaskLogStream("create", data.task_id, `Create ${kbName}`);
        subscribeProgress(kbName, data.task_id);
        setProgressMap((prev) => ({
          ...prev,
          [kbName]: {
            task_id: data.task_id,
            stage: "initializing",
            message: "Initializing knowledge base...",
            current: 0,
            total: fileCount,
            progress_percent: 0,
          },
        }));
      } else {
        subscribeProgress(kbName);
      }

      setNewKbName("");
      setNewKbFiles([]);
      if (createFileRef.current) createFileRef.current.value = "";
      await loadAll();
    } catch (error) {
      setCreateProcess((prev) => ({
        ...prev,
        executing: false,
        error: error instanceof Error ? error.message : String(error),
        label: prev.label || `Create ${kbName}`,
      }));
    } finally {
      setCreating(false);
    }
  };

  const uploadToKnowledgeBase = async () => {
    if (!uploadTarget || !uploadFiles.length) return;
    const targetKb = uploadTarget;
    const fileCount = uploadFiles.length;
    setUploadingKb(uploadTarget);
    try {
      const form = new FormData();
      uploadFiles.forEach((file) => form.append("files", file));
      if (selectedProvider) form.append("rag_provider", selectedProvider);

      const res = await fetch(apiUrl(`/api/v1/knowledge/${targetKb}/upload`), {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.detail || "Failed to upload files");
      }

      const data = (await res.json()) as KnowledgeTaskResponse;
      invalidateKnowledgeCaches();
      if (data.task_id) {
        openTaskLogStream("upload", data.task_id, `Upload to ${targetKb}`);
        subscribeProgress(targetKb, data.task_id);
        setProgressMap((prev) => ({
          ...prev,
          [targetKb]: {
            task_id: data.task_id,
            stage: "processing_documents",
            message: `Processing ${fileCount} files...`,
            current: 0,
            total: fileCount,
            progress_percent: 0,
          },
        }));
      } else {
        subscribeProgress(targetKb);
      }

      setUploadFiles([]);
      if (uploadFileRef.current) uploadFileRef.current.value = "";
      await loadAll();
    } catch (error) {
      setUploadProcess((prev) => ({
        ...prev,
        executing: false,
        error: error instanceof Error ? error.message : String(error),
        label: prev.label || `Upload to ${targetKb}`,
      }));
    } finally {
      setUploadingKb(null);
    }
  };

  const setDefaultKnowledgeBase = async (kbName: string) => {
    await fetch(apiUrl(`/api/v1/knowledge/default/${kbName}`), { method: "PUT" });
    invalidateKnowledgeCaches();
    await loadAll();
  };

  const deleteKnowledgeBase = async (kbName: string) => {
    if (!window.confirm(t('Delete knowledge base "{{name}}"?', { name: kbName }))) return;
    await fetch(apiUrl(`/api/v1/knowledge/${kbName}`), { method: "DELETE" });
    invalidateKnowledgeCaches();
    await loadAll();
  };

  const createNotebook = async () => {
    if (!newNotebookName.trim()) return;
    await fetch(apiUrl("/api/v1/notebook/create"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: newNotebookName.trim(),
        description: newNotebookDescription.trim(),
      }),
    });
    invalidateNotebookCaches();
    setNewNotebookName("");
    setNewNotebookDescription("");
    await loadAll();
  };

  const loadNotebookDetail = async (notebookId: string) => {
    setSelectedNotebookId(notebookId);
    setExpandedRecordId(null);
    setLoadingNotebookDetail(true);
    try {
      const notebook = (await getNotebookDetail(notebookId)) as NotebookDetail;
      setSelectedNotebook(notebook);
    } catch {
      setSelectedNotebook(null);
    } finally {
      setLoadingNotebookDetail(false);
    }
  };

  const openNotebookRecord = (record: NotebookRecord) => {
    const sessionId = String(record.metadata?.session_id || "");
    if (!sessionId) return;
    if (record.type === "chat") {
      router.push(`/?session=${encodeURIComponent(sessionId)}`);
      return;
    }
    if (record.type === "guided_learning") {
      router.push(`/guide?session=${encodeURIComponent(sessionId)}`);
    }
  };

  const formatTimestamp = (value?: number) => {
    if (!value) return t("Unknown time");
    return new Date(value * 1000).toLocaleString();
  };

  const getRecordBadge = (type: string) => {
    switch (type) {
      case "chat":
        return { label: t("Chat"), color: "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300", icon: MessageSquare };
      case "guided_learning":
        return { label: t("Guided Learning"), color: "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300", icon: GraduationCap };
      case "co_writer":
        return { label: t("Co-Writer"), color: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300", icon: PenLine };
      case "research":
        return { label: t("Research"), color: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300", icon: Search };
      default:
        return { label: type, color: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400", icon: NotebookPen };
    }
  };

  const combinedKbs = useMemo(
    () =>
      knowledgeBases.map((kb) => ({
        ...kb,
        status: kb.status ?? kb.statistics?.status,
        progress: progressMap[kb.name] || kb.progress || kb.statistics?.progress,
      })),
    [knowledgeBases, progressMap],
  );

  const hasUploadableKb = useMemo(
    () => combinedKbs.some((kb) => kbIsUploadable(kb)),
    [combinedKbs],
  );

  const uploadTargetKb = useMemo(
    () => combinedKbs.find((kb) => kb.name === uploadTarget) ?? null,
    [combinedKbs, uploadTarget],
  );

  const uploadBlockedReason = useMemo(() => {
    if (!uploadTargetKb) return null;
    if (kbNeedsReindex(uploadTargetKb)) {
      return t("This knowledge base is in legacy index format and needs reindex before upload.");
    }
    const status = resolveKbStatus(uploadTargetKb);
    if (status !== "ready") {
      return t("This knowledge base is currently {{status}} and cannot accept uploads yet.", { status: status.replaceAll("_", " ") });
    }
    return null;
  }, [uploadTargetKb]);

  const uploadDisabled =
    !uploadTarget || !uploadFiles.length || !!uploadingKb || Boolean(uploadBlockedReason);

  return (
    <div className="h-full overflow-y-auto bg-[var(--background)] [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-5xl px-6 py-8 pb-10">
        {/* Header */}
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-[var(--foreground)]">
              {t("Knowledge")}
            </h1>
            <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
              {t("Manage your knowledge bases and notebooks in one place.")}
            </p>
          </div>

          <div className="inline-flex shrink-0 rounded-lg border border-[var(--border)] bg-[var(--muted)] p-0.5">
            {[
              { key: "knowledge", label: t("Knowledge Bases"), icon: Database },
              { key: "notebooks", label: t("Notebooks"), icon: NotebookPen },
            ].map((item) => (
              <button
                key={item.key}
                onClick={() => setTab(item.key as "knowledge" | "notebooks")}
                className={`inline-flex items-center gap-1.5 rounded-md px-3.5 py-1.5 text-[13px] font-medium transition-all ${
                  tab === item.key
                    ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
                    : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                <item.icon size={14} />
                {item.label}
              </button>
            ))}
          </div>
        </div>

        {pageError && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
            {pageError}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
          </div>
        ) : tab === "knowledge" ? (
          <div className="space-y-5">
            <div className="grid gap-5 lg:grid-cols-2">
              {/* Create KB */}
              <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
                <div className="mb-4 flex items-center gap-2">
                  <Plus size={15} className="text-[var(--muted-foreground)]" />
                  <h2 className="text-[14px] font-semibold text-[var(--foreground)]">
                    {t("Create knowledge base")}
                  </h2>
                </div>

                <div className="space-y-3">
                  <input
                    value={newKbName}
                    onChange={(event) => setNewKbName(event.target.value)}
                    placeholder={t("Knowledge base name")}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25"
                  />

                  <select
                    value={selectedProvider}
                    onChange={(event) => setSelectedProvider(event.target.value)}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none"
                  >
                    {providers.map((provider) => (
                      <option key={provider.id} value={provider.id}>
                        {provider.name}
                      </option>
                    ))}
                  </select>

                  {/* Styled file upload area */}
                  <button
                    type="button"
                    onClick={() => createFileRef.current?.click()}
                    className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-[var(--border)] bg-[var(--background)] px-4 py-3 text-[13px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--foreground)]/25 hover:text-[var(--foreground)]"
                  >
                    <FileUp size={15} />
                    {newKbFiles.length
                      ? newKbFiles.length > 1
                        ? t("{n} files selected", { n: newKbFiles.length })
                        : t("{n} file selected", { n: newKbFiles.length })
                      : t("Choose files...")}
                  </button>
                  <input
                    ref={createFileRef}
                    type="file"
                    multiple
                    className="hidden"
                    onChange={(event) =>
                      setNewKbFiles(Array.from(event.target.files || []))
                    }
                  />

                  {!!newKbFiles.length && (
                    <div className="flex flex-wrap gap-1.5">
                      {newKbFiles.map((file) => (
                        <span
                          key={file.name}
                          className="rounded-md bg-[var(--muted)] px-2 py-0.5 text-[11px] text-[var(--muted-foreground)]"
                        >
                          {file.name}
                        </span>
                      ))}
                    </div>
                  )}

                  <button
                    onClick={createKnowledgeBase}
                    disabled={creating || !newKbName.trim() || !newKbFiles.length}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-1.5 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus size={14} />}
                    {t("Create")}
                  </button>

                  {(createProcess.taskId || createProcess.logs.length > 0 || createProcess.executing) && (
                    <div className="space-y-2">
                      {createProcess.label && (
                        <div className="text-[11px] text-[var(--muted-foreground)]">
                          {createProcess.label}
                          {createProcess.taskId ? ` · ${createProcess.taskId}` : ""}
                        </div>
                      )}
                      <ProcessLogs
                        logs={createProcess.logs}
                        executing={createProcess.executing}
                        title={t("Create Process")}
                      />
                    </div>
                  )}

                  {createProcess.error && (
                    <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                      {createProcess.error}
                    </div>
                  )}
                </div>
              </section>

              {/* Upload to existing KB */}
              <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
                <div className="mb-4 flex items-center gap-2">
                  <Upload size={15} className="text-[var(--muted-foreground)]" />
                  <h2 className="text-[14px] font-semibold text-[var(--foreground)]">
                    {t("Upload documents")}
                  </h2>
                </div>

                <div className="space-y-3">
                  <select
                    value={uploadTarget}
                    onChange={(event) => setUploadTarget(event.target.value)}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none"
                  >
                    <option value="">{t("Select a knowledge base")}</option>
                    {combinedKbs.map((kb) => {
                      const status = resolveKbStatus(kb);
                      const needsReindex = kbNeedsReindex(kb);
                      const uploadable = kbIsUploadable(kb);
                      let suffix = "";
                      if (needsReindex) {
                        suffix = ` (${t("needs reindex")})`;
                      } else if (status !== "ready") {
                        suffix = ` (${status.replaceAll("_", " ")})`;
                      }
                      return (
                        <option key={kb.name} value={kb.name} disabled={!uploadable}>
                          {kb.name}
                          {suffix}
                        </option>
                      );
                    })}
                  </select>

                  {!hasUploadableKb && (
                    <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-700 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
                      {t("No ready knowledge base is available for upload. Create a new KB or reindex legacy KBs first.")}
                    </div>
                  )}

                  {uploadBlockedReason && (
                    <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-700 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
                      {uploadBlockedReason}
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={() => uploadFileRef.current?.click()}
                    className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-[var(--border)] bg-[var(--background)] px-4 py-3 text-[13px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--foreground)]/25 hover:text-[var(--foreground)]"
                  >
                    <FileUp size={15} />
                    {uploadFiles.length
                      ? uploadFiles.length > 1
                        ? t("{n} files selected", { n: uploadFiles.length })
                        : t("{n} file selected", { n: uploadFiles.length })
                      : t("Choose files...")}
                  </button>
                  <input
                    ref={uploadFileRef}
                    type="file"
                    multiple
                    className="hidden"
                    onChange={(event) =>
                      setUploadFiles(Array.from(event.target.files || []))
                    }
                  />

                  {!!uploadFiles.length && (
                    <div className="flex flex-wrap gap-1.5">
                      {uploadFiles.map((file) => (
                        <span
                          key={file.name}
                          className="rounded-md bg-[var(--muted)] px-2 py-0.5 text-[11px] text-[var(--muted-foreground)]"
                        >
                          {file.name}
                        </span>
                      ))}
                    </div>
                  )}

                  <button
                    onClick={uploadToKnowledgeBase}
                    disabled={uploadDisabled}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3.5 py-1.5 text-[13px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {uploadingKb ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Upload size={14} />
                    )}
                    {t("Upload")}
                  </button>

                  {(uploadProcess.taskId || uploadProcess.logs.length > 0 || uploadProcess.executing) && (
                    <div className="space-y-2">
                      {uploadProcess.label && (
                        <div className="text-[11px] text-[var(--muted-foreground)]">
                          {uploadProcess.label}
                          {uploadProcess.taskId ? ` · ${uploadProcess.taskId}` : ""}
                        </div>
                      )}
                      <ProcessLogs
                        logs={uploadProcess.logs}
                        executing={uploadProcess.executing}
                        title={t("Upload Process")}
                      />
                    </div>
                  )}

                  {uploadProcess.error && (
                    <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                      {uploadProcess.error}
                    </div>
                  )}
                </div>
              </section>
            </div>

            {/* KB list */}
            <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
              <div className="mb-4 flex items-center gap-2">
                <BookOpen size={15} className="text-[var(--muted-foreground)]" />
                <h2 className="text-[14px] font-semibold text-[var(--foreground)]">
                  {t("Knowledge bases")}
                </h2>
              </div>

              <div className="space-y-3">
                {combinedKbs.map((kb) => {
                  const progress = kb.progress;
                  const status = resolveKbStatus(kb);
                  const needsReindex = kbNeedsReindex(kb);
                  const displayStatus =
                    needsReindex
                      ? t("needs reindex")
                      : status !== "ready"
                        ? status.replaceAll("_", " ")
                        : null;
                  const percent =
                    progress?.progress_percent ??
                    progress?.percent ??
                    ((progress?.current ?? 0) && (progress?.total ?? 0)
                      ? Math.round(((progress?.current ?? 0) / (progress?.total ?? 1)) * 100)
                      : 0);

                  return (
                    <div
                      key={kb.name}
                      className="group rounded-lg border border-[var(--border)] bg-[var(--background)] p-4 transition-colors hover:border-[var(--foreground)]/10"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <h3 className="text-[14px] font-medium text-[var(--foreground)]">
                              {kb.name}
                            </h3>
                            {kb.is_default && (
                              <span className="inline-flex items-center gap-1 rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                                <Star size={10} /> {t("Default")}
                              </span>
                            )}
                          </div>
                          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-[var(--muted-foreground)]">
                            <span>{t("Provider")}: {kb.statistics?.rag_provider || "llamaindex"}</span>
                            <span>{t("Documents")}: {kb.statistics?.raw_documents ?? 0}</span>
                            {displayStatus && (
                              <span
                                className={
                                  needsReindex
                                    ? "font-medium text-amber-600 dark:text-amber-400"
                                    : "capitalize"
                                }
                              >
                                {t("Status")}: {displayStatus}
                              </span>
                            )}
                          </div>
                        </div>

                        <div className="flex items-center gap-1.5">
                          {!kb.is_default && (
                            <button
                              onClick={() => setDefaultKnowledgeBase(kb.name)}
                              className="rounded-md border border-[var(--border)] px-2.5 py-1 text-[12px] text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
                            >
                              {t("Set default")}
                            </button>
                          )}
                          <button
                            onClick={() => deleteKnowledgeBase(kb.name)}
                            className="rounded-md border border-[var(--border)] p-1.5 text-[var(--muted-foreground)] transition-colors hover:border-red-200 hover:bg-red-50 hover:text-red-600 dark:hover:border-red-900 dark:hover:bg-red-950/30 dark:hover:text-red-400"
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </div>

                      {progress?.message && (
                        <div className="mt-3 rounded-lg bg-[var(--muted)] p-3">
                          <div className="text-[12px] text-[var(--foreground)]">
                            {progress.message}
                          </div>
                          {percent > 0 && (
                            <div className="mt-2 h-1 overflow-hidden rounded-full bg-[var(--border)]">
                              <div
                                className="h-full rounded-full bg-[var(--primary)] transition-all duration-300"
                                style={{ width: `${percent}%` }}
                              />
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}

                {!combinedKbs.length && (
                  <div className="rounded-lg border border-dashed border-[var(--border)] px-6 py-10 text-center text-[13px] text-[var(--muted-foreground)]">
                    {t("No knowledge bases yet. Create one to get started.")}
                  </div>
                )}
              </div>
            </section>
          </div>
        ) : (
          <div className="space-y-5">
            {/* Create notebook */}
            <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
              <div className="mb-4 flex items-center gap-2">
                <Plus size={15} className="text-[var(--muted-foreground)]" />
                <h2 className="text-[14px] font-semibold text-[var(--foreground)]">
                  {t("Create notebook")}
                </h2>
              </div>

              <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
                <input
                  value={newNotebookName}
                  onChange={(event) => setNewNotebookName(event.target.value)}
                  placeholder={t("Notebook name")}
                  className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25"
                />
                <input
                  value={newNotebookDescription}
                  onChange={(event) => setNewNotebookDescription(event.target.value)}
                  placeholder={t("Description")}
                  className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25"
                />
                <button
                  onClick={createNotebook}
                  disabled={!newNotebookName.trim()}
                  className="rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[13px] font-medium text-[var(--primary-foreground)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {t("Create")}
                </button>
              </div>
            </section>

            {/* Notebook list */}
            <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
              <div className="mb-4 flex items-center gap-2">
                <NotebookPen size={15} className="text-[var(--muted-foreground)]" />
                <h2 className="text-[14px] font-semibold text-[var(--foreground)]">
                  {t("Notebooks")}
                </h2>
              </div>

              <div className="grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)]">
                <div className="xl:sticky xl:top-8 xl:max-h-[calc(100vh-12rem)] space-y-3 overflow-y-auto pr-1">
                  {notebooks.map((notebook) => {
                    const active = selectedNotebookId === notebook.id;
                    return (
                      <button
                        key={notebook.id}
                        onClick={() => void loadNotebookDetail(notebook.id)}
                        className={`w-full rounded-xl border p-4 text-left transition-all ${
                          active
                            ? "border-indigo-200 bg-indigo-50/70 shadow-[0_8px_24px_rgba(99,102,241,0.08)] dark:border-indigo-800 dark:bg-indigo-950/25"
                            : "border-[var(--border)] bg-[var(--background)] hover:border-[var(--foreground)]/12 hover:bg-[var(--muted)]/18"
                        }`}
                      >
                        <div className="flex items-start gap-3">
                          <div
                            className="mt-1 h-3 w-3 rounded-full"
                            style={{ backgroundColor: notebook.color || "#6366f1" }}
                          />
                          <div className="min-w-0 flex-1">
                            <div className="text-[14px] font-semibold text-[var(--foreground)]">
                              {notebook.name}
                            </div>
                            {notebook.description && (
                              <p className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                                {notebook.description}
                              </p>
                            )}
                            <div className="mt-3 flex items-center justify-between text-[11px] text-[var(--muted-foreground)]">
                              <span>{notebook.record_count ?? 0} {t("records")}</span>
                              <span>{notebook.updated_at ? formatTimestamp(notebook.updated_at) : ""}</span>
                            </div>
                          </div>
                        </div>
                      </button>
                    );
                  })}

                  {!notebooks.length && (
                    <div className="rounded-xl border border-dashed border-[var(--border)] px-6 py-10 text-center text-[13px] text-[var(--muted-foreground)]">
                      {t("No notebooks yet. Create one to organize outputs.")}
                    </div>
                  )}
                </div>

                <div className="flex min-h-[560px] flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--background)] p-4 xl:h-[calc(100vh-12rem)]">
                  {loadingNotebookDetail ? (
                    <div className="flex min-h-[320px] items-center justify-center">
                      <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
                    </div>
                  ) : selectedNotebook ? (
                    <div className="flex min-h-0 flex-1 flex-col">
                      <div className="mb-3 flex shrink-0 items-center justify-between gap-4 pb-3">
                        <div className="flex items-center gap-2.5">
                          <div
                            className="h-2.5 w-2.5 rounded-full"
                            style={{ backgroundColor: selectedNotebook.color || "#6366f1" }}
                          />
                          <h3 className="text-[15px] font-semibold text-[var(--foreground)]">
                            {selectedNotebook.name}
                          </h3>
                          {selectedNotebook.description && (
                            <span className="text-[12px] text-[var(--muted-foreground)]">
                              — {selectedNotebook.description}
                            </span>
                          )}
                        </div>
                        <span className="text-[11px] tabular-nums text-[var(--muted-foreground)]">
                          {selectedNotebook.records?.length || 0} {t("records")}
                        </span>
                      </div>

                      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                        <div className="divide-y divide-[var(--border)]">
                        {selectedNotebook.records?.map((record) => {
                          const badge = getRecordBadge(record.type);
                          const BadgeIcon = badge.icon;
                          const expanded = expandedRecordId === record.id;
                          const canOpenSession =
                            (record.type === "chat" || record.type === "guided_learning") &&
                            Boolean(record.metadata?.session_id);
                          const sessionLabel =
                            record.type === "chat" ? t("Open chat session") : t("Open guided learning session");

                          return (
                            <div key={record.id} className="group">
                              {/* Collapsed row — always visible */}
                              <button
                                onClick={() => setExpandedRecordId(expanded ? null : record.id)}
                                className="flex w-full items-center gap-3 px-1 py-3.5 text-left transition-colors hover:bg-[var(--muted)]/30"
                              >
                                <span className="shrink-0 text-[var(--muted-foreground)]">
                                  {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                </span>
                                <span className={`inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium ${badge.color}`}>
                                  <BadgeIcon size={11} />
                                  {badge.label}
                                </span>
                                <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-[var(--foreground)]">
                                  {record.title}
                                </span>
                                <span className="shrink-0 text-[11px] tabular-nums text-[var(--muted-foreground)]">
                                  {formatTimestamp(record.created_at)}
                                </span>
                              </button>

                              {/* Expanded detail */}
                              {expanded && (
                                <div className="pb-4 pl-8 pr-1">
                                  {record.summary && (
                                    <p className="mb-3 text-[13px] leading-6 text-[var(--foreground)]/85">
                                      {record.summary}
                                    </p>
                                  )}
                                  {record.type !== "chat" && record.user_query && (
                                    <div className="mb-3 flex items-baseline gap-2 text-[12px]">
                                      <span className="shrink-0 font-medium text-[var(--muted-foreground)]">{t("Query:")}</span>
                                      <span className="text-[var(--foreground)]/70">{record.user_query}</span>
                                    </div>
                                  )}

                                  {canOpenSession && (
                                    <button
                                      onClick={() => openNotebookRecord(record)}
                                      className="mb-3 inline-flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3.5 py-2 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 dark:hover:border-indigo-700 dark:hover:bg-indigo-950/30 dark:hover:text-indigo-300"
                                    >
                                      <ExternalLink size={13} />
                                      {sessionLabel}
                                      <ArrowRight size={13} />
                                    </button>
                                  )}

                                  <div className="max-h-[320px] overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--muted)]/30 p-3">
                                    <MarkdownRenderer
                                      content={record.output || ""}
                                      variant="prose"
                                      className="text-[12px] leading-5 text-[var(--foreground)]"
                                    />
                                  </div>
                                </div>
                              )}
                            </div>
                          );
                        })}

                        {!selectedNotebook.records?.length && (
                          <div className="px-6 py-12 text-center text-[13px] text-[var(--muted-foreground)]">
                            {t("This notebook is empty for now.")}
                          </div>
                        )}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="flex min-h-[320px] items-center justify-center rounded-2xl border border-dashed border-[var(--border)] text-[13px] text-[var(--muted-foreground)]">
                      {t("Select a notebook to inspect its saved records.")}
                    </div>
                  )}
                </div>
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
