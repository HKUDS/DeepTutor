"use client";

import { useState, useEffect, useCallback, useRef } from "react";

// Type declarations for FileSystem Entry API (drag & drop folder support)
interface FileSystemEntry {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
}

interface FileSystemFileEntry extends FileSystemEntry {
  file(
    successCallback: (file: File) => void,
    errorCallback?: (error: Error) => void,
  ): void;
}

interface FileSystemDirectoryEntry extends FileSystemEntry {
  createReader(): FileSystemDirectoryReader;
}

interface FileSystemDirectoryReader {
  readEntries(
    successCallback: (entries: FileSystemEntry[]) => void,
    errorCallback?: (error: Error) => void,
  ): void;
}

import {
  BookOpen,
  Database,
  FileText,
  Image as ImageIcon,
  Layers,
  MoreVertical,
  Plus,
  Search,
  Upload,
  Trash2,
  Loader2,
  X,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Star,
} from "lucide-react";
import { apiUrl, wsUrl } from "@/lib/api";

interface ProgressInfo {
  stage: string;
  message: string;
  percent?: number;
  progress_percent?: number; // Legacy field from WebSocket
  current: number;
  total: number;
  file_name?: string;
  error?: string;
  timestamp?: string;
}

interface KnowledgeBase {
  name: string;
  is_default: boolean;
  status?: string; // "initializing", "processing", "ready", "error"
  progress?: ProgressInfo;
  statistics: {
    raw_documents: number;
    images: number;
    content_lists: number;
    rag_initialized: boolean;
    rag_provider?: string;
    status?: string;
    progress?: ProgressInfo;
    rag?: {
      chunks?: number;
      entities?: number;
      relations?: number;
    };
  };
}

interface UploadFile {
  file: File;
  id: string;
  name: string;
  type: string;
  size: number;
}

