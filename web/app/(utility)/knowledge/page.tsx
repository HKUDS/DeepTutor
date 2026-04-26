"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import {
  Suspense,
  type DragEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  ArrowRight,
  Bookmark,
  BookOpen,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  Clock3,
  Database,
  ExternalLink,
  FileUp,
  FileText,
  Files,
  FolderOpen,
  Layers,
  Loader2,
  MessageSquare,
  NotebookPen,
  Pencil,
  Plus,
  Search,
  Star,
  Trash2,
  Upload,
  Wand2,
  X,
} from "lucide-react";
import { apiUrl, wsUrl } from "@/lib/api";
import {
  getKnowledgeUploadPolicy,
  invalidateKnowledgeCaches,
  listKnowledgeBases,
  listRagProviders,
  type KnowledgeUploadPolicy,
} from "@/lib/knowledge-api";
import {
  listCategories,
  listNotebookEntries,
  createCategory,
  deleteCategory,
  renameCategory,
  updateNotebookEntry,
  deleteNotebookEntry,
  removeEntryFromCategory,
  listNotebooks,
  getNotebook,
  createNotebook,
  deleteNotebook,
  type NotebookEntry,
  type NotebookCategory,
} from "@/lib/notebook-api";
import {
  createSkill,
  deleteSkill,
  getSkill,
  listSkills,
  updateSkill,
  type SkillInfo,
} from "@/lib/skills-api";