export default function KnowledgePage() {
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [targetKb, setTargetKb] = useState<string>("");
  const [uploading, setUploading] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<UploadFile[]>([]);
  const [newKbName, setNewKbName] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const [ragProvider, setRagProvider] = useState<string>("llamaindex");
  const [ragProviders, setRagProviders] = useState<
    Array<{ id: string; name: string; description: string }>
  >([]);
  const [progressMap, setProgressMap] = useState<Record<string, ProgressInfo>>(
    {},
  );

  // Toast notification system
  const [toast, setToast] = useState<{
    message: string;
    type: "success" | "error" | "info";
  } | null>(null);

  // Helper function to generate unique ID
  const generateFileId = () => Math.random().toString(36).substring(2, 15);

  // Helper function to get file extension
  const getFileExtension = (filename: string): string => {
    const parts = filename.split(".");
    return parts.length > 1 ? parts.pop()?.toLowerCase() || "" : "";
  };

  // Supported file extensions per RAG provider (based on actual backend capabilities)
  const PROVIDER_SUPPORTED_EXTENSIONS: Record<string, string[]> = {
    // LlamaIndex: PDF + plain text files only (uses PyMuPDF for PDF, direct read for text)
    llamaindex: [
      "pdf",
      "txt",
      "md",
      "markdown",
      "json",
      "csv",
      "html",
      "htm",
      "xml",
      "yaml",
      "yml",
      "toml",
      "tex",
      "rst",
      "log",
    ],
    // LightRAG: Same as LlamaIndex - PDF + plain text files (uses FileTypeRouter + PDFParser)
    lightrag: [
      "pdf",
      "txt",
      "md",
      "markdown",
      "json",
      "csv",
      "html",
      "htm",
      "xml",
      "yaml",
      "yml",
      "toml",
      "tex",
      "rst",
      "log",
    ],
    // RAGAnything: Full multimodal support - PDF, Word, Images, and plain text (uses MinerU)
    raganything: [
      "pdf",
      "doc",
      "docx",
      "txt",
      "md",
      "markdown",
      "json",
      "csv",
      "html",
      "htm",
      "xml",
      "yaml",
      "yml",
      "toml",
      "tex",
      "rst",
      "log",
      "png",
      "jpg",
      "jpeg",
      "gif",
      "webp",
      "bmp",
      "tiff",
      "tif",
    ],
  };

  // Human-readable file type hints for each provider
  const PROVIDER_FILE_HINTS: Record<string, string> = {
    llamaindex: "PDF, TXT, MD, JSON, CSV, HTML, XML...",
    lightrag: "PDF, TXT, MD, JSON, CSV, HTML, XML...",
    raganything: "PDF, Word, 图片, TXT, MD, JSON, CSV, HTML...",
  };

  // Get supported extensions for current provider
  const getSupportedExtensions = (provider: string): string[] => {
    return (
      PROVIDER_SUPPORTED_EXTENSIONS[provider] ||
      PROVIDER_SUPPORTED_EXTENSIONS.llamaindex
    );
  };

  // Get file type hint for current provider
  const getFileTypeHint = (provider: string): string => {
    return PROVIDER_FILE_HINTS[provider] || PROVIDER_FILE_HINTS.llamaindex;
  };

  // Get accept attribute for file input based on provider
  const getAcceptAttribute = (provider: string): string => {
    const extensions = getSupportedExtensions(provider);
    return extensions.map((ext) => `.${ext}`).join(",");
  };

  const isSupportedFile = (filename: string): boolean => {
    const ext = getFileExtension(filename);
    const supportedExtensions = getSupportedExtensions(ragProvider);
    return supportedExtensions.includes(ext);
  };

  // Helper function to convert File to UploadFile
  const fileToUploadFile = (file: File): UploadFile => ({
    file,
    id: generateFileId(),
    name: file.name,
    type: getFileExtension(file.name),
    size: file.size,
  });

  // Helper function to add files (avoiding duplicates)
  const addFiles = (newFiles: File[]) => {
    setUploadFiles((prev) => {
      const existingNames = new Set(prev.map((f) => f.name));
      const uniqueNewFiles = newFiles
        .filter((f) => !existingNames.has(f.name))
        .map(fileToUploadFile);
      return [...prev, ...uniqueNewFiles];
    });
  };

  // Helper function to remove a file
  const removeFile = (fileId: string) => {
    setUploadFiles((prev) => prev.filter((f) => f.id !== fileId));
  };

  // Helper function to clear all files
  const clearAllFiles = () => {
    setUploadFiles([]);
  };

  // Helper function to recursively read directory entries
  const readDirectoryRecursively = async (
    dirEntry: FileSystemDirectoryEntry,
  ): Promise<File[]> => {
    const files: File[] = [];
    const reader = dirEntry.createReader();

    const readEntries = (): Promise<FileSystemEntry[]> => {
      return new Promise((resolve, reject) => {
        reader.readEntries(resolve, reject);
      });
    };

    const getFile = (fileEntry: FileSystemFileEntry): Promise<File> => {
      return new Promise((resolve, reject) => {
        fileEntry.file(resolve, reject);
      });
    };

    let entries: FileSystemEntry[];
    do {
      entries = await readEntries();
      for (const entry of entries) {
        if (entry.isFile) {
          const file = await getFile(entry as FileSystemFileEntry);
          // Filter supported file types
          if (isSupportedFile(file.name)) {
            files.push(file);
          }
        } else if (entry.isDirectory) {
          const subFiles = await readDirectoryRecursively(
            entry as FileSystemDirectoryEntry,
          );
          files.push(...subFiles);
        }
      }
    } while (entries.length > 0);

    return files;
  };

  // Helper function to process dropped items (files and folders)
  const processDroppedItems = async (dataTransfer: DataTransfer) => {
    const items = dataTransfer.items;
    const allFiles: File[] = [];

    const processItem = async (item: DataTransferItem): Promise<File[]> => {
      const entry = item.webkitGetAsEntry?.();
      if (!entry) {
        // Fallback: try to get as file
        const file = item.getAsFile();
        if (file && isSupportedFile(file.name)) {
          return [file];
        }
        return [];
      }

      if (entry.isFile) {
        return new Promise((resolve) => {
          (entry as unknown as FileSystemFileEntry).file(
            (file) => {
              if (isSupportedFile(file.name)) {
                resolve([file]);
              } else {
                resolve([]);
              }
            },
            () => resolve([]),
          );
        });
      } else if (entry.isDirectory) {
        return readDirectoryRecursively(
          entry as unknown as FileSystemDirectoryEntry,
        );
      }
      return [];
    };

    // Process all items in parallel
    const promises: Promise<File[]>[] = [];
    for (let i = 0; i < items.length; i++) {
      promises.push(processItem(items[i]));
    }

    const results = await Promise.all(promises);
    results.forEach((files) => allFiles.push(...files));

    return allFiles;
  };

  // Helper function to format file size
  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  };

  // Helper function to get file icon based on type
  const getFileIcon = (type: string) => {
    switch (type) {
      case "pdf":
        return <FileText className="w-4 h-4 text-red-500" />;
      case "md":
        return <FileText className="w-4 h-4 text-blue-500" />;
      case "txt":
        return <FileText className="w-4 h-4 text-slate-500" />;
      case "doc":
      case "docx":
      case "rtf":
        return <FileText className="w-4 h-4 text-blue-600" />;
      case "html":
      case "htm":
      case "xml":
        return <FileText className="w-4 h-4 text-orange-500" />;
      case "json":
        return <FileText className="w-4 h-4 text-yellow-600" />;
      case "csv":
      case "xlsx":
      case "xls":
        return <FileText className="w-4 h-4 text-green-600" />;
      case "pptx":
      case "ppt":
        return <FileText className="w-4 h-4 text-orange-600" />;
      default:
        return <FileText className="w-4 h-4 text-slate-400" />;
    }
  };

  // Helper function to get file type label
  const getFileTypeLabel = (type: string): string => {
    const labels: Record<string, string> = {
      pdf: "PDF",
      md: "Markdown",
      txt: "Text",
      doc: "Word",
      docx: "Word",
      rtf: "RTF",
      html: "HTML",
      htm: "HTML",
      xml: "XML",
      json: "JSON",
      csv: "CSV",
      xlsx: "Excel",
      xls: "Excel",
      pptx: "PowerPoint",
      ppt: "PowerPoint",
    };
    return labels[type] || type.toUpperCase();
  };

  const showToast = (
    message: string,
    type: "success" | "error" | "info" = "info",
  ) => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  // Use ref only for WebSocket connections (no need for state as it's not used in render)
  const wsConnectionsRef = useRef<Record<string, WebSocket>>({});
  const kbsNamesRef = useRef<string[]>([]);

  // Restore progress state from localStorage (with cleanup of stuck states)
  useEffect(() => {
    try {
      const saved = localStorage.getItem("kb_progress_map");
      if (saved) {
        const parsed = JSON.parse(saved);

        // Clean up stuck progress states (older than 30 minutes and not completed/error)
        const now = new Date().getTime();
        const thirtyMinutes = 30 * 60 * 1000;
        const cleaned: Record<string, ProgressInfo> = {};

        Object.entries(parsed).forEach(([kbName, progress]: [string, any]) => {
          if (progress.timestamp) {
            const progressTime = new Date(progress.timestamp).getTime();
            const age = now - progressTime;

            // Keep if: completed, error, or recent (< 30 min)
            if (
              progress.stage === "completed" ||
              progress.stage === "error" ||
              age < thirtyMinutes
            ) {
              cleaned[kbName] = progress;
            } else {
              console.log(
                `[KB Progress] Clearing stuck progress for ${kbName} (age: ${Math.round(age / 60000)} min)`,
              );
            }
          } else {
            // No timestamp, keep completed/error, clear others
            if (progress.stage === "completed" || progress.stage === "error") {
              cleaned[kbName] = progress;
            }
          }
        });

        setProgressMap(cleaned);
        localStorage.setItem("kb_progress_map", JSON.stringify(cleaned));
      }
    } catch (e) {
      console.error("Failed to load progress from localStorage:", e);
    }
  }, []);

  // Persist progress state to localStorage
  useEffect(() => {
    try {
      localStorage.setItem("kb_progress_map", JSON.stringify(progressMap));
    } catch (e) {
      console.error("Failed to save progress to localStorage:", e);
    }
  }, [progressMap]);

  // Define fetchKnowledgeBases using useCallback to ensure it's available
  const fetchKnowledgeBases = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const baseUrl = apiUrl("");
      const listUrl = apiUrl("/api/v1/knowledge/list");
      const healthUrl = apiUrl("/api/v1/knowledge/health");

      console.log("🔍 Fetching knowledge bases...");
      console.log("  Base URL:", baseUrl);
      console.log("  List URL:", listUrl);
      console.log("  Health URL:", healthUrl);

      // Test health check endpoint first
      try {
        const healthRes = await fetch(healthUrl);
        const healthData = await healthRes.json();
        console.log("✅ Health check response:", healthData);
      } catch (healthErr) {
        console.warn("⚠️ Health check failed:", healthErr);
      }

      // Fetch knowledge base list
      const res = await fetch(listUrl, {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
      });

      console.log("📡 Response status:", res.status, res.statusText);
      console.log(
        "📡 Response headers:",
        Object.fromEntries(res.headers.entries()),
      );

      if (!res.ok) {
        let errorMessage = `HTTP ${res.status}: Failed to fetch knowledge bases`;
        let errorDetail = "";
        try {
          const errorData = await res.json();
          errorDetail = errorData.detail || errorData.message || "";
          errorMessage = errorDetail || errorMessage;
          console.error("❌ Error response:", errorData);
        } catch (parseErr) {
          const text = await res.text();
          console.error("❌ Error response (text):", text);
          errorMessage = `${errorMessage}. Response: ${text.substring(0, 200)}`;
        }
        throw new Error(errorMessage);
      }

      const data = await res.json();
      console.log("✅ Received knowledge bases:", data);
      console.log("✅ Data type:", Array.isArray(data) ? "array" : typeof data);
      console.log("✅ Data length:", Array.isArray(data) ? data.length : "N/A");

      if (!Array.isArray(data)) {
        throw new Error(
          `Invalid response format: expected array, got ${typeof data}`,
        );
      }

      setKbs(data);
      setError(null); // Clear previous error - empty list is not an error, it's just empty state
    } catch (err: any) {
      console.error("❌ Error fetching knowledge bases:", err);
      console.error("❌ Error stack:", err.stack);

      let errorMessage =
        err.message ||
        "Failed to load knowledge bases. Please ensure the backend is running.";

      // Provide more detailed message for network errors
      if (err.name === "TypeError" && err.message.includes("fetch")) {
        errorMessage = `Network error: Cannot connect to backend at ${apiUrl("")}. Please ensure the backend is running.`;
      }

      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchKnowledgeBases();
  }, [fetchKnowledgeBases]);

  // Auto-poll when any KB is processing/initializing
  useEffect(() => {
    // Check if any KB is in processing/initializing state
    const hasProcessingKb = kbs.some((kb) => {
      const status = kb.statistics.status || kb.status;
      return status === "initializing" || status === "processing";
    });

    if (!hasProcessingKb) {
      return;
    }

    // Poll every 3 seconds while processing
    const intervalId = setInterval(() => {
      fetchKnowledgeBases();
    }, 3000);

    return () => clearInterval(intervalId);
  }, [kbs, fetchKnowledgeBases]);

  // Fetch RAG providers
  useEffect(() => {
    const fetchRagProviders = async () => {
      try {
        const res = await fetch(apiUrl("/api/v1/knowledge/rag-providers"));
        if (res.ok) {
          const data = await res.json();
          setRagProviders(data.providers || []);
        }
      } catch (err) {
        console.error("Failed to fetch RAG providers:", err);
      }
    };
    fetchRagProviders();
  }, []);

  // Establish WebSocket connections for all KBs to receive progress updates (only when KB names change)
  useEffect(() => {
    // Skip if still loading or kbs is not yet loaded
    if (loading || !kbs) {
      return;
    }

    // Only re-establish connections if KB names actually changed
    const currentKbNames = [...kbs.map((kb) => kb.name)].sort();
    const currentKbNamesStr = currentKbNames.join(",");
    const prevKbNames = [...(kbsNamesRef.current || [])].sort();
    const prevKbNamesStr = prevKbNames.join(",");

    // If KB names haven't changed, don't re-establish connections
    if (
      currentKbNamesStr === prevKbNamesStr &&
      currentKbNamesStr !== "" &&
      Object.keys(wsConnectionsRef.current).length > 0
    ) {
      // Update statistics in existing connections context, but don't reconnect
      return;
    }

    // If kbs is empty and we have connections, close them all
    if (kbs.length === 0) {
      if (Object.keys(wsConnectionsRef.current).length > 0) {
        Object.values(wsConnectionsRef.current).forEach((ws) => {
          if (
            ws &&
            (ws.readyState === WebSocket.OPEN ||
              ws.readyState === WebSocket.CONNECTING)
          ) {
            ws.close();
          }
        });
        wsConnectionsRef.current = {};
      }
      kbsNamesRef.current = [];
      return;
    }

    // Close old connections that are no longer needed
    Object.entries(wsConnectionsRef.current).forEach(([kbName, ws]) => {
      if (!kbs.find((kb) => kb.name === kbName)) {
        if (
          ws &&
          (ws.readyState === WebSocket.OPEN ||
            ws.readyState === WebSocket.CONNECTING)
        ) {
          ws.close();
        }
        delete wsConnectionsRef.current[kbName];
      }
    });

    const connections: Record<string, WebSocket> = {
      ...wsConnectionsRef.current,
    };

    kbs.forEach((kb) => {
      // Only create new connection if one doesn't exist
      if (
        connections[kb.name] &&
        connections[kb.name].readyState !== WebSocket.CLOSED
      ) {
        return;
      }
      // Connect to all KBs (not just uninitialized ones)
      // This allows receiving progress updates when adding documents
      const ws = new WebSocket(
        wsUrl(`/api/v1/knowledge/${kb.name}/progress/ws`),
      );

      ws.onopen = () => {
        console.log(`[Progress WS] Connected for KB: ${kb.name}`);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "progress" && data.data) {
            // If KB is already initialized (ready), ignore stale in-progress updates
            // Only accept 'completed' or 'error' or recent updates (within 5 minutes)
            if (kb.statistics.rag_initialized) {
              const progressStage = data.data.stage;
              const progressTime = data.data.timestamp
                ? new Date(data.data.timestamp).getTime()
                : 0;
              const now = new Date().getTime();
              const fiveMinutes = 5 * 60 * 1000;

              // Skip stale in-progress updates for already-ready KBs
              if (progressStage !== "completed" && progressStage !== "error") {
                if (!progressTime || now - progressTime > fiveMinutes) {
                  console.log(
                    `[Progress WS] Ignoring stale progress for ready KB: ${kb.name}`,
                  );
                  return;
                }
              }
            }

            setProgressMap((prev) => {
              const updated = {
                ...prev,
                [kb.name]: data.data,
              };
              // Auto-persist to localStorage
              try {
                localStorage.setItem(
                  "kb_progress_map",
                  JSON.stringify(updated),
                );
              } catch (e) {
                console.error("Failed to save progress to localStorage:", e);
              }
              return updated;
            });

            // Don't auto-refresh KB list when completed or error
            // User can manually refresh using the refresh button
          } else if (data.type === "error") {
            console.error(
              `[Progress WS] Error for KB ${kb.name}:`,
              data.message,
            );
          }
        } catch (e) {
          console.error(
            `[Progress WS] Error parsing message for ${kb.name}:`,
            e,
          );
        }
      };

      ws.onerror = (error) => {
        console.error(`[Progress WS] Error for ${kb.name}:`, error);
      };

      ws.onclose = () => {
        console.log(`[Progress WS] Closed for KB: ${kb.name}`);
      };

      connections[kb.name] = ws;
      wsConnectionsRef.current[kb.name] = ws;
    });

    kbsNamesRef.current = kbs.map((kb) => kb.name);
     
  }, [kbs, loading]);

  // Cleanup all connections on component unmount
  useEffect(() => {
    return () => {
      Object.values(wsConnectionsRef.current).forEach((ws) => {
        if (
          ws &&
          (ws.readyState === WebSocket.OPEN ||
            ws.readyState === WebSocket.CONNECTING)
        ) {
          ws.close();
        }
      });
      wsConnectionsRef.current = {};
    };
  }, []);

  const handleDelete = async (name: string) => {
    if (
      !confirm(
        `Are you sure you want to delete knowledge base "${name}"? This cannot be undone.`,
      )
    )
      return;

    try {
      const res = await fetch(apiUrl(`/api/v1/knowledge/${name}`), {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to delete knowledge base");

      // Also clear progress state for this KB
      clearProgress(name);

      fetchKnowledgeBases();
    } catch (err) {
      console.error(err);
      showToast("Failed to delete knowledge base", "error");
    }
  };

  // Clear progress state for a specific KB (frontend + backend)
  const clearProgress = async (kbName: string) => {
    // Clear frontend state
    setProgressMap((prev) => {
      const updated = { ...prev };
      delete updated[kbName];
      try {
        localStorage.setItem("kb_progress_map", JSON.stringify(updated));
      } catch (e) {
        console.error("Failed to save progress to localStorage:", e);
      }
      return updated;
    });

    // Clear backend progress file
    try {
      await fetch(apiUrl(`/api/v1/knowledge/${kbName}/progress/clear`), {
        method: "POST",
      });
      console.log(`[Progress] Cleared backend progress for KB: ${kbName}`);
    } catch (e) {
      console.error("Failed to clear backend progress:", e);
    }
  };

  // Clear all stuck progress states
  const clearAllStuckProgress = () => {
    setProgressMap((prev) => {
      const cleaned: Record<string, ProgressInfo> = {};
      Object.entries(prev).forEach(([kbName, progress]) => {
        // Only keep completed and error states
        if (progress.stage === "completed" || progress.stage === "error") {
          cleaned[kbName] = progress;
        }
      });
      try {
        localStorage.setItem("kb_progress_map", JSON.stringify(cleaned));
      } catch (e) {
        console.error("Failed to save progress to localStorage:", e);
      }
      return cleaned;
    });
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (uploadFiles.length === 0 || !targetKb) return;

    setUploading(true);
    const formData = new FormData();
    uploadFiles.forEach((uploadFile) => {
      formData.append("files", uploadFile.file);
    });

    // Add rag_provider to form data if user selected one different from KB's existing provider
    if (ragProvider) {
      formData.append("rag_provider", ragProvider);
    }

    try {
      const res = await fetch(apiUrl(`/api/v1/knowledge/${targetKb}/upload`), {
        method: "POST",
        body: formData,
      });
      if (!res.ok) throw new Error("Upload failed");

      setUploadModalOpen(false);
      clearAllFiles();
      // Refresh immediately to establish WebSocket connection
      await fetchKnowledgeBases();
      showToast(
        "Files uploaded successfully! Processing started in background.",
        "success",
      );
    } catch (err) {
      console.error(err);
      showToast("Failed to upload files", "error");
    } finally {
      setUploading(false);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKbName || uploadFiles.length === 0) return;

    setUploading(true);
    const formData = new FormData();
    formData.append("name", newKbName);
    formData.append("rag_provider", ragProvider);
    uploadFiles.forEach((uploadFile) => {
      formData.append("files", uploadFile.file);
    });

    try {
      const res = await fetch(apiUrl("/api/v1/knowledge/create"), {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const errorData = await res.json();
        showToast(errorData.detail || "Creation failed", "error");
        setUploading(false);
        return;
      }

      const result = await res.json();

      setCreateModalOpen(false);
      clearAllFiles();
      setNewKbName("");
      setRagProvider("llamaindex"); // Reset to default

      // Immediately refresh to get the new KB from backend
      // (Backend now registers KB to kb_config.json immediately with status)
      await fetchKnowledgeBases();

      showToast("Knowledge base created successfully!", "success");
    } catch (err: any) {
      console.error(err);
      showToast(`Failed to create knowledge base: ${err.message}`, "error");
    } finally {
      setUploading(false);
    }
  };

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      // Use the new folder-aware processing
      const droppedFiles = await processDroppedItems(e.dataTransfer);
      if (droppedFiles.length > 0) {
        addFiles(droppedFiles);
      }
    } else if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      // Fallback for browsers that don't support DataTransferItem
      const validFiles = Array.from(e.dataTransfer.files).filter((file) =>
        isSupportedFile(file.name),
      );
      if (validFiles.length > 0) {
        addFiles(validFiles);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Helper functions are stable
  }, []);

  return (
    <div className="animate-fade-in h-screen overflow-y-auto p-6">
      {/* Header */}
      <div className="flex justify-between items-end mb-8">
        <div>
          <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100 tracking-tight flex items-center gap-3">
            <BookOpen className="w-8 h-8 text-blue-600 dark:text-blue-400" />
            Knowledge Bases
          </h1>
          <p className="text-slate-500 dark:text-slate-400 mt-2">
            Manage and explore your educational content repositories.
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={async () => {
              setLoading(true);
              await fetchKnowledgeBases();
            }}
            className="bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-4 py-2 rounded-lg text-sm font-medium hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors flex items-center gap-2 border border-slate-200 dark:border-slate-600 shadow-sm hover:shadow"
            title="Refresh knowledge bases"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
          <button
            onClick={() => {
              clearAllFiles();
              setNewKbName("");
              setRagProvider("llamaindex");
              setCreateModalOpen(true);
            }}
            className="bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 px-4 py-2 rounded-lg text-sm font-medium hover:bg-slate-800 dark:hover:bg-slate-200 transition-colors flex items-center gap-2 shadow-lg shadow-slate-900/20"
          >
            <Plus className="w-4 h-4" />
            New Knowledge Base
          </button>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 p-4 rounded-xl border border-red-100 dark:border-red-800 mb-6 flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-red-500" />
          {error}
        </div>
      )}

      {/* Loading State */}
      {loading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="bg-white dark:bg-slate-800 h-48 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 animate-pulse"
            />
          ))}
        </div>
      )}

      {/* KB Grid */}
      {!loading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {kbs.map((kb) => (
            <div
              key={kb.name}
              className="group bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 hover:shadow-md transition-all duration-300 hover:-translate-y-1 overflow-hidden flex flex-col"
            >
              {/* Card Header */}
              <div className="p-6 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex justify-between items-start">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-white dark:bg-slate-700 rounded-xl border border-slate-200 dark:border-slate-600 flex items-center justify-center shadow-sm">
                    <Database className="w-5 h-5 text-blue-500 dark:text-blue-400" />
                  </div>
                  <div>
                    <h3 className="font-bold text-slate-900 dark:text-slate-100">
                      {kb.name}
                    </h3>
                    <div className="flex items-center gap-1.5 mt-1">
                      {kb.is_default && (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-blue-50 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400 text-[10px] font-bold uppercase tracking-wide border border-blue-100 dark:border-blue-800">
                          Default
                        </span>
                      )}
                      {kb.statistics.rag_provider && (
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide border ${
                            kb.statistics.rag_provider === "raganything"
                              ? "bg-purple-50 dark:bg-purple-900/40 text-purple-600 dark:text-purple-400 border-purple-100 dark:border-purple-800"
                              : kb.statistics.rag_provider === "lightrag"
                                ? "bg-emerald-50 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400 border-emerald-100 dark:border-emerald-800"
                                : "bg-amber-50 dark:bg-amber-900/40 text-amber-600 dark:text-amber-400 border-amber-100 dark:border-amber-800"
                          }`}
                        >
                          {kb.statistics.rag_provider === "raganything"
                            ? "RAG-Anything"
                            : kb.statistics.rag_provider === "lightrag"
                              ? "LightRAG"
                              : kb.statistics.rag_provider === "llamaindex"
                                ? "LlamaIndex"
                                : kb.statistics.rag_provider}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  {!kb.is_default && (
                    <button
                      onClick={async () => {
                        try {
                          const res = await fetch(
                            apiUrl(`/api/v1/knowledge/default/${kb.name}`),
                            {
                              method: "PUT",
                            },
                          );
                          if (!res.ok) throw new Error("Failed to set default");
                          showToast(
                            `Set "${kb.name}" as default knowledge base`,
                            "success",
                          );
                          fetchKnowledgeBases();
                        } catch (err) {
                          console.error(err);
                          showToast(
                            "Failed to set default knowledge base",
                            "error",
                          );
                        }
                      }}
                      className="p-2 hover:bg-amber-100 dark:hover:bg-amber-900/40 rounded-lg text-slate-500 dark:text-slate-400 hover:text-amber-600 dark:hover:text-amber-400 transition-colors"
                      title="Set as Default"
                    >
                      <Star className="w-4 h-4" />
                    </button>
                  )}
                  <button
                    onClick={() => {
                      setTargetKb(kb.name);
                      clearAllFiles();
                      // Set RAG provider to KB's existing provider or default
                      setRagProvider(
                        kb.statistics.rag_provider || "llamaindex",
                      );
                      setUploadModalOpen(true);
                    }}
                    className="p-2 hover:bg-slate-200 dark:hover:bg-slate-600 rounded-lg text-slate-500 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
                    title="Upload Documents"
                  >
                    <Upload className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => handleDelete(kb.name)}
                    className="p-2 hover:bg-red-100 dark:hover:bg-red-900/40 rounded-lg text-slate-500 dark:text-slate-400 hover:text-red-600 dark:hover:text-red-400 transition-colors"
                    title="Delete Knowledge Base"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {/* Stats */}
              <div className="p-6 space-y-4 flex-1">
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-slate-50 dark:bg-slate-700/50 p-3 rounded-lg">
                    <p className="text-xs text-slate-500 dark:text-slate-400 font-medium mb-1 flex items-center gap-1.5">
                      <FileText className="w-3 h-3" /> Documents
                    </p>
                    <p className="text-lg font-bold text-slate-700 dark:text-slate-200">
                      {kb.statistics.raw_documents}
                    </p>
                  </div>
                  <div className="bg-slate-50 dark:bg-slate-700/50 p-3 rounded-lg">
                    <p className="text-xs text-slate-500 dark:text-slate-400 font-medium mb-1 flex items-center gap-1.5">
                      <ImageIcon className="w-3 h-3" /> Images
                    </p>
                    <p className="text-lg font-bold text-slate-700 dark:text-slate-200">
                      {kb.statistics.images}
                    </p>
                  </div>
                </div>

                <div className="pt-2">
                  <div className="flex items-center justify-between text-xs mb-2">
                    <span className="text-slate-500 dark:text-slate-400 font-medium flex items-center gap-1.5">
                      <Layers className="w-3 h-3" /> Status
                    </span>
                    {(() => {
                      // Priority: API progress > WebSocket progressMap > rag_initialized
                      const apiProgress = kb.statistics.progress || kb.progress;
                      const wsProgress = progressMap[kb.name];
                      const progress = apiProgress || wsProgress;
                      const status = kb.statistics.status || kb.status;

                      if (
                        status === "ready" ||
                        progress?.stage === "completed"
                      ) {
                        return (
                          <span className="text-emerald-600 dark:text-emerald-400 font-bold">
                            Ready
                          </span>
                        );
                      } else if (
                        status === "error" ||
                        progress?.stage === "error"
                      ) {
                        return (
                          <span className="text-red-600 dark:text-red-400 font-bold">
                            Error
                          </span>
                        );
                      } else if (
                        status === "initializing" ||
                        status === "processing" ||
                        progress
                      ) {
                        // Display current stage and progress
                        const stageLabels: Record<string, string> = {
                          initializing: "Initializing",
                          processing_documents: "Processing",
                          processing_file: "Processing File",
                          extracting_items: "Extracting Items",
                        };
                        const stage =
                          progress?.stage || status || "initializing";
                        const stageLabel = stageLabels[stage] || stage;
                        const percent =
                          progress?.percent ?? progress?.progress_percent ?? 0;
                        return (
                          <span className="text-blue-600 dark:text-blue-400 font-bold flex items-center gap-1">
                            <Loader2 className="w-3 h-3 animate-spin" />
                            {stageLabel} {percent}%
                          </span>
                        );
                      }
                      return (
                        <span
                          className={
                            kb.statistics.rag_initialized
                              ? "text-emerald-600 dark:text-emerald-400 font-bold"
                              : "text-slate-400 dark:text-slate-500"
                          }
                        >
                          {kb.statistics.rag_initialized
                            ? "Ready"
                            : "Not Indexed"}
                        </span>
                      );
                    })()}
                  </div>
                  <div className="w-full bg-slate-100 dark:bg-slate-700 rounded-full h-1.5 overflow-hidden">
                    {(() => {
                      const apiProgress = kb.statistics.progress || kb.progress;
                      const wsProgress = progressMap[kb.name];
                      const progress = apiProgress || wsProgress;
                      const status = kb.statistics.status || kb.status;

                      if (
                        progress ||
                        status === "initializing" ||
                        status === "processing"
                      ) {
                        const percent =
                          progress?.percent ?? progress?.progress_percent ?? 0;
                        let bgColor = "bg-blue-500";
                        if (
                          status === "ready" ||
                          progress?.stage === "completed"
                        ) {
                          bgColor = "bg-emerald-500";
                        } else if (
                          status === "error" ||
                          progress?.stage === "error"
                        ) {
                          bgColor = "bg-red-500";
                        }
                        return (
                          <div
                            className={`h-full rounded-full ${bgColor} transition-all duration-300`}
                            style={{
                              width: `${Math.max(percent, status === "initializing" ? 5 : 0)}%`,
                            }}
                          />
                        );
                      }
                      return (
                        <div
                          className={`h-full rounded-full ${kb.statistics.rag_initialized ? "bg-emerald-500 w-full" : "bg-slate-300 w-0"}`}
                        />
                      );
                    })()}
                  </div>
                  {(() => {
                    const apiProgress = kb.statistics.progress || kb.progress;
                    const wsProgress = progressMap[kb.name];
                    const progress = apiProgress || wsProgress;
                    const status = kb.statistics.status || kb.status;

                    if (
                      progress?.message ||
                      (status && status !== "ready" && status !== "unknown")
                    ) {
                      return (
                        <div className="mt-2 space-y-1">
                          <div className="text-[10px] text-slate-600 dark:text-slate-400 font-medium flex items-center justify-between">
                            <span>
                              {progress?.message || `Status: ${status}`}
                            </span>
                            {/* Clear button for stuck states */}
                            {progress?.stage !== "completed" &&
                              status !== "ready" && (
                                <button
                                  onClick={async (e) => {
                                    e.stopPropagation();
                                    await clearProgress(kb.name);
                                    // Refresh KB list to show correct status
                                    fetchKnowledgeBases();
                                  }}
                                  className="text-slate-400 dark:text-slate-500 hover:text-red-500 dark:hover:text-red-400 transition-colors"
                                  title="Clear progress status"
                                >
                                  <X className="w-3 h-3" />
                                </button>
                              )}
                          </div>
                          {progress?.file_name && (
                            <div className="text-[10px] text-slate-500 dark:text-slate-400 flex items-center gap-1">
                              <FileText className="w-3 h-3" />
                              <span className="truncate">
                                {progress.file_name}
                              </span>
                            </div>
                          )}
                          {progress &&
                            progress.current > 0 &&
                            progress.total > 0 && (
                              <div className="text-[10px] text-slate-400 dark:text-slate-500">
                                File {progress.current} of {progress.total}
                              </div>
                            )}
                          {progress?.error && (
                            <div className="text-[10px] text-red-600 dark:text-red-400 mt-1">
                              Error: {progress.error}
                            </div>
                          )}
                        </div>
                      );
                    }
                    if (kb.statistics.rag) {
                      return (
                        <div className="mt-2 space-y-1">
                          <div className="flex gap-3 text-[10px] text-slate-400 dark:text-slate-500">
                            <span>{kb.statistics.rag.chunks} chunks</span>
                            <span>•</span>
                            <span>{kb.statistics.rag.entities} entities</span>
                          </div>
                          {kb.statistics.rag_provider && (
                            <div className="text-[10px] text-slate-500 dark:text-slate-400">
                              Provider:{" "}
                              <span className="font-semibold text-slate-600 dark:text-slate-300">
                                {kb.statistics.rag_provider}
                              </span>
                            </div>
                          )}
                        </div>
                      );
                    }
                    if (kb.statistics.rag_provider) {
                      return (
                        <div className="mt-2 text-[10px] text-slate-500 dark:text-slate-400">
                          Provider:{" "}
                          <span className="font-semibold text-slate-600 dark:text-slate-300">
                            {kb.statistics.rag_provider}
                          </span>
                        </div>
                      );
                    }
                    return null;
                  })()}
                </div>
              </div>
            </div>
          ))}

          {/* Empty State */}
          {kbs.length === 0 && (
            <div className="col-span-full text-center py-12 text-slate-400 dark:text-slate-500">
              <Database className="w-12 h-12 mx-auto mb-4 opacity-20" />
              <p>No knowledge bases found. Create one to get started.</p>
            </div>
          )}
        </div>
      )}

      {/* Create KB Modal */}
      {createModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 ">
          <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl w-full max-w-md p-6 animate-in zoom-in-95">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">
                Create Knowledge Base
              </h3>
              <button
                onClick={() => setCreateModalOpen(false)}
                className="text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                  Knowledge Base Name
                </label>
                <input
                  type="text"
                  required
                  value={newKbName}
                  onChange={(e) => setNewKbName(e.target.value)}
                  placeholder="e.g., Math101"
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                  RAG Provider
                </label>
                <select
                  value={ragProvider}
                  onChange={(e) => setRagProvider(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all"
                >
                  {ragProviders.length > 0 ? (
                    ragProviders.map((provider) => (
                      <option key={provider.id} value={provider.id}>
                        {provider.name}
                      </option>
                    ))
                  ) : (
                    <>
                      <option value="llamaindex">LlamaIndex</option>
                      <option value="lightrag">LightRAG</option>
                      <option value="raganything">RAG-Anything</option>
                    </>
                  )}
                </select>
                {/* Provider description */}
                <div className="mt-2 p-2.5 bg-slate-50 dark:bg-slate-700/50 rounded-lg border border-slate-100 dark:border-slate-600">
                  <p className="text-xs text-slate-600 dark:text-slate-300">
                    {(() => {
                      const selectedProvider = ragProviders.find(
                        (p) => p.id === ragProvider,
                      );
                      if (selectedProvider?.description) {
                        return selectedProvider.description;
                      }
                      // Fallback descriptions
                      const fallbackDescriptions: Record<string, string> = {
                        llamaindex:
                          "Pure vector retrieval, fastest processing speed.",
                        lightrag:
                          "Lightweight knowledge graph retrieval, fast processing of text documents.",
                        raganything:
                          "Multimodal document processing with chart and formula extraction, builds knowledge graphs.",
                      };
                      return (
                        fallbackDescriptions[ragProvider] ||
                        "Select a RAG pipeline suitable for your document type"
                      );
                    })()}
                  </p>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                  Upload Documents
                </label>
                <div
                  className={`border-2 border-dashed rounded-xl p-8 text-center transition-colors ${
                    dragActive
                      ? "border-blue-500 bg-blue-50 dark:bg-blue-900/30"
                      : "border-slate-200 dark:border-slate-600 hover:border-blue-400 dark:hover:border-blue-500 bg-slate-50 dark:bg-slate-700/50"
                  }`}
                  onDragEnter={handleDrag}
                  onDragLeave={handleDrag}
                  onDragOver={handleDrag}
                  onDrop={handleDrop}
                >
                  <input
                    type="file"
                    multiple
                    className="hidden"
                    id="kb-file-upload"
                    onChange={(e) => {
                      if (e.target.files) {
                        const validFiles = Array.from(e.target.files).filter(
                          (file) => isSupportedFile(file.name),
                        );
                        addFiles(validFiles);
                      }
                      e.target.value = ""; // Reset input to allow re-selecting same files
                    }}
                    accept={getAcceptAttribute(ragProvider)}
                  />

                  {/* Drop zone / Click to upload area */}
                  <label
                    htmlFor="kb-file-upload"
                    className={`cursor-pointer flex flex-col items-center gap-2 ${uploadFiles.length > 0 ? "p-4" : "p-8"}`}
                  >
                    <Upload
                      className={`w-6 h-6 ${dragActive ? "text-blue-500 dark:text-blue-400" : "text-slate-400 dark:text-slate-500"}`}
                    />
                    <span className="text-sm font-medium text-slate-600 dark:text-slate-300">
                      {uploadFiles.length > 0
                        ? "Click or drop to add more files"
                        : "Drag & drop files or folders here"}
                    </span>
                    <span className="text-xs text-slate-400 dark:text-slate-500">
                      {getFileTypeHint(ragProvider)}
                    </span>
                  </label>

                  {/* File list */}
                  {uploadFiles.length > 0 && (
                    <div className="border-t border-slate-200 dark:border-slate-600 px-3 py-2 max-h-48 overflow-y-auto">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                          {uploadFiles.length} file
                          {uploadFiles.length > 1 ? "s" : ""} selected
                        </span>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.preventDefault();
                            clearAllFiles();
                          }}
                          className="text-xs text-red-500 hover:text-red-600 dark:text-red-400 dark:hover:text-red-300 font-medium"
                        >
                          Clear all
                        </button>
                      </div>
                      <div className="space-y-1">
                        {uploadFiles.map((file) => (
                          <div
                            key={file.id}
                            className="flex items-center justify-between gap-2 p-2 bg-white dark:bg-slate-700 rounded-lg border border-slate-100 dark:border-slate-600 group"
                          >
                            <div className="flex items-center gap-2 min-w-0 flex-1">
                              {getFileIcon(file.type)}
                              <div className="min-w-0 flex-1">
                                <p
                                  className="text-sm font-medium text-slate-700 dark:text-slate-200 truncate"
                                  title={file.name}
                                >
                                  {file.name}
                                </p>
                                <p className="text-xs text-slate-400 dark:text-slate-500">
                                  {getFileTypeLabel(file.type)} •{" "}
                                  {formatFileSize(file.size)}
                                </p>
                              </div>
                            </div>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.preventDefault();
                                removeFile(file.id);
                              }}
                              className="p-1 text-slate-400 hover:text-red-500 dark:text-slate-500 dark:hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                              title="Remove file"
                            >
                              <X className="w-4 h-4" />
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setCreateModalOpen(false)}
                  className="flex-1 py-2.5 rounded-xl border border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300 font-medium hover:bg-slate-50 dark:hover:bg-slate-700"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!newKbName || uploadFiles.length === 0 || uploading}
                  className="flex-1 py-2.5 rounded-xl bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 font-medium hover:bg-slate-800 dark:hover:bg-slate-200 disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {uploading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    "Create & Initialize"
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Upload Modal (Existing) */}
      {uploadModalOpen && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl w-full max-w-md p-6 animate-in zoom-in-95">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">
                Upload Documents
              </h3>
              <button
                onClick={() => setUploadModalOpen(false)}
                className="text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
              Upload documents to{" "}
              <strong className="text-slate-700 dark:text-slate-200">
                {targetKb}
              </strong>
            </p>

            <form onSubmit={handleUpload} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                  RAG Provider (Optional)
                </label>
                <select
                  value={ragProvider}
                  onChange={(e) => setRagProvider(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all"
                >
                  {ragProviders.length > 0 ? (
                    ragProviders.map((provider) => (
                      <option key={provider.id} value={provider.id}>
                        {provider.name}
                      </option>
                    ))
                  ) : (
                    <>
                      <option value="llamaindex">LlamaIndex</option>
                      <option value="lightrag">LightRAG</option>
                      <option value="raganything">RAG-Anything</option>
                    </>
                  )}
                </select>
                {/* Provider description */}
                <div className="mt-2 p-2.5 bg-slate-50 dark:bg-slate-700/50 rounded-lg border border-slate-100 dark:border-slate-600">
                  <p className="text-xs text-slate-600 dark:text-slate-300">
                    {(() => {
                      const selectedProvider = ragProviders.find(
                        (p) => p.id === ragProvider,
                      );
                      if (selectedProvider?.description) {
                        return selectedProvider.description;
                      }
                      const fallbackDescriptions: Record<string, string> = {
                        llamaindex:
                          "Pure vector retrieval, fastest processing speed.",
                        lightrag:
                          "Lightweight knowledge graph retrieval, fast processing of text documents.",
                        raganything:
                          "Multimodal document processing with chart and formula extraction, builds knowledge graphs.",
                      };
                      return (
                        fallbackDescriptions[ragProvider] ||
                        "Select a RAG pipeline suitable for your document type"
                      );
                    })()}
                  </p>
                </div>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  Leave as-is to use the KB&apos;s existing provider
                </p>
              </div>

              <div
                className={`border-2 border-dashed rounded-xl transition-colors ${
                  dragActive
                    ? "border-blue-500 bg-blue-50 dark:bg-blue-900/30"
                    : "border-slate-200 dark:border-slate-600 hover:border-blue-400 dark:hover:border-blue-500 bg-slate-50 dark:bg-slate-700/50"
                }`}
                onDragEnter={handleDrag}
                onDragLeave={handleDrag}
                onDragOver={handleDrag}
                onDrop={handleDrop}
              >
                <input
                  type="file"
                  multiple
                  className="hidden"
                  id="file-upload"
                  onChange={(e) => {
                    if (e.target.files) {
                      const validFiles = Array.from(e.target.files).filter(
                        (file) => isSupportedFile(file.name),
                      );
                      addFiles(validFiles);
                    }
                    e.target.value = ""; // Reset input to allow re-selecting same files
                  }}
                  accept={getAcceptAttribute(ragProvider)}
                />

                {/* Drop zone / Click to upload area */}
                <label
                  htmlFor="file-upload"
                  className={`cursor-pointer flex flex-col items-center gap-2 ${uploadFiles.length > 0 ? "p-4" : "p-8"}`}
                >
                  <Upload
                    className={`w-6 h-6 ${dragActive ? "text-blue-500 dark:text-blue-400" : "text-slate-400 dark:text-slate-500"}`}
                  />
                  <span className="text-sm font-medium text-slate-600 dark:text-slate-300">
                    {uploadFiles.length > 0
                      ? "Click or drop to add more files"
                      : "Drag & drop files or folders here"}
                  </span>
                  <span className="text-xs text-slate-400 dark:text-slate-500">
                    {getFileTypeHint(ragProvider)}
                  </span>
                </label>

                {/* File list */}
                {uploadFiles.length > 0 && (
                  <div className="border-t border-slate-200 dark:border-slate-600 px-3 py-2 max-h-48 overflow-y-auto">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                        {uploadFiles.length} file
                        {uploadFiles.length > 1 ? "s" : ""} selected
                      </span>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.preventDefault();
                          clearAllFiles();
                        }}
                        className="text-xs text-red-500 hover:text-red-600 dark:text-red-400 dark:hover:text-red-300 font-medium"
                      >
                        Clear all
                      </button>
                    </div>
                    <div className="space-y-1">
                      {uploadFiles.map((file) => (
                        <div
                          key={file.id}
                          className="flex items-center justify-between gap-2 p-2 bg-white dark:bg-slate-700 rounded-lg border border-slate-100 dark:border-slate-600 group"
                        >
                          <div className="flex items-center gap-2 min-w-0 flex-1">
                            {getFileIcon(file.type)}
                            <div className="min-w-0 flex-1">
                              <p
                                className="text-sm font-medium text-slate-700 dark:text-slate-200 truncate"
                                title={file.name}
                              >
                                {file.name}
                              </p>
                              <p className="text-xs text-slate-400 dark:text-slate-500">
                                {getFileTypeLabel(file.type)} •{" "}
                                {formatFileSize(file.size)}
                              </p>
                            </div>
                          </div>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.preventDefault();
                              removeFile(file.id);
                            }}
                            className="p-1 text-slate-400 hover:text-red-500 dark:text-slate-500 dark:hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                            title="Remove file"
                          >
                            <X className="w-4 h-4" />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => setUploadModalOpen(false)}
                  className="flex-1 py-2.5 rounded-xl border border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300 font-medium hover:bg-slate-50 dark:hover:bg-slate-700"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={uploadFiles.length === 0 || uploading}
                  className="flex-1 py-2.5 rounded-xl bg-blue-600 text-white font-medium hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {uploading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    "Upload"
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