const MarkdownRenderer = dynamic(
  () => import("@/components/common/MarkdownRenderer"),
  {
    ssr: false,
  },
);
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
  path?: string;
  is_default?: boolean;
  status?: string;
  metadata?: {
    created_at?: string;
    last_updated?: string;
    rag_provider?: string;
    needs_reindex?: boolean;
    embedding_model?: string;
    embedding_dim?: number;
    embedding_mismatch?: boolean;
  };
  progress?: ProgressInfo;
  statistics?: {
    raw_documents?: number;
    images?: number;
    content_lists?: number;
    rag_provider?: string;
    rag_initialized?: boolean;
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

interface DropZoneState {
  active: boolean;
  invalid: boolean;
  draggedCount: number;
}

interface ValidatedSelectionFile {
  id: string;
  file: File;
  extension: string;
  sizeLabel: string;
  valid: boolean;
  error: string | null;
}

interface ValidatedFileSelection {
  items: ValidatedSelectionFile[];
  validFiles: File[];
  invalidFiles: ValidatedSelectionFile[];
  totalBytes: number;
}

type ProcessKind = "create" | "upload";
type DropZoneKind = "create" | "upload";

const EMPTY_PROCESS_STATE: ProcessState = {
  taskId: null,
  label: "",
  logs: [],
  executing: false,
  error: null,
};

const EMPTY_DROP_ZONE_STATE: DropZoneState = {
  active: false,
  invalid: false,
  draggedCount: 0,
};

const DEFAULT_UPLOAD_POLICY: KnowledgeUploadPolicy = {
  extensions: [],
  accept: "",
  max_file_size_bytes: 100 * 1024 * 1024,
  max_pdf_size_bytes: 50 * 1024 * 1024,
};

const formatFileSize = (bytes: number): string => {
  if (bytes >= 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
};

const getFileExtension = (filename: string): string => {
  const index = filename.lastIndexOf(".");
  return index >= 0 ? filename.slice(index).toLowerCase() : "";
};

const mergeSelectedFiles = (existing: File[], incoming: File[]): File[] => {
  const merged = new Map<string, File>();
  [...existing, ...incoming].forEach((file) => {
    merged.set(selectionFileId(file), file);
  });
  return Array.from(merged.values());
};

const parseKnowledgeTimestamp = (value?: string): Date | null => {
  if (!value) return null;
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

const formatKnowledgeTimestamp = (value?: string): string | null => {
  const parsed = parseKnowledgeTimestamp(value);
  return parsed ? parsed.toLocaleString() : value || null;
};

const selectionFileId = (file: File): string =>
  `${file.name}:${file.size}:${file.lastModified}`;

const resolveKbStatus = (kb: KnowledgeBase): string =>
  kb.status ?? kb.statistics?.status ?? "unknown";

const kbNeedsReindex = (kb: KnowledgeBase): boolean =>
  Boolean(kb.statistics?.needs_reindex) ||
  resolveKbStatus(kb) === "needs_reindex";

const kbIsUploadable = (kb: KnowledgeBase): boolean =>
  resolveKbStatus(kb) === "ready" && !kbNeedsReindex(kb);

const kbHasLiveProgress = (kb: KnowledgeBase): boolean => {
  const status = resolveKbStatus(kb);
  const stage = kb.progress?.stage;
  return (
    status !== "ready" &&
    status !== "error" &&
    stage !== "completed" &&
    stage !== "error"
  );
};

const resolveProgressPercent = (progress?: ProgressInfo): number => {
  const directPercent = progress?.progress_percent ?? progress?.percent;
  if (typeof directPercent === "number") return directPercent;

  const current = progress?.current ?? 0;
  const total = progress?.total ?? 0;
  if (!current || !total) return 0;
  return Math.round((current / total) * 100);
};

type TabKey = "knowledge" | "notebooks" | "questions" | "skills";

function KnowledgePageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useTranslation();
  const initialTab = (searchParams.get("tab") as TabKey) || "knowledge";
  const [tab, setTab] = useState<TabKey>(initialTab);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [notebooks, setNotebooks] = useState<NotebookInfo[]>([]);
  const [providers, setProviders] = useState<RAGProvider[]>([]);
  const [uploadPolicy, setUploadPolicy] = useState<KnowledgeUploadPolicy>(
    DEFAULT_UPLOAD_POLICY,
  );
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [uploadingKb, setUploadingKb] = useState<string | null>(null);
  const [progressMap, setProgressMap] = useState<Record<string, ProgressInfo>>(
    {},
  );
  const [newKbName, setNewKbName] = useState("");
  const [newKbFiles, setNewKbFiles] = useState<File[]>([]);
  const [selectedProvider, setSelectedProvider] = useState("llamaindex");
  const [uploadTarget, setUploadTarget] = useState("");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [newNotebookName, setNewNotebookName] = useState("");
  const [newNotebookDescription, setNewNotebookDescription] = useState("");
  const [selectedNotebookId, setSelectedNotebookId] = useState<string | null>(
    null,
  );
  const [selectedNotebook, setSelectedNotebook] =
    useState<NotebookDetail | null>(null);
  const [loadingNotebookDetail, setLoadingNotebookDetail] = useState(false);
  const [expandedRecordId, setExpandedRecordId] = useState<string | null>(null);
  const [createProcess, setCreateProcess] =
    useState<ProcessState>(EMPTY_PROCESS_STATE);
  const [uploadProcess, setUploadProcess] =
    useState<ProcessState>(EMPTY_PROCESS_STATE);
  const socketsRef = useRef<Record<string, WebSocket>>({});
  const logSourcesRef = useRef<Record<ProcessKind, EventSource | null>>({
    create: null,
    upload: null,
  });
  const createFileRef = useRef<HTMLInputElement>(null);
  const uploadFileRef = useRef<HTMLInputElement>(null);
  const createDropDepthRef = useRef(0);
  const uploadDropDepthRef = useRef(0);
  const [createDropZone, setCreateDropZone] = useState<DropZoneState>(
    EMPTY_DROP_ZONE_STATE,
  );
  const [uploadDropZone, setUploadDropZone] = useState<DropZoneState>(
    EMPTY_DROP_ZONE_STATE,
  );

  const validateFileSelection = useCallback(
    (files: File[]): ValidatedFileSelection => {
      const allowedExtensions = new Set(
        uploadPolicy.extensions.map((ext) => ext.toLowerCase()),
      );

      const items = files.map((file) => {
        const extension = getFileExtension(file.name);
        let error: string | null = null;

        if (allowedExtensions.size > 0 && !allowedExtensions.has(extension)) {
          error = t("Unsupported file type");
        } else if (
          extension === ".pdf" &&
          file.size > uploadPolicy.max_pdf_size_bytes
        ) {
          error = t("PDF files must be smaller than {{size}}.", {
            size: formatFileSize(uploadPolicy.max_pdf_size_bytes),
          });
        } else if (file.size > uploadPolicy.max_file_size_bytes) {
          error = t("This file exceeds the maximum size of {{size}}.", {
            size: formatFileSize(uploadPolicy.max_file_size_bytes),
          });
        }

        return {
          id: selectionFileId(file),
          file,
          extension: extension || t("No extension"),
          sizeLabel: formatFileSize(file.size),
          valid: !error,
          error,
        };
      });

      return {
        items,
        validFiles: items.filter((item) => item.valid).map((item) => item.file),
        invalidFiles: items.filter((item) => !item.valid),
        totalBytes: files.reduce((total, file) => total + file.size, 0),
      };
    },
    [t, uploadPolicy],
  );

  const newKbSelection = useMemo(
    () => validateFileSelection(newKbFiles),
    [newKbFiles, validateFileSelection],
  );
  const uploadSelection = useMemo(
    () => validateFileSelection(uploadFiles),
    [uploadFiles, validateFileSelection],
  );

  const removeNewKbFile = (fileId: string) => {
    setNewKbFiles((prev) =>
      prev.filter((file) => selectionFileId(file) !== fileId),
    );
  };

  const removeUploadFile = (fileId: string) => {
    setUploadFiles((prev) =>
      prev.filter((file) => selectionFileId(file) !== fileId),
    );
  };

  const resetDropZone = useCallback((kind: DropZoneKind) => {
    if (kind === "create") {
      createDropDepthRef.current = 0;
      setCreateDropZone(EMPTY_DROP_ZONE_STATE);
      return;
    }

    uploadDropDepthRef.current = 0;
    setUploadDropZone(EMPTY_DROP_ZONE_STATE);
  }, []);

  const previewDroppedFiles = useCallback(
    (files: File[]) => {
      const selection = validateFileSelection(files);
      return {
        count: files.length,
        invalid: selection.invalidFiles.length > 0,
      };
    },
    [validateFileSelection],
  );

  const handleDropZoneEnter = useCallback(
    (kind: DropZoneKind, event: DragEvent<HTMLElement>) => {
      if (!Array.from(event.dataTransfer.types).includes("Files")) return;
      event.preventDefault();
      event.stopPropagation();

      const depthRef =
        kind === "create" ? createDropDepthRef : uploadDropDepthRef;
      const setDropZone =
        kind === "create" ? setCreateDropZone : setUploadDropZone;

      depthRef.current += 1;
      const previewFiles = Array.from(event.dataTransfer.items)
        .filter((item) => item.kind === "file")
        .map((item) => item.getAsFile())
        .filter((file): file is File => Boolean(file));
      const preview = previewDroppedFiles(previewFiles);

      setDropZone({
        active: true,
        invalid: preview.invalid,
        draggedCount: preview.count,
      });
    },
    [previewDroppedFiles],
  );

  const handleDropZoneOver = useCallback(
    (kind: DropZoneKind, event: DragEvent<HTMLElement>) => {
      if (!Array.from(event.dataTransfer.types).includes("Files")) return;
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = "copy";

      const previewFiles = Array.from(event.dataTransfer.items)
        .filter((item) => item.kind === "file")
        .map((item) => item.getAsFile())
        .filter((file): file is File => Boolean(file));
      const preview = previewDroppedFiles(previewFiles);

      if (kind === "create") {
        setCreateDropZone({
          active: true,
          invalid: preview.invalid,
          draggedCount: preview.count,
        });
      } else {
        setUploadDropZone({
          active: true,
          invalid: preview.invalid,
          draggedCount: preview.count,
        });
      }
    },
    [previewDroppedFiles],
  );

  const handleDropZoneLeave = useCallback(
    (kind: DropZoneKind, event: DragEvent<HTMLElement>) => {
      if (!Array.from(event.dataTransfer.types).includes("Files")) return;
      event.preventDefault();
      event.stopPropagation();

      const depthRef =
        kind === "create" ? createDropDepthRef : uploadDropDepthRef;
      depthRef.current = Math.max(0, depthRef.current - 1);
      if (depthRef.current === 0) {
        resetDropZone(kind);
      }
    },
    [resetDropZone],
  );

  const handleDropZoneDrop = useCallback(
    (kind: DropZoneKind, event: DragEvent<HTMLElement>) => {
      if (!Array.from(event.dataTransfer.types).includes("Files")) return;
      event.preventDefault();
      event.stopPropagation();

      const droppedFiles = Array.from(event.dataTransfer.files || []);
      resetDropZone(kind);
      if (!droppedFiles.length) return;

      if (kind === "create") {
        setNewKbFiles((prev) => mergeSelectedFiles(prev, droppedFiles));
      } else {
        setUploadFiles((prev) => mergeSelectedFiles(prev, droppedFiles));
      }
    },
    [resetDropZone],
  );

  // ── Question Notebook state ──
  type QFilterMode = "all" | "bookmarked" | "wrong";
  const [qItems, setQItems] = useState<NotebookEntry[]>([]);
  const [qTotal, setQTotal] = useState(0);
  const [qLoading, setQLoading] = useState(true);
  const [qError, setQError] = useState<string | null>(null);
  const [qRefreshing, setQRefreshing] = useState(false);
  const [qFilter, setQFilter] = useState<QFilterMode>("all");
  const [qActiveCategoryId, setQActiveCategoryId] = useState<number | null>(
    null,
  );
  const [qCategories, setQCategories] = useState<NotebookCategory[]>([]);
  const [qPendingId, setQPendingId] = useState<number | null>(null);
  const [qShowCategoryManager, setQShowCategoryManager] = useState(false);
  const [qNewCatName, setQNewCatName] = useState("");
  const [qRenamingCat, setQRenamingCat] = useState<{
    id: number;
    name: string;
  } | null>(null);

  // ── Skills state ──
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillsError, setSkillsError] = useState<string | null>(null);
  const [skillEditor, setSkillEditor] = useState<{
    mode: "create" | "edit";
    originalName: string | null;
    name: string;
    description: string;
    content: string;
    saving: boolean;
    error: string | null;
  } | null>(null);
  const [skillDeleting, setSkillDeleting] = useState<string | null>(null);

  const loadSkills = useCallback(async () => {
    setSkillsLoading(true);
    setSkillsError(null);
    try {
      const items = await listSkills({ force: true });
      setSkills(items);
    } catch (err) {
      setSkillsError(err instanceof Error ? err.message : String(err));
    } finally {
      setSkillsLoading(false);
    }
  }, []);

  const openCreateSkill = useCallback(() => {
    setSkillEditor({
      mode: "create",
      originalName: null,
      name: "",
      description: "",
      content:
        "# My Skill\n\nDescribe how the assistant should behave when this skill is active.\n",
      saving: false,
      error: null,
    });
  }, []);

  const openEditSkill = useCallback(async (name: string) => {
    setSkillEditor({
      mode: "edit",
      originalName: name,
      name,
      description: "",
      content: "",
      saving: true,
      error: null,
    });
    try {
      const detail = await getSkill(name);
      setSkillEditor({
        mode: "edit",
        originalName: name,
        name: detail.name,
        description: detail.description,
        content: detail.content,
        saving: false,
        error: null,
      });
    } catch (err) {
      setSkillEditor((prev) =>
        prev
          ? {
              ...prev,
              saving: false,
              error: err instanceof Error ? err.message : String(err),
            }
          : prev,
      );
    }
  }, []);

  const handleSaveSkill = useCallback(async () => {
    if (!skillEditor) return;
    const trimmedName = skillEditor.name.trim();
    if (!trimmedName) {
      setSkillEditor({ ...skillEditor, error: "Name is required" });
      return;
    }
    setSkillEditor({ ...skillEditor, saving: true, error: null });
    try {
      if (skillEditor.mode === "create") {
        await createSkill({
          name: trimmedName,
          description: skillEditor.description,
          content: skillEditor.content,
        });
      } else if (skillEditor.originalName) {
        await updateSkill(skillEditor.originalName, {
          description: skillEditor.description,
          content: skillEditor.content,
          rename_to:
            trimmedName !== skillEditor.originalName ? trimmedName : undefined,
        });
      }
      setSkillEditor(null);
      await loadSkills();
    } catch (err) {
      setSkillEditor((prev) =>
        prev
          ? {
              ...prev,
              saving: false,
              error: err instanceof Error ? err.message : String(err),
            }
          : prev,
      );
    }
  }, [skillEditor, loadSkills]);

  const handleDeleteSkill = useCallback(
    async (name: string) => {
      if (!window.confirm(`Delete skill "${name}"?`)) return;
      setSkillDeleting(name);
      try {
        await deleteSkill(name);
        await loadSkills();
      } catch (err) {
        setSkillsError(err instanceof Error ? err.message : String(err));
      } finally {
        setSkillDeleting(null);
      }
    },
    [loadSkills],
  );

  useEffect(() => {
    if (tab === "skills") void loadSkills();
  }, [tab, loadSkills]);

  // ── Question Notebook handlers ──
  const loadQCategories = useCallback(async () => {
    try {
      setQCategories(await listCategories());
    } catch {
      /* ignore */
    }
  }, []);

  const loadQItems = useCallback(
    async (mode: QFilterMode, catId: number | null) => {
      setQRefreshing(true);
      setQError(null);
      try {
        const response = await listNotebookEntries({
          bookmarked: mode === "bookmarked" ? true : undefined,
          is_correct: mode === "wrong" ? false : undefined,
          category_id: catId ?? undefined,
          limit: 200,
        });
        setQItems(response.items);
        setQTotal(response.total);
      } catch (err) {
        setQError(String(err instanceof Error ? err.message : err));
      } finally {
        setQLoading(false);
        setQRefreshing(false);
      }
    },
    [],
  );

  const handleQToggleBookmark = useCallback(
    async (item: NotebookEntry) => {
      const next = !item.bookmarked;
      setQPendingId(item.id);
      try {
        await updateNotebookEntry(item.id, { bookmarked: next });
        setQItems((prev) =>
          qFilter === "bookmarked" && !next
            ? prev.filter((e) => e.id !== item.id)
            : prev.map((e) =>
                e.id === item.id ? { ...e, bookmarked: next } : e,
              ),
        );
        if (qFilter === "bookmarked" && !next)
          setQTotal((p) => Math.max(0, p - 1));
      } catch {
        /* ignore */
      }
      setQPendingId(null);
    },
    [qFilter],
  );

  const handleQDelete = useCallback(
    async (item: NotebookEntry) => {
      if (!window.confirm(t("Delete this entry?"))) return;
      setQPendingId(item.id);
      try {
        await deleteNotebookEntry(item.id);
        setQItems((prev) => prev.filter((e) => e.id !== item.id));
        setQTotal((p) => Math.max(0, p - 1));
      } catch {
        /* ignore */
      }
      setQPendingId(null);
    },
    [t],
  );

  const handleQRemoveFromCategory = useCallback(
    async (item: NotebookEntry) => {
      if (qActiveCategoryId === null) return;
      setQPendingId(item.id);
      try {
        await removeEntryFromCategory(item.id, qActiveCategoryId);
        setQItems((prev) => prev.filter((e) => e.id !== item.id));
        setQTotal((p) => Math.max(0, p - 1));
      } catch {
        /* ignore */
      }
      setQPendingId(null);
    },
    [qActiveCategoryId],
  );

  const handleQCreateCategory = useCallback(async () => {
    if (!qNewCatName.trim()) return;
    try {
      await createCategory(qNewCatName.trim());
      setQNewCatName("");
      await loadQCategories();
    } catch {
      /* ignore */
    }
  }, [loadQCategories, qNewCatName]);

  const handleQRenameCategory = useCallback(async () => {
    if (!qRenamingCat || !qRenamingCat.name.trim()) return;
    try {
      await renameCategory(qRenamingCat.id, qRenamingCat.name.trim());
      setQRenamingCat(null);
      await loadQCategories();
    } catch {
      /* ignore */
    }
  }, [loadQCategories, qRenamingCat]);

  const handleQDeleteCategory = useCallback(
    async (catId: number) => {
      if (!window.confirm(t("Delete this category?"))) return;
      try {
        await deleteCategory(catId);
        if (qActiveCategoryId === catId) setQActiveCategoryId(null);
        await loadQCategories();
      } catch {
        /* ignore */
      }
    },
    [qActiveCategoryId, loadQCategories, t],
  );

  const Q_FILTERS: { mode: QFilterMode; label: string }[] = [
    { mode: "all", label: "All" },
    { mode: "bookmarked", label: "Bookmarked" },
    { mode: "wrong", label: "Wrong Only" },
  ];

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

  const openTaskLogStream = (
    kind: ProcessKind,
    taskId: string,
    label: string,
    kbName?: string,
  ) => {
    closeTaskLogStream(kind);
    const setProcess = getProcessSetter(kind);
    setProcess({
      taskId,
      label,
      logs: [],
      executing: true,
      error: null,
    });

    const source = new EventSource(
      apiUrl(`/api/v1/knowledge/tasks/${taskId}/stream`),
    );
    logSourcesRef.current[kind] = source;

    let settled = false;

    source.addEventListener("log", (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data) as {
          line?: string;
        };
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

    source.addEventListener("progress", (event) => {
      if (!kbName) return;
      try {
        const payload = JSON.parse(
          (event as MessageEvent).data,
        ) as ProgressInfo;
        setProgressMap((prev) => ({ ...prev, [kbName]: payload }));
      } catch {
        // Ignore malformed progress events.
      }
    });

    source.addEventListener("complete", () => {
      settled = true;
      setProcess((prev) => ({ ...prev, taskId, label, executing: false }));
      void loadAll({ force: true, showSpinner: false });
      closeTaskLogStream(kind);
    });

    source.addEventListener("failed", (event) => {
      settled = true;
      let detail = "Task failed";
      try {
        const payload = JSON.parse((event as MessageEvent).data) as {
          detail?: string;
        };
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
      void loadAll({ force: true, showSpinner: false });
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

  const loadAll = async (options?: {
    force?: boolean;
    showSpinner?: boolean;
  }) => {
    const showSpinner = options?.showSpinner ?? true;
    if (showSpinner) setLoading(true);
    setPageError(null);
    try {
      const [kbs, providerData, nbs, nextUploadPolicy] = await Promise.all([
        listKnowledgeBases({ force: options?.force }),
        listRagProviders({ force: options?.force }),
        listNotebooks(),
        getKnowledgeUploadPolicy({ force: options?.force }).catch(
          () => DEFAULT_UPLOAD_POLICY,
        ),
      ]);
      setKnowledgeBases(kbs);
      setUploadPolicy(nextUploadPolicy);
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
      const nextNotebooks: NotebookInfo[] = nbs.map((nb) => ({
        id: String(nb.id),
        name: nb.name,
        description: nb.description,
        record_count: nb.record_count ?? 0,
        color: nb.color,
        icon: nb.icon,
        updated_at: nb.updated_at,
      }));
      setNotebooks(nextNotebooks);
      if (!selectedNotebookId && nextNotebooks.length > 0) {
        void loadNotebookDetail(nextNotebooks[0].id);
      } else if (selectedNotebookId) {
        const stillExists = nextNotebooks.some(
          (item: NotebookInfo) => item.id === selectedNotebookId,
        );
        if (stillExists) {
          void loadNotebookDetail(selectedNotebookId);
        } else {
          setSelectedNotebookId(null);
          setSelectedNotebook(null);
        }
      }

      const preferredUploadTarget =
        kbs.find((kb: KnowledgeBase) => kb.is_default && kbIsUploadable(kb))
          ?.name ??
        kbs.find((kb: KnowledgeBase) => kbIsUploadable(kb))?.name ??
        "";
      setUploadTarget((prev) => {
        if (
          prev &&
          kbs.some(
            (kb: KnowledgeBase) => kb.name === prev && kbIsUploadable(kb),
          )
        ) {
          return prev;
        }
        return preferredUploadTarget;
      });

      const nextProgressEntries: Record<string, ProgressInfo> = {};
      for (const kb of kbs) {
        const status = kb.status ?? kb.statistics?.status;
        const progress = kb.progress ?? kb.statistics?.progress;
        const progressInfo = progress as ProgressInfo | undefined;

        if (status === "error" && progressInfo) {
          nextProgressEntries[kb.name] = progressInfo;
          continue;
        }

        if (kbHasLiveProgress({ ...kb, progress: progressInfo })) {
          nextProgressEntries[kb.name] = progressInfo || {};
          const taskId = (progress as ProgressInfo | undefined)?.task_id;
          subscribeProgress(kb.name, taskId || undefined);
        }
      }
      setProgressMap(nextProgressEntries);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : String(error));
    } finally {
      if (showSpinner) setLoading(false);
    }
  };

  useEffect(() => {
    void loadAll();
    return () => {
      closeAllProgressSockets();
      closeTaskLogStream("create");
      closeTaskLogStream("upload");
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (tab === "questions") {
      void loadQItems(qFilter, qActiveCategoryId);
      void loadQCategories();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, qFilter, qActiveCategoryId]);

  const subscribeProgress = (kbName: string, expectedTaskId?: string) => {
    closeProgressSocket(kbName);

    const query = expectedTaskId
      ? `?task_id=${encodeURIComponent(expectedTaskId)}`
      : "";
    const socket = new WebSocket(
      wsUrl(`/api/v1/knowledge/${kbName}/progress/ws${query}`),
    );
    socketsRef.current[kbName] = socket;

    socket.onmessage = (event) => {
      try {
        const rawData = JSON.parse(event.data) as {
          type?: string;
          data?: ProgressInfo;
          message?: string;
        };
        const progress =
          rawData?.type === "progress" && rawData.data
            ? rawData.data
            : (rawData as ProgressInfo);
        if (!progress || typeof progress !== "object") return;
        if (
          expectedTaskId &&
          progress.task_id &&
          progress.task_id !== expectedTaskId
        )
          return;

        setProgressMap((prev) => ({ ...prev, [kbName]: progress }));
        const stage = progress.stage;
        if (stage === "completed" || stage === "error") {
          closeProgressSocket(kbName);
          void loadAll({ force: true, showSpinner: false });
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
    if (
      !newKbName.trim() ||
      !newKbSelection.validFiles.length ||
      newKbSelection.invalidFiles.length > 0
    ) {
      return;
    }
    const kbName = newKbName.trim();
    const fileCount = newKbSelection.validFiles.length;
    setCreating(true);
    try {
      const form = new FormData();
      form.append("name", kbName);
      form.append("rag_provider", selectedProvider);
      newKbSelection.validFiles.forEach((file) => form.append("files", file));

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
        openTaskLogStream("create", data.task_id, `Create ${kbName}`, kbName);
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
      await loadAll({ force: true, showSpinner: false });
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
    if (
      !uploadTarget ||
      !uploadSelection.validFiles.length ||
      uploadSelection.invalidFiles.length > 0
    ) {
      return;
    }
    const targetKb = uploadTarget;
    const fileCount = uploadSelection.validFiles.length;
    setUploadingKb(uploadTarget);
    try {
      const form = new FormData();
      uploadSelection.validFiles.forEach((file) => form.append("files", file));
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
        openTaskLogStream(
          "upload",
          data.task_id,
          `Upload to ${targetKb}`,
          targetKb,
        );
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
      await loadAll({ force: true, showSpinner: false });
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
    await fetch(apiUrl(`/api/v1/knowledge/default/${kbName}`), {
      method: "PUT",
    });
    invalidateKnowledgeCaches();
    await loadAll({ force: true, showSpinner: false });
  };

  const deleteKnowledgeBase = async (kbName: string) => {
    if (
      !window.confirm(t('Delete knowledge base "{{name}}"?', { name: kbName }))
    )
      return;
    setPageError(null);
    try {
      const res = await fetch(
        apiUrl(`/api/v1/knowledge/${encodeURIComponent(kbName)}`),
        { method: "DELETE" },
      );
      if (!res.ok) {
        let detail = `Delete failed (${res.status})`;
        try {
          const body = await res.json();
          if (body?.detail) detail = String(body.detail);
        } catch {
          // Response body was not JSON; keep generic message.
        }
        throw new Error(detail);
      }
      closeProgressSocket(kbName);
      setProgressMap((prev) => {
        if (!(kbName in prev)) return prev;
        const next = { ...prev };
        delete next[kbName];
        return next;
      });
      invalidateKnowledgeCaches();
      await loadAll({ force: true, showSpinner: false });
    } catch (err) {
      setPageError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleCreateNotebook = async () => {
    if (!newNotebookName.trim()) return;
    await createNotebook({
      name: newNotebookName.trim(),
      description: newNotebookDescription.trim(),
    });
    setNewNotebookName("");
    setNewNotebookDescription("");
    await loadAll();
  };

  const handleDeleteNotebook = async (notebookId: string, name: string) => {
    if (!window.confirm(t('Delete notebook "{{name}}"?', { name }))) return;
    await deleteNotebook(notebookId);
    if (selectedNotebookId === notebookId) {
      setSelectedNotebookId(null);
      setSelectedNotebook(null);
    }
    await loadAll();
  };

  const loadNotebookDetail = async (notebookId: string) => {
    setSelectedNotebookId(notebookId);
    setExpandedRecordId(null);
    setLoadingNotebookDetail(true);
    try {
      const info = notebooks.find((n) => n.id === notebookId);
      const data = await getNotebook(notebookId);
      const records: NotebookRecord[] = (data.records || []).map((rec) => ({
        id: String(rec.id),
        type: String(rec.type),
        title: rec.title,
        summary: rec.summary,
        user_query: rec.user_query,
        output: rec.output,
        metadata: rec.metadata,
        created_at: rec.created_at,
      }));
      setSelectedNotebook({
        id: notebookId,
        name: data.name ?? info?.name ?? "",
        description: data.description ?? info?.description,
        record_count: records.length,
        color: data.color ?? info?.color,
        icon: data.icon ?? info?.icon,
        updated_at: data.updated_at ?? info?.updated_at,
        records,
      });
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
    }
  };

  const formatTimestamp = (value?: number) => {
    if (!value) return t("Unknown time");
    return new Date(value * 1000).toLocaleString();
  };

  const getRecordBadge = (type: string) => {
    switch (type) {
      case "chat":
        return {
          label: t("Chat"),
          color: "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300",
          icon: MessageSquare,
        };
      case "tutorbot":
        return {
          label: t("Tutorbot"),
          color:
            "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300",
          icon: Bot,
        };
      case "research":
        return {
          label: t("Research"),
          color:
            "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
          icon: Search,
        };
      case "co_writer":
        return {
          label: t("Co-Writer"),
          color:
            "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
          icon: Pencil,
        };
      default:
        return {
          label: type,
          color:
            "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
          icon: NotebookPen,
        };
    }
  };

  const combinedKbs = useMemo(
    () =>
      knowledgeBases.map((kb) => ({
        ...kb,
        status: kb.status ?? kb.statistics?.status,
        progress:
          progressMap[kb.name] || kb.progress || kb.statistics?.progress,
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
      return t(
        "This knowledge base is in legacy index format and needs reindex before upload.",
      );
    }
    const status = resolveKbStatus(uploadTargetKb);
    if (status !== "ready") {
      return t(
        "This knowledge base is currently {{status}} and cannot accept uploads yet.",
        { status: status.replaceAll("_", " ") },
      );
    }
    return null;
  }, [uploadTargetKb]);

  const createDisabled =
    creating ||
    !newKbName.trim() ||
    !newKbSelection.validFiles.length ||
    newKbSelection.invalidFiles.length > 0;

  const uploadDisabled =
    !uploadTarget ||
    !uploadSelection.validFiles.length ||
    uploadSelection.invalidFiles.length > 0 ||
    !!uploadingKb ||
    Boolean(uploadBlockedReason);

  const hasActiveKbWork = useMemo(
    () => combinedKbs.some((kb) => kbHasLiveProgress(kb)),
    [combinedKbs],
  );

  useEffect(() => {
    if (!hasActiveKbWork) return;

    const interval = window.setInterval(() => {
      void loadAll({ force: true, showSpinner: false });
    }, 4000);

    return () => window.clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasActiveKbWork]);

  const renderSelectionSummary = (
    selection: ValidatedFileSelection,
    onRemove: (fileId: string) => void,
    onClear: () => void,
  ) => {
    if (!selection.items.length) return null;

    const invalidCount = selection.invalidFiles.length;
    const readyCount = selection.validFiles.length;
    const hasIssues = invalidCount > 0;

    return (
      <div
        className={`rounded-2xl border p-3 ${
          hasIssues
            ? "border-amber-200 bg-amber-50/80 dark:border-amber-900/70 dark:bg-amber-950/20"
            : "border-emerald-200 bg-emerald-50/70 dark:border-emerald-900/60 dark:bg-emerald-950/15"
        }`}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-[13px] font-medium text-[var(--foreground)]">
              {hasIssues ? (
                <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400" />
              ) : (
                <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
              )}
              {hasIssues
                ? t("{{count}} invalid files", { count: invalidCount })
                : t("{{count}} files ready", { count: readyCount })}
            </div>
            <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
              {hasIssues
                ? t("Only supported files can continue.")
                : t("Ready to upload")}{" "}
              · {formatFileSize(selection.totalBytes)}
            </p>
          </div>
          <button
            type="button"
            onClick={onClear}
            className="rounded-md border border-[var(--border)] px-2 py-1 text-[11px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)] hover:text-[var(--foreground)]"
          >
            {t("Clear selection")}
          </button>
        </div>

        <div className="mt-3 space-y-2">
          {selection.items.map((item) => (
            <div
              key={item.id}
              className={`flex items-start gap-3 rounded-xl border px-3 py-2.5 ${
                item.valid
                  ? "border-white/60 bg-white/70 dark:border-white/10 dark:bg-white/5"
                  : "border-amber-200/80 bg-amber-100/60 dark:border-amber-900/60 dark:bg-amber-950/20"
              }`}
            >
              <div
                className={`mt-0.5 rounded-lg p-2 ${
                  item.valid
                    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300"
                    : "bg-amber-100 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300"
                }`}
              >
                <FileText className="h-3.5 w-3.5" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[12px] font-medium text-[var(--foreground)]">
                  {item.file.name}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-[0.12em] text-[var(--muted-foreground)]">
                  <span>{item.extension}</span>
                  <span>{item.sizeLabel}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 normal-case tracking-normal ${
                      item.valid
                        ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300"
                        : "bg-amber-100 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300"
                    }`}
                  >
                    {item.valid ? t("Supported") : t("Needs attention")}
                  </span>
                </div>
                {item.error && (
                  <p className="mt-1.5 text-[11px] leading-relaxed text-amber-700 dark:text-amber-300">
                    {item.error}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => onRemove(item.id)}
                title={t("Remove")}
                className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)] hover:text-[var(--foreground)]"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="h-full overflow-y-auto bg-[var(--background)] [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-5xl px-4 py-5 pb-10 sm:px-6 sm:py-8">
        {/* Header */}
        <div className="mb-5 flex flex-col gap-4 sm:mb-6 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold tracking-tight text-[var(--foreground)]">
              {t("Knowledge")}
            </h1>
            <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
              {t("Manage your knowledge bases and notebooks in one place.")}
            </p>
          </div>

          <div className="grid w-full grid-cols-2 gap-1 rounded-xl border border-[var(--border)] bg-[var(--muted)] p-1 sm:inline-flex sm:w-auto sm:shrink-0 sm:rounded-lg sm:p-0.5">
            {[
              { key: "knowledge", label: t("Knowledge Bases"), icon: Database },
              { key: "notebooks", label: t("Notebooks"), icon: NotebookPen },
              {
                key: "questions",
                label: t("Question Bank"),
                icon: ClipboardList,
              },
              { key: "skills", label: t("Skills"), icon: Wand2 },
            ].map((item) => (
              <button
                type="button"
                key={item.key}
                aria-pressed={tab === item.key}
                onClick={() => setTab(item.key as TabKey)}
                className={`inline-flex min-w-0 items-center justify-center gap-1.5 rounded-lg px-2.5 py-2 text-[12px] font-medium transition-all sm:rounded-md sm:px-3.5 sm:py-1.5 sm:text-[13px] ${
                  tab === item.key
                    ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
                    : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                <item.icon className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{item.label}</span>
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
              <section className="relative overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
                <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[var(--foreground)]/20 to-transparent" />
                <div className="mb-4 flex items-center gap-2">
                  <Plus size={15} className="text-[var(--muted-foreground)]" />
                  <h2 className="text-[14px] font-semibold text-[var(--foreground)]">
                    {t("Create knowledge base")}
                  </h2>
                </div>

                <div className="space-y-4">
                  <input
                    value={newKbName}
                    onChange={(event) => setNewKbName(event.target.value)}
                    placeholder={t("Knowledge base name")}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25"
                  />

                  <select
                    value={selectedProvider}
                    onChange={(event) =>
                      setSelectedProvider(event.target.value)
                    }
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none"
                  >
                    {providers.map((provider) => (
                      <option key={provider.id} value={provider.id}>
                        {provider.name}
                      </option>
                    ))}
                  </select>

                  <button
                    type="button"
                    onClick={() => createFileRef.current?.click()}
                    onDragEnter={(event) =>
                      handleDropZoneEnter("create", event)
                    }
                    onDragLeave={(event) =>
                      handleDropZoneLeave("create", event)
                    }
                    onDragOver={(event) => handleDropZoneOver("create", event)}
                    onDrop={(event) => handleDropZoneDrop("create", event)}
                    className={`group flex w-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-5 py-7 text-center transition-colors ${
                      createDropZone.active
                        ? createDropZone.invalid
                          ? "border-amber-400 bg-amber-50/60 dark:border-amber-700 dark:bg-amber-950/20"
                          : "border-sky-400 bg-sky-50/60 dark:border-sky-700 dark:bg-sky-950/20"
                        : "border-[var(--border)] bg-[var(--background)] hover:border-[var(--foreground)]/25 hover:bg-[var(--muted)]/40"
                    }`}
                  >
                    <Files className="h-5 w-5 text-[var(--muted-foreground)] transition-colors group-hover:text-[var(--foreground)]" />
                    <div className="space-y-1">
                      <div className="text-[13px] font-medium text-[var(--foreground)]">
                        {createDropZone.active
                          ? createDropZone.invalid
                            ? t("Some dragged files are not supported")
                            : t("Drop files to add them")
                          : newKbFiles.length
                            ? newKbSelection.invalidFiles.length > 0
                              ? t("{{count}} invalid files", {
                                  count: newKbSelection.invalidFiles.length,
                                })
                              : t("{{count}} files ready", {
                                  count: newKbSelection.validFiles.length,
                                })
                            : t("Choose files...")}
                      </div>
                      <p className="text-[11px] text-[var(--muted-foreground)]">
                        {createDropZone.active
                          ? createDropZone.draggedCount > 0
                            ? t("{{count}} files detected", {
                                count: createDropZone.draggedCount,
                              })
                            : t("Release to attach the files")
                          : newKbFiles.length
                            ? formatFileSize(newKbSelection.totalBytes)
                            : t("Click to browse supported documents")}
                      </p>
                    </div>
                  </button>
                  <p className="text-[11px] text-[var(--muted-foreground)]">
                    {uploadPolicy.extensions.length} {t("types")} ·{" "}
                    {t("Maximum file size: {{size}}", {
                      size: formatFileSize(uploadPolicy.max_file_size_bytes),
                    })}{" "}
                    ·{" "}
                    {t("PDF limit: {{size}}", {
                      size: formatFileSize(uploadPolicy.max_pdf_size_bytes),
                    })}
                  </p>
                  <input
                    ref={createFileRef}
                    type="file"
                    multiple
                    className="hidden"
                    onChange={(event) => {
                      const picked = Array.from(event.target.files || []);
                      event.target.value = "";
                      setNewKbFiles((prev) => mergeSelectedFiles(prev, picked));
                    }}
                  />

                  {renderSelectionSummary(
                    newKbSelection,
                    removeNewKbFile,
                    () => {
                      setNewKbFiles([]);
                      if (createFileRef.current)
                        createFileRef.current.value = "";
                    },
                  )}

                  <button
                    onClick={createKnowledgeBase}
                    disabled={createDisabled}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-1.5 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {creating ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Plus size={14} />
                    )}
                    {t("Create")}
                  </button>

                  {(createProcess.taskId ||
                    createProcess.logs.length > 0 ||
                    createProcess.executing) && (
                    <div className="space-y-2">
                      {createProcess.label && (
                        <div className="text-[11px] text-[var(--muted-foreground)]">
                          {createProcess.label}
                          {createProcess.taskId
                            ? ` · ${createProcess.taskId}`
                            : ""}
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
              <section className="relative overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
                <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[var(--foreground)]/20 to-transparent" />
                <div className="mb-4 flex items-center gap-2">
                  <Upload
                    size={15}
                    className="text-[var(--muted-foreground)]"
                  />
                  <h2 className="text-[14px] font-semibold text-[var(--foreground)]">
                    {t("Upload documents")}
                  </h2>
                </div>

                <div className="space-y-4">
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
                        <option
                          key={kb.name}
                          value={kb.name}
                          disabled={!uploadable}
                        >
                          {kb.name}
                          {suffix}
                        </option>
                      );
                    })}
                  </select>

                  {!hasUploadableKb && (
                    <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-700 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
                      {t(
                        "No ready knowledge base is available for upload. Create a new KB or reindex legacy KBs first.",
                      )}
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
                    onDragEnter={(event) =>
                      handleDropZoneEnter("upload", event)
                    }
                    onDragLeave={(event) =>
                      handleDropZoneLeave("upload", event)
                    }
                    onDragOver={(event) => handleDropZoneOver("upload", event)}
                    onDrop={(event) => handleDropZoneDrop("upload", event)}
                    className={`group flex w-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-5 py-7 text-center transition-colors ${
                      uploadDropZone.active
                        ? uploadDropZone.invalid
                          ? "border-amber-400 bg-amber-50/60 dark:border-amber-700 dark:bg-amber-950/20"
                          : "border-sky-400 bg-sky-50/60 dark:border-sky-700 dark:bg-sky-950/20"
                        : "border-[var(--border)] bg-[var(--background)] hover:border-[var(--foreground)]/25 hover:bg-[var(--muted)]/40"
                    }`}
                  >
                    <Files className="h-5 w-5 text-[var(--muted-foreground)] transition-colors group-hover:text-[var(--foreground)]" />
                    <div className="space-y-1">
                      <div className="text-[13px] font-medium text-[var(--foreground)]">
                        {uploadDropZone.active
                          ? uploadDropZone.invalid
                            ? t("Some dragged files are not supported")
                            : t("Drop files to add them")
                          : uploadFiles.length
                            ? uploadSelection.invalidFiles.length > 0
                              ? t("{{count}} invalid files", {
                                  count: uploadSelection.invalidFiles.length,
                                })
                              : t("{{count}} files ready", {
                                  count: uploadSelection.validFiles.length,
                                })
                            : t("Choose files...")}
                      </div>
                      <p className="text-[11px] text-[var(--muted-foreground)]">
                        {uploadDropZone.active
                          ? uploadDropZone.draggedCount > 0
                            ? t("{{count}} files detected", {
                                count: uploadDropZone.draggedCount,
                              })
                            : t("Release to attach the files")
                          : uploadFiles.length
                            ? formatFileSize(uploadSelection.totalBytes)
                            : t("Click to browse supported documents")}
                      </p>
                    </div>
                  </button>
                  <p className="text-[11px] text-[var(--muted-foreground)]">
                    {uploadPolicy.extensions.length} {t("types")} ·{" "}
                    {t("Maximum file size: {{size}}", {
                      size: formatFileSize(uploadPolicy.max_file_size_bytes),
                    })}{" "}
                    ·{" "}
                    {t("PDF limit: {{size}}", {
                      size: formatFileSize(uploadPolicy.max_pdf_size_bytes),
                    })}
                  </p>
                  <input
                    ref={uploadFileRef}
                    type="file"
                    multiple
                    className="hidden"
                    onChange={(event) => {
                      const picked = Array.from(event.target.files || []);
                      event.target.value = "";
                      setUploadFiles((prev) =>
                        mergeSelectedFiles(prev, picked),
                      );
                    }}
                  />

                  {renderSelectionSummary(
                    uploadSelection,
                    removeUploadFile,
                    () => {
                      setUploadFiles([]);
                      if (uploadFileRef.current)
                        uploadFileRef.current.value = "";
                    },
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

                  {(uploadProcess.taskId ||
                    uploadProcess.logs.length > 0 ||
                    uploadProcess.executing) && (
                    <div className="space-y-2">
                      {uploadProcess.label && (
                        <div className="text-[11px] text-[var(--muted-foreground)]">
                          {uploadProcess.label}
                          {uploadProcess.taskId
                            ? ` · ${uploadProcess.taskId}`
                            : ""}
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
                <BookOpen
                  size={15}
                  className="text-[var(--muted-foreground)]"
                />
                <h2 className="text-[14px] font-semibold text-[var(--foreground)]">
                  {t("Knowledge bases")}
                </h2>
              </div>

              <div className="space-y-3">
                {combinedKbs.map((kb) => {
                  const progress = kb.progress;
                  const status = resolveKbStatus(kb);
                  const needsReindex = kbNeedsReindex(kb);
                  const kbMetadata = kb.metadata || {};
                  const isReady = status === "ready" && !needsReindex;
                  const isError = status === "error";
                  const isLive = kbHasLiveProgress(kb);
                  const percent = resolveProgressPercent(progress);
                  const documentsCount = kb.statistics?.raw_documents ?? 0;
                  const updatedLabel =
                    formatKnowledgeTimestamp(kbMetadata.last_updated) ||
                    t("Unknown time");
                  const embeddingLabel = kbMetadata.embedding_model
                    ? typeof kbMetadata.embedding_dim === "number"
                      ? `${kbMetadata.embedding_model} · ${kbMetadata.embedding_dim}d`
                      : kbMetadata.embedding_model
                    : t("Default embedding");
                  const activityMessage =
                    progress?.message ||
                    (needsReindex
                      ? t(
                          "This knowledge base needs reindex before it can accept new files.",
                        )
                      : isError
                        ? t("The last processing run failed.")
                        : isLive
                          ? t("Waiting for live progress...")
                          : null);
                  const statusLabel = needsReindex
                    ? t("Needs reindex")
                    : isError
                      ? t("Error")
                      : isLive
                        ? t("Processing live")
                        : isReady
                          ? t("Ready")
                          : status.replaceAll("_", " ");

                  return (
                    <div
                      key={kb.name}
                      className="group rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 transition-colors hover:border-[var(--foreground)]/15"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="flex min-w-0 flex-1 items-center gap-3">
                          <div className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--muted)]/60 text-[var(--muted-foreground)] sm:flex">
                            <Layers className="h-4 w-4" />
                          </div>

                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <h3 className="text-[14px] font-semibold text-[var(--foreground)]">
                                {kb.name}
                              </h3>
                              {kb.is_default && (
                                <span className="inline-flex items-center gap-1 rounded-full bg-[var(--muted)] px-2 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                                  <Star size={10} /> {t("Default")}
                                </span>
                              )}
                              <span
                                className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                                  needsReindex
                                    ? "bg-amber-100 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300"
                                    : isError
                                      ? "bg-red-100 text-red-700 dark:bg-red-950/30 dark:text-red-300"
                                      : isLive
                                        ? "bg-sky-100 text-sky-700 dark:bg-sky-950/30 dark:text-sky-300"
                                        : "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300"
                                }`}
                              >
                                {isLive ? (
                                  <Clock3 className="h-3 w-3" />
                                ) : isReady ? (
                                  <CheckCircle2 className="h-3 w-3" />
                                ) : (
                                  <AlertTriangle className="h-3 w-3" />
                                )}
                                {statusLabel}
                              </span>
                            </div>
                            <div className="mt-1 truncate text-[11px] text-[var(--muted-foreground)]">
                              {kb.statistics?.rag_provider || "llamaindex"}
                              {" · "}
                              {embeddingLabel}
                              {!!progress?.current &&
                                !!progress?.total &&
                                isLive && (
                                  <>
                                    {" · "}
                                    {t("Progress")}: {progress.current}/
                                    {progress.total}
                                  </>
                                )}
                            </div>
                          </div>
                        </div>

                        <div className="flex items-center gap-1.5">
                          {!kb.is_default && (
                            <button
                              onClick={() => setDefaultKnowledgeBase(kb.name)}
                              className="rounded-md px-2.5 py-1 text-[12px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                            >
                              {t("Set default")}
                            </button>
                          )}
                          <button
                            onClick={() => deleteKnowledgeBase(kb.name)}
                            className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/30 dark:hover:text-red-400"
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </div>

                      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-[var(--muted-foreground)]">
                        <span>
                          <span className="font-medium text-[var(--foreground)]">
                            {documentsCount}
                          </span>{" "}
                          {documentsCount === 1
                            ? t("document")
                            : t("documents")}
                        </span>
                        <span
                          className="h-3 w-px bg-[var(--border)]"
                          aria-hidden
                        />
                        <span>
                          {kb.statistics?.rag_initialized
                            ? t("Vector index ready")
                            : t("Index not ready")}
                        </span>
                        <span
                          className="h-3 w-px bg-[var(--border)]"
                          aria-hidden
                        />
                        <span>
                          {t("Updated")} {updatedLabel}
                        </span>
                      </div>
                      {kb.path && (
                        <div className="mt-1 truncate font-mono text-[10.5px] text-[var(--muted-foreground)]/80">
                          {kb.path}
                        </div>
                      )}

                      {(isLive || isError || needsReindex) &&
                        activityMessage && (
                          <div
                            className={`mt-4 rounded-2xl border p-4 ${
                              isError
                                ? "border-red-200 bg-red-50/70 dark:border-red-900/60 dark:bg-red-950/20"
                                : needsReindex
                                  ? "border-amber-200 bg-amber-50/80 dark:border-amber-900/60 dark:bg-amber-950/20"
                                  : "border-sky-200 bg-sky-50/70 dark:border-sky-900/60 dark:bg-sky-950/20"
                            }`}
                          >
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-[var(--muted-foreground)]">
                                {isError
                                  ? t("Latest activity")
                                  : isLive
                                    ? t("Live pipeline")
                                    : t("Action required")}
                              </div>
                              {isLive && percent > 0 && (
                                <div className="text-[12px] font-medium text-[var(--foreground)]">
                                  {percent}%
                                </div>
                              )}
                            </div>
                            <div className="mt-2 text-[13px] text-[var(--foreground)]">
                              {activityMessage}
                            </div>
                            {isLive && (
                              <div className="mt-3">
                                <div className="h-1.5 overflow-hidden rounded-full bg-[var(--border)]/70">
                                  <div
                                    className="h-full rounded-full bg-[var(--primary)] transition-all duration-300"
                                    style={{ width: `${percent}%` }}
                                  />
                                </div>
                              </div>
                            )}
                            {isLive &&
                              progress?.current !== undefined &&
                              progress?.total !== undefined &&
                              progress.total > 0 && (
                                <div className="mt-2 text-[11px] text-[var(--muted-foreground)]">
                                  {t("Step {{current}} of {{total}}", {
                                    current: progress.current,
                                    total: progress.total,
                                  })}
                                </div>
                              )}
                          </div>
                        )}
                    </div>
                  );
                })}

                {!combinedKbs.length && (
                  <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--background)]/40 px-6 py-12 text-center">
                    <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--muted)] text-[var(--muted-foreground)]">
                      <Database className="h-5 w-5" />
                    </div>
                    <div className="text-[14px] font-medium text-[var(--foreground)]">
                      {t("No knowledge bases yet. Create one to get started.")}
                    </div>
                    <p className="mx-auto mt-2 max-w-md text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                      {t(
                        "Once a knowledge base is ready, it stays clean here as a reusable resource instead of showing stale completion banners.",
                      )}
                    </p>
                  </div>
                )}
              </div>
            </section>
          </div>
        ) : tab === "notebooks" ? (
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
                  onChange={(event) =>
                    setNewNotebookDescription(event.target.value)
                  }
                  placeholder={t("Description")}
                  className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25"
                />
                <button
                  onClick={() => void handleCreateNotebook()}
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
                <NotebookPen
                  size={15}
                  className="text-[var(--muted-foreground)]"
                />
                <h2 className="text-[14px] font-semibold text-[var(--foreground)]">
                  {t("Notebooks")}
                </h2>
              </div>

              <div className="grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)]">
                <div className="xl:sticky xl:top-8 xl:max-h-[calc(100vh-12rem)] space-y-3 overflow-y-auto pr-1">
                  {notebooks.map((notebook) => {
                    const active = selectedNotebookId === notebook.id;
                    return (
                      <div
                        key={notebook.id}
                        className={`group relative w-full rounded-xl border p-4 text-left transition-all ${
                          active
                            ? "border-[var(--primary)]/40 bg-[var(--primary)]/8 shadow-sm"
                            : "border-[var(--border)] bg-[var(--background)] hover:border-[var(--foreground)]/15 hover:bg-[var(--muted)]/30"
                        }`}
                      >
                        <button
                          type="button"
                          onClick={() => void loadNotebookDetail(notebook.id)}
                          className="block w-full text-left"
                        >
                          <div className="flex items-start gap-3">
                            <div
                              className="mt-1 h-3 w-3 rounded-full"
                              style={{
                                backgroundColor:
                                  notebook.color || "var(--primary)",
                              }}
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
                                <span>
                                  {notebook.record_count ?? 0} {t("records")}
                                </span>
                                <span>
                                  {notebook.updated_at
                                    ? formatTimestamp(notebook.updated_at)
                                    : ""}
                                </span>
                              </div>
                            </div>
                          </div>
                        </button>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            void handleDeleteNotebook(
                              notebook.id,
                              notebook.name,
                            );
                          }}
                          title={t("Delete")}
                          className="absolute right-2 top-2 rounded-md p-1.5 text-[var(--muted-foreground)] opacity-0 transition-opacity hover:bg-[var(--destructive)]/10 hover:text-[var(--destructive)] group-hover:opacity-100"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
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
                            style={{
                              backgroundColor:
                                selectedNotebook.color || "var(--primary)",
                            }}
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
                              record.type === "chat" &&
                              Boolean(record.metadata?.session_id);
                            const sessionLabel = t("Open chat session");

                            return (
                              <div key={record.id} className="group">
                                {/* Collapsed row — always visible */}
                                <button
                                  onClick={() =>
                                    setExpandedRecordId(
                                      expanded ? null : record.id,
                                    )
                                  }
                                  className="flex w-full items-center gap-3 px-1 py-3.5 text-left transition-colors hover:bg-[var(--muted)]/30"
                                >
                                  <span className="shrink-0 text-[var(--muted-foreground)]">
                                    {expanded ? (
                                      <ChevronDown size={14} />
                                    ) : (
                                      <ChevronRight size={14} />
                                    )}
                                  </span>
                                  <span
                                    className={`inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium ${badge.color}`}
                                  >
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
                                    {record.type !== "chat" &&
                                      record.user_query && (
                                        <div className="mb-3 flex items-baseline gap-2 text-[12px]">
                                          <span className="shrink-0 font-medium text-[var(--muted-foreground)]">
                                            {t("Query:")}
                                          </span>
                                          <span className="text-[var(--foreground)]/70">
                                            {record.user_query}
                                          </span>
                                        </div>
                                      )}

                                    {canOpenSession && (
                                      <button
                                        onClick={() =>
                                          openNotebookRecord(record)
                                        }
                                        className="mb-3 inline-flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3.5 py-2 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--primary)]/40 hover:bg-[var(--primary)]/8 hover:text-[var(--primary)]"
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
        ) : tab === "questions" ? (
          /* ── Questions tab content ── */
          <div className="space-y-0">
            {/* Category manager */}
            <div
              className={`mb-4 overflow-hidden rounded-xl border transition-colors ${qShowCategoryManager ? "border-[var(--border)] bg-[var(--card)]" : "border-[var(--border)]/50 bg-transparent"}`}
            >
              <button
                onClick={() => setQShowCategoryManager((v) => !v)}
                className="flex w-full items-center justify-between px-4 py-2.5 text-[13px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/40"
              >
                <span className="flex items-center gap-2">
                  <FolderOpen className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />
                  {t("Manage Categories")}
                  {qCategories.length > 0 && (
                    <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
                      {qCategories.length}
                    </span>
                  )}
                </span>
                <ChevronDown
                  className={`h-3.5 w-3.5 text-[var(--muted-foreground)] transition-transform duration-200 ${qShowCategoryManager ? "rotate-180" : ""}`}
                />
              </button>

              {qShowCategoryManager && (
                <div className="border-t border-[var(--border)] px-4 pb-4 pt-3">
                  <div className="space-y-1.5">
                    {qCategories.map((cat) => (
                      <div
                        key={cat.id}
                        className="flex items-center justify-between gap-2 rounded-lg bg-[var(--muted)]/30 px-3 py-2"
                      >
                        {qRenamingCat?.id === cat.id ? (
                          <input
                            autoFocus
                            value={qRenamingCat.name}
                            onChange={(e) =>
                              setQRenamingCat({
                                ...qRenamingCat,
                                name: e.target.value,
                              })
                            }
                            onKeyDown={(e) => {
                              if (e.key === "Enter")
                                void handleQRenameCategory();
                              if (e.key === "Escape") setQRenamingCat(null);
                            }}
                            onBlur={() => void handleQRenameCategory()}
                            className="flex-1 rounded border border-[var(--border)] bg-[var(--background)] px-2 py-0.5 text-[12px] text-[var(--foreground)] outline-none"
                          />
                        ) : (
                          <span className="text-[12px] text-[var(--foreground)]">
                            {cat.name}
                            <span className="ml-1.5 text-[var(--muted-foreground)]">
                              ({cat.entry_count})
                            </span>
                          </span>
                        )}
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() =>
                              setQRenamingCat({ id: cat.id, name: cat.name })
                            }
                            className="rounded p-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                          >
                            <Pencil size={12} />
                          </button>
                          <button
                            onClick={() => void handleQDeleteCategory(cat.id)}
                            className="rounded p-1 text-[var(--muted-foreground)] transition-colors hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30"
                          >
                            <Trash2 size={12} />
                          </button>
                        </div>
                      </div>
                    ))}
                    {!qCategories.length && (
                      <p className="py-2 text-center text-[12px] text-[var(--muted-foreground)]">
                        {t("No categories yet.")}
                      </p>
                    )}
                  </div>
                  <div className="mt-3 flex items-center gap-1.5">
                    <input
                      value={qNewCatName}
                      onChange={(e) => setQNewCatName(e.target.value)}
                      onKeyDown={(e) =>
                        e.key === "Enter" && void handleQCreateCategory()
                      }
                      placeholder={t("New category name...")}
                      className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[12px] text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
                    />
                    <button
                      onClick={() => void handleQCreateCategory()}
                      disabled={!qNewCatName.trim()}
                      className="rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-white disabled:opacity-30"
                    >
                      <Plus size={13} />
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Filter bar */}
            <div className="mb-5 flex items-center justify-between border-b border-[var(--border)]/50 pb-3">
              <div className="flex items-center gap-1 overflow-x-auto">
                {Q_FILTERS.map(({ mode, label }) => {
                  const active = qFilter === mode && qActiveCategoryId === null;
                  return (
                    <button
                      key={mode}
                      onClick={() => {
                        setQFilter(mode);
                        setQActiveCategoryId(null);
                      }}
                      className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] transition-colors ${
                        active
                          ? "bg-[var(--muted)] font-medium text-[var(--foreground)]"
                          : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                      }`}
                    >
                      {t(label)}
                    </button>
                  );
                })}
                {qCategories.length > 0 && (
                  <span className="mx-1 text-[var(--border)]">|</span>
                )}
                {qCategories.map((cat) => {
                  const active = qActiveCategoryId === cat.id;
                  return (
                    <button
                      key={cat.id}
                      onClick={() => {
                        setQActiveCategoryId(cat.id);
                        setQFilter("all");
                      }}
                      className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] transition-colors ${
                        active
                          ? "bg-[var(--muted)] font-medium text-[var(--foreground)]"
                          : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                      }`}
                    >
                      <FolderOpen size={12} />
                      {cat.name}
                    </button>
                  );
                })}
              </div>
              <span className="shrink-0 text-[12px] text-[var(--muted-foreground)]">
                {t("Total")}: {qTotal}
              </span>
            </div>

            {/* Content */}
            {qLoading ? (
              <div className="flex min-h-[420px] items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
              </div>
            ) : qError ? (
              <div className="flex min-h-[320px] flex-col items-center justify-center rounded-xl border border-dashed border-red-300 text-center dark:border-red-900">
                <div className="mb-3 rounded-xl bg-red-50 p-2.5 text-red-500 dark:bg-red-950/30">
                  <AlertTriangle size={18} />
                </div>
                <p className="text-[14px] font-medium text-[var(--foreground)]">
                  {t("Failed to load entries")}
                </p>
                <p className="mt-1.5 max-w-xs text-[13px] text-[var(--muted-foreground)]">
                  {qError}
                </p>
                <button
                  onClick={() => void loadQItems(qFilter, qActiveCategoryId)}
                  className="mt-3 rounded-lg bg-[var(--primary)] px-4 py-1.5 text-[12px] font-medium text-white"
                >
                  {t("Retry")}
                </button>
              </div>
            ) : qItems.length === 0 ? (
              <div className="flex min-h-[320px] flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border)] text-center">
                <div className="mb-3 rounded-xl bg-[var(--muted)] p-2.5 text-[var(--muted-foreground)]">
                  <ClipboardList size={18} />
                </div>
                <p className="text-[14px] font-medium text-[var(--foreground)]">
                  {t("No entries yet")}
                </p>
                <p className="mt-1.5 max-w-xs text-[13px] text-[var(--muted-foreground)]">
                  {t("Questions from your quizzes will appear here.")}
                </p>
              </div>
            ) : (
              <ul className="flex flex-col gap-3">
                {qItems.map((item) => {
                  const disabled = qPendingId === item.id;
                  return (
                    <li
                      key={item.id}
                      className={`rounded-xl border border-[var(--border)] px-5 py-4 transition-opacity ${
                        disabled ? "opacity-60" : ""
                      }`}
                    >
                      {/* Question header */}
                      <div className="mb-3 flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                            {item.difficulty && (
                              <span
                                className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase ${
                                  item.difficulty === "hard"
                                    ? "bg-red-50 text-red-600 dark:bg-red-950/30 dark:text-red-400"
                                    : item.difficulty === "medium"
                                      ? "bg-amber-50 text-amber-600 dark:bg-amber-950/30 dark:text-amber-400"
                                      : "bg-green-50 text-green-600 dark:bg-green-950/30 dark:text-green-400"
                                }`}
                              >
                                {item.difficulty}
                              </span>
                            )}
                            {item.question_type && (
                              <span className="rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                                {item.question_type}
                              </span>
                            )}
                            <span
                              className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${
                                item.is_correct
                                  ? "bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-400"
                                  : "bg-red-100 text-red-700 dark:bg-red-950/30 dark:text-red-400"
                              }`}
                            >
                              {item.is_correct ? t("Correct") : t("Incorrect")}
                            </span>
                          </div>
                          <div className="text-[14px] font-medium text-[var(--foreground)]">
                            <MarkdownRenderer
                              content={item.question}
                              variant="prose"
                              className="text-[14px] leading-relaxed"
                            />
                          </div>
                        </div>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => void handleQToggleBookmark(item)}
                            disabled={disabled}
                            title={
                              item.bookmarked
                                ? t("Remove Bookmark")
                                : t("Bookmark")
                            }
                            className={`rounded-lg p-1.5 transition-colors disabled:opacity-40 ${
                              item.bookmarked
                                ? "text-[var(--primary)]"
                                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                            }`}
                          >
                            <Bookmark
                              className="h-4 w-4"
                              fill={item.bookmarked ? "currentColor" : "none"}
                            />
                          </button>
                          {qActiveCategoryId !== null && (
                            <button
                              onClick={() =>
                                void handleQRemoveFromCategory(item)
                              }
                              disabled={disabled}
                              title={t("Remove from category")}
                              className="rounded-lg p-1.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:opacity-40"
                            >
                              <X className="h-4 w-4" />
                            </button>
                          )}
                          <button
                            onClick={() => void handleQDelete(item)}
                            disabled={disabled}
                            title={t("Delete")}
                            className="rounded-lg p-1.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:opacity-40"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </div>

                      {/* Options for choice questions */}
                      {item.options && Object.keys(item.options).length > 0 && (
                        <div className="mb-3 space-y-1.5">
                          {Object.entries(item.options).map(([key, text]) => {
                            const isUserAnswer =
                              item.user_answer?.toUpperCase() ===
                              key.toUpperCase();
                            const isCorrectAnswer =
                              item.correct_answer?.toUpperCase() ===
                              key.toUpperCase();
                            const isWrongPick =
                              isUserAnswer && !item.is_correct;
                            return (
                              <div
                                key={key}
                                className={`flex items-start gap-2.5 rounded-lg border px-3 py-2 text-[13px] transition-colors ${
                                  isCorrectAnswer
                                    ? "border-green-200 bg-green-50/60 dark:border-green-900 dark:bg-green-950/20"
                                    : isWrongPick
                                      ? "border-red-200 bg-red-50/60 dark:border-red-900 dark:bg-red-950/20"
                                      : "border-transparent bg-[var(--muted)]/30"
                                }`}
                              >
                                <span
                                  className={`mt-px shrink-0 font-semibold ${
                                    isCorrectAnswer
                                      ? "text-green-600 dark:text-green-400"
                                      : isWrongPick
                                        ? "text-red-600 dark:text-red-400"
                                        : "text-[var(--muted-foreground)]"
                                  }`}
                                >
                                  {key}.
                                </span>
                                <span
                                  className={`flex-1 ${
                                    isCorrectAnswer || isWrongPick
                                      ? "text-[var(--foreground)]"
                                      : "text-[var(--muted-foreground)]"
                                  }`}
                                >
                                  {text}
                                </span>
                                {isCorrectAnswer && (
                                  <span className="mt-px shrink-0 text-[10px] font-medium text-green-600 dark:text-green-400">
                                    ✓ {t("Correct")}
                                  </span>
                                )}
                                {isWrongPick && (
                                  <span className="mt-px shrink-0 text-[10px] font-medium text-red-600 dark:text-red-400">
                                    ✗ {t("Your pick")}
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}

                      {/* Answers for coding / written / fill-in questions */}
                      {(!item.options ||
                        Object.keys(item.options).length === 0) && (
                        <div className="mb-3 space-y-2 text-[13px]">
                          <div
                            className={`rounded-lg border px-3 py-2.5 ${
                              !item.is_correct
                                ? "border-red-200/60 bg-red-50/40 dark:border-red-900/40 dark:bg-red-950/15"
                                : "border-green-200/60 bg-green-50/40 dark:border-green-900/40 dark:bg-green-950/15"
                            }`}
                          >
                            <div
                              className={`mb-1 text-[11px] font-medium uppercase tracking-wide ${
                                !item.is_correct
                                  ? "text-red-500 dark:text-red-400"
                                  : "text-green-600 dark:text-green-400"
                              }`}
                            >
                              {t("Your Answer")} {item.is_correct ? "✓" : "✗"}
                            </div>
                            <div className="text-[var(--foreground)]">
                              {item.user_answer ? (
                                item.question_type === "coding" ? (
                                  <MarkdownRenderer
                                    content={`\`\`\`python\n${item.user_answer}\n\`\`\``}
                                    variant="prose"
                                    className="text-[13px]"
                                  />
                                ) : (
                                  <MarkdownRenderer
                                    content={item.user_answer}
                                    variant="prose"
                                    className="text-[13px] leading-relaxed"
                                  />
                                )
                              ) : (
                                <span className="text-[var(--muted-foreground)]">
                                  —
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="rounded-lg border border-green-200/60 bg-green-50/40 px-3 py-2.5 dark:border-green-900/40 dark:bg-green-950/15">
                            <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-green-600 dark:text-green-400">
                              {t("Reference Answer")}
                            </div>
                            <div className="text-[var(--foreground)]">
                              {item.correct_answer ? (
                                item.question_type === "coding" ? (
                                  <MarkdownRenderer
                                    content={
                                      item.correct_answer
                                        .trimStart()
                                        .startsWith("```")
                                        ? item.correct_answer
                                        : `\`\`\`python\n${item.correct_answer}\n\`\`\``
                                    }
                                    variant="prose"
                                    className="text-[13px]"
                                  />
                                ) : (
                                  <MarkdownRenderer
                                    content={item.correct_answer}
                                    variant="prose"
                                    className="text-[13px] leading-relaxed"
                                  />
                                )
                              ) : (
                                <span className="text-[var(--muted-foreground)]">
                                  —
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Explanation */}
                      {item.explanation && (
                        <div className="mb-3 rounded-lg border border-blue-200/60 bg-blue-50/30 px-3 py-2.5 dark:border-blue-900/40 dark:bg-blue-950/15">
                          <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-blue-600 dark:text-blue-400">
                            {t("Explanation")}
                          </div>
                          <div className="text-[13px] leading-relaxed text-[var(--foreground)]">
                            <MarkdownRenderer
                              content={item.explanation}
                              variant="prose"
                              className="text-[13px] leading-relaxed"
                            />
                          </div>
                        </div>
                      )}

                      {/* Footer */}
                      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px]">
                        <div className="flex items-center gap-2">
                          <Link
                            href={`/?session=${encodeURIComponent(item.session_id)}`}
                            className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--muted)]/40 px-2.5 py-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                          >
                            <ExternalLink size={10} />
                            {item.session_title || t("Original Session")}
                          </Link>
                          {item.followup_session_id && (
                            <Link
                              href={`/?session=${encodeURIComponent(item.followup_session_id)}`}
                              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--muted)]/40 px-2.5 py-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                            >
                              <MessageSquare size={10} />
                              {t("Follow-up")}
                            </Link>
                          )}
                        </div>
                        <span className="text-[var(--muted-foreground)]">
                          {new Date(item.created_at * 1000).toLocaleString()}
                        </span>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        ) : (
          /* ── Skills tab content ── */
          <div className="space-y-5">
            <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
              <div className="mb-4 flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Wand2 size={15} className="text-[var(--muted-foreground)]" />
                  <h2 className="text-[14px] font-semibold text-[var(--foreground)]">
                    {t("Skills")}
                  </h2>
                  <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
                    {skills.length}
                  </span>
                </div>
                <button
                  onClick={openCreateSkill}
                  className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--muted)]/40 px-3 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
                >
                  <Plus size={13} /> {t("New skill")}
                </button>
              </div>
              <p className="mb-4 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                {t(
                  "Skills are short markdown playbooks that shape the assistant's behavior in chat. Pick one from the composer or use Auto.",
                )}
              </p>

              {skillsError && (
                <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                  {skillsError}
                </div>
              )}

              {skillsLoading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
                </div>
              ) : skills.length === 0 ? (
                <div className="rounded-lg border border-dashed border-[var(--border)] py-12 text-center text-[13px] text-[var(--muted-foreground)]">
                  {t("No skills yet. Create your first one to customize chat.")}
                </div>
              ) : (
                <ul className="divide-y divide-[var(--border)]/50 rounded-lg border border-[var(--border)]">
                  {skills.map((skill) => (
                    <li
                      key={skill.name}
                      className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-[var(--muted)]/30"
                    >
                      <Wand2
                        size={14}
                        className="shrink-0 text-[var(--muted-foreground)]"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[13px] font-medium text-[var(--foreground)]">
                          {skill.name}
                        </div>
                        {skill.description && (
                          <div className="mt-0.5 truncate text-[12px] text-[var(--muted-foreground)]">
                            {skill.description}
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => void openEditSkill(skill.name)}
                          className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                          title={t("Edit")}
                        >
                          <Pencil size={13} />
                        </button>
                        <button
                          onClick={() => void handleDeleteSkill(skill.name)}
                          disabled={skillDeleting === skill.name}
                          className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50 dark:hover:bg-red-950/30"
                          title={t("Delete")}
                        >
                          {skillDeleting === skill.name ? (
                            <Loader2 size={13} className="animate-spin" />
                          ) : (
                            <Trash2 size={13} />
                          )}
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {skillEditor && (
              <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
                <div className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-2xl">
                  <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3">
                    <div className="flex items-center gap-2">
                      <Wand2
                        size={14}
                        className="text-[var(--muted-foreground)]"
                      />
                      <h3 className="text-[14px] font-semibold text-[var(--foreground)]">
                        {skillEditor.mode === "create"
                          ? t("New skill")
                          : t("Edit skill")}
                      </h3>
                    </div>
                    <button
                      onClick={() => setSkillEditor(null)}
                      className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                    >
                      <X size={14} />
                    </button>
                  </div>

                  <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
                    <div>
                      <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                        {t("Name")}
                      </label>
                      <input
                        value={skillEditor.name}
                        onChange={(e) =>
                          setSkillEditor({
                            ...skillEditor,
                            name: e.target.value,
                          })
                        }
                        placeholder={t("e.g. teacher")}
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] outline-none transition-colors focus:border-[var(--foreground)]/25"
                      />
                      <p className="mt-1 text-[11px] text-[var(--muted-foreground)]/70">
                        {t("Lowercase letters, digits, and hyphens only.")}
                      </p>
                    </div>

                    <div>
                      <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                        {t("Description")}
                      </label>
                      <input
                        value={skillEditor.description}
                        onChange={(e) =>
                          setSkillEditor({
                            ...skillEditor,
                            description: e.target.value,
                          })
                        }
                        placeholder={t("Short summary used by Auto mode")}
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] outline-none transition-colors focus:border-[var(--foreground)]/25"
                      />
                    </div>

                    <div>
                      <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                        {t("Markdown body")}
                      </label>
                      <textarea
                        value={skillEditor.content}
                        onChange={(e) =>
                          setSkillEditor({
                            ...skillEditor,
                            content: e.target.value,
                          })
                        }
                        rows={16}
                        spellCheck={false}
                        className="w-full resize-y rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-mono text-[12px] leading-relaxed outline-none transition-colors focus:border-[var(--foreground)]/25"
                      />
                      <p className="mt-1 text-[11px] text-[var(--muted-foreground)]/70">
                        {t(
                          "YAML frontmatter is optional and is auto-managed for name and description.",
                        )}
                      </p>
                    </div>

                    {skillEditor.error && (
                      <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                        {skillEditor.error}
                      </div>
                    )}
                  </div>

                  <div className="flex items-center justify-end gap-2 border-t border-[var(--border)] px-5 py-3">
                    <button
                      onClick={() => setSkillEditor(null)}
                      className="rounded-md px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                    >
                      {t("Cancel")}
                    </button>
                    <button
                      onClick={() => void handleSaveSkill()}
                      disabled={skillEditor.saving}
                      className="inline-flex items-center gap-1.5 rounded-md bg-[var(--foreground)] px-3.5 py-1.5 text-[12px] font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-50"
                    >
                      {skillEditor.saving && (
                        <Loader2 size={12} className="animate-spin" />
                      )}
                      {t("Save")}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function KnowledgePage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[50vh] items-center justify-center text-[13px] text-[var(--muted-foreground)]">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      }
    >
      <KnowledgePageContent />
    </Suspense>
  );
}
