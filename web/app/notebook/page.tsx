"use client";

import { useState, useEffect } from "react";
import {
  BookOpen,
  Plus,
  Trash2,
  Edit3,
  Search,
  Clock,
  FileText,
  Calculator,
  Microscope,
  PenTool,
  ChevronRight,
  ChevronLeft,
  X,
  Check,
  FolderOpen,
  Database,
  Download,
  Upload,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { apiUrl } from "@/lib/api";
import { processLatexContent } from "@/lib/latex";

interface NotebookRecord {
  id: string;
  type: "solve" | "question" | "research" | "co_writer";
  title: string;
  user_query: string;
  output: string;
  metadata: Record<string, any>;
  created_at: number;
  kb_name?: string;
}

interface Notebook {
  id: string;
  name: string;
  description: string;
  created_at: number;
  updated_at: number;
  records: NotebookRecord[];
  color: string;
  icon: string;
}

interface NotebookSummary {
  id: string;
  name: string;
  description: string;
  created_at: number;
  updated_at: number;
  record_count: number;
  color: string;
  icon: string;
}

const COLORS = [
  "#3B82F6", // blue
  "#8B5CF6", // purple
  "#EC4899", // pink
  "#EF4444", // red
  "#F97316", // orange
  "#EAB308", // yellow
  "#22C55E", // green
  "#14B8A6", // teal
  "#06B6D4", // cyan
  "#6366F1", // indigo
];

const getRecordIcon = (type: string) => {
  switch (type) {
    case "solve":
      return <Calculator className="w-4 h-4" />;
    case "question":
      return <FileText className="w-4 h-4" />;
    case "research":
      return <Microscope className="w-4 h-4" />;
    case "co_writer":
      return <PenTool className="w-4 h-4" />;
    default:
      return <FileText className="w-4 h-4" />;
  }
};

const getRecordLabel = (type: string) => {
  switch (type) {
    case "solve":
      return "解题";
    case "question":
      return "题目";
    case "research":
      return "研究";
    case "co_writer":
      return "写作";
    default:
      return "记录";
  }
};

const getRecordColor = (type: string) => {
  switch (type) {
    case "solve":
      return "text-blue-500 bg-blue-50 border-blue-200";
    case "question":
      return "text-purple-500 bg-purple-50 border-purple-200";
    case "research":
      return "text-emerald-500 bg-emerald-50 border-emerald-200";
    case "co_writer":
      return "text-amber-500 bg-amber-50 border-amber-200";
    default:
      return "text-slate-500 bg-slate-50 border-slate-200";
  }
};

export default function NotebookPage() {
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [selectedNotebook, setSelectedNotebook] = useState<Notebook | null>(
    null,
  );
  const [selectedRecord, setSelectedRecord] = useState<NotebookRecord | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");

  // Collapse states
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [middleCollapsed, setMiddleCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);

  // Modal states
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(
    null,
  );

  // Form states
  const [newNotebook, setNewNotebook] = useState({
    name: "",
    description: "",
    color: "#3B82F6",
  });
  const [editingNotebook, setEditingNotebook] = useState<{
    id: string;
    name: string;
    description: string;
    color: string;
  } | null>(null);

  // Layout state for expandable detail panel (deprecated, using rightCollapsed instead)
  // Import modal state
  const [showImportModal, setShowImportModal] = useState(false);
  const [availableNotebooks, setAvailableNotebooks] = useState<
    NotebookSummary[]
  >([]);
  const [importSourceNotebook, setImportSourceNotebook] = useState<string>("");
  const [importSourceRecords, setImportSourceRecords] = useState<
    NotebookRecord[]
  >([]);
  const [selectedImportRecords, setSelectedImportRecords] = useState<
    Set<string>
  >(new Set());
  const [loadingImport, setLoadingImport] = useState(false);

  // Fetch notebooks
  useEffect(() => {
    fetchNotebooks();
  }, []);

  const fetchNotebooks = async () => {
    try {
      const res = await fetch(apiUrl("/api/v1/notebook/list"));
      const data = await res.json();
      setNotebooks(data.notebooks || []);
    } catch (err) {
      console.error("Failed to fetch notebooks:", err);
    } finally {
      setLoading(false);
    }
  };

  const fetchNotebookDetail = async (notebookId: string) => {
    try {
      const res = await fetch(apiUrl(`/api/v1/notebook/${notebookId}`));
      const data = await res.json();
      setSelectedNotebook(data);
      setSelectedRecord(null);
    } catch (err) {
      console.error("Failed to fetch notebook detail:", err);
    }
  };

  const handleCreateNotebook = async () => {
    if (!newNotebook.name.trim()) return;

    try {
      const res = await fetch(apiUrl("/api/v1/notebook/create"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newNotebook),
      });
      const data = await res.json();
      if (data.success) {
        fetchNotebooks();
        setShowCreateModal(false);
        setNewNotebook({ name: "", description: "", color: "#3B82F6" });
      }
    } catch (err) {
      console.error("Failed to create notebook:", err);
    }
  };

  const handleUpdateNotebook = async () => {
    if (!editingNotebook || !editingNotebook.name.trim()) return;

    try {
      const res = await fetch(
        apiUrl(`/api/v1/notebook/${editingNotebook.id}`),
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: editingNotebook.name,
            description: editingNotebook.description,
            color: editingNotebook.color,
          }),
        },
      );
      const data = await res.json();
      if (data.success) {
        fetchNotebooks();
        if (selectedNotebook?.id === editingNotebook.id) {
          fetchNotebookDetail(editingNotebook.id);
        }
        setShowEditModal(false);
        setEditingNotebook(null);
      }
    } catch (err) {
      console.error("Failed to update notebook:", err);
    }
  };

  const handleDeleteNotebook = async (notebookId: string) => {
    try {
      const res = await fetch(apiUrl(`/api/v1/notebook/${notebookId}`), {
        method: "DELETE",
      });
      const data = await res.json();
      if (data.success) {
        fetchNotebooks();
        if (selectedNotebook?.id === notebookId) {
          setSelectedNotebook(null);
        }
        setShowDeleteConfirm(null);
      }
    } catch (err) {
      console.error("Failed to delete notebook:", err);
    }
  };

  const handleDeleteRecord = async (recordId: string) => {
    if (!selectedNotebook) return;

    try {
      const res = await fetch(
        apiUrl(`/api/v1/notebook/${selectedNotebook.id}/records/${recordId}`),
        {
          method: "DELETE",
        },
      );
      const data = await res.json();
      if (data.success) {
        fetchNotebookDetail(selectedNotebook.id);
        if (selectedRecord?.id === recordId) {
          setSelectedRecord(null);
        }
      }
    } catch (err) {
      console.error("Failed to delete record:", err);
    }
  };

  // Export functions
  const exportAsMarkdown = () => {
    if (!selectedRecord) return;

    const content = `# ${selectedRecord.title}\n\n**类型：** ${getRecordLabel(selectedRecord.type)}\n**创建时间：** ${new Date(selectedRecord.created_at * 1000).toLocaleString()}\n\n## 用户问题\n\n${selectedRecord.user_query}\n\n## 输出\n\n${selectedRecord.output}`;

    const blob = new Blob([content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${selectedRecord.title.replace(/[^a-zA-Z0-9]/g, "_")}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportAsPDF = async () => {
    if (!selectedRecord) return;

    // Use browser print for simple PDF export
    const printContent = `
      <html>
        <head>
          <title>${selectedRecord.title}</title>
          <style>
            body { font-family: system-ui, -apple-system, sans-serif; padding: 40px; max-width: 800px; margin: 0 auto; }
            h1 { color: #1e293b; }
            .meta { color: #64748b; font-size: 14px; margin-bottom: 20px; }
            .section { margin: 20px 0; }
            .section-title { font-size: 12px; text-transform: uppercase; color: #94a3b8; font-weight: 600; margin-bottom: 8px; }
            .query { background: #eff6ff; padding: 16px; border-radius: 8px; }
            .output { background: #f8fafc; padding: 16px; border-radius: 8px; white-space: pre-wrap; }
          </style>
        </head>
        <body>
          <h1>${selectedRecord.title}</h1>
          <div class="meta">${getRecordLabel(selectedRecord.type)} • ${new Date(selectedRecord.created_at * 1000).toLocaleString()}</div>
          <div class="section">
            <div class="section-title">用户问题</div>
            <div class="query">${selectedRecord.user_query}</div>
          </div>
          <div class="section">
            <div class="section-title">输出</div>
            <div class="output">${selectedRecord.output}</div>
          </div>
        </body>
      </html>
    `;

    const printWindow = window.open("", "_blank");
    if (printWindow) {
      printWindow.document.write(printContent);
      printWindow.document.close();
      printWindow.print();
    }
  };

  // Import functions
  const openImportModal = async () => {
    if (!selectedNotebook) return;

    setShowImportModal(true);
    setLoadingImport(true);

    try {
      const res = await fetch(apiUrl("/api/v1/notebook/list"));
      const data = await res.json();
      // Filter out current notebook
      const others = (data.notebooks || []).filter(
        (nb: NotebookSummary) =>
          nb.id !== selectedNotebook.id && nb.record_count > 0,
      );
      setAvailableNotebooks(others);
    } catch (err) {
      console.error("Failed to fetch notebooks for import:", err);
    } finally {
      setLoadingImport(false);
    }
  };

  const loadImportSourceRecords = async (notebookId: string) => {
    setImportSourceNotebook(notebookId);
    setLoadingImport(true);

    try {
      const res = await fetch(apiUrl(`/api/v1/notebook/${notebookId}`));
      const data = await res.json();
      setImportSourceRecords(data.records || []);
      setSelectedImportRecords(new Set());
    } catch (err) {
      console.error("Failed to fetch records for import:", err);
    } finally {
      setLoadingImport(false);
    }
  };

  const toggleImportRecord = (recordId: string) => {
    setSelectedImportRecords((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(recordId)) {
        newSet.delete(recordId);
      } else {
        newSet.add(recordId);
      }
      return newSet;
    });
  };

  const handleImportRecords = async () => {
    if (!selectedNotebook || selectedImportRecords.size === 0) return;

    setLoadingImport(true);

    try {
      // Get selected records
      const recordsToImport = importSourceRecords.filter((r) =>
        selectedImportRecords.has(r.id),
      );

      // Add each record to current notebook
      for (const record of recordsToImport) {
        await fetch(apiUrl(`/api/v1/notebook/${selectedNotebook.id}/records`), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            type: record.type,
            title: `[Imported] ${record.title}`,
            user_query: record.user_query,
            output: record.output,
            metadata: {
              ...record.metadata,
              imported_from: importSourceNotebook,
            },
          }),
        });
      }

      // Refresh notebook
      fetchNotebookDetail(selectedNotebook.id);
      setShowImportModal(false);
      setImportSourceNotebook("");
      setImportSourceRecords([]);
      setSelectedImportRecords(new Set());
    } catch (err) {
      console.error("Failed to import records:", err);
    } finally {
      setLoadingImport(false);
    }
  };

  const filteredNotebooks = notebooks.filter(
    (nb) =>
      nb.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      nb.description.toLowerCase().includes(searchTerm.toLowerCase()),
  );

  return (
    <div
      className="h-screen flex gap-4 p-4 animate-fade-in"
      style={{ justifyContent: "flex-start" }}
    >
      {/* Left Panel: Notebook List */}
      <div
        className={`flex flex-col bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden transition-all duration-300 flex-shrink-0 ${leftCollapsed ? "overflow-hidden" : ""}`}
        style={{
          width: leftCollapsed ? 0 : "288px",
          minWidth: leftCollapsed ? 0 : "288px",
          maxWidth: leftCollapsed ? 0 : "288px",
          opacity: leftCollapsed ? 0 : 1,
        }}
      >
        {/* Header */}
        <div className="p-4 border-b border-slate-100 dark:border-slate-700 bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-indigo-900/30 dark:to-purple-900/30">
          <div className="flex items-center justify-between mb-4">
            <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <BookOpen className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
              笔记本
            </h1>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowCreateModal(true)}
                className="p-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-all shadow-md shadow-indigo-500/20"
              >
                <Plus className="w-4 h-4" />
              </button>
              <button
                onClick={() => setLeftCollapsed(true)}
                className="p-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg shadow-sm hover:bg-slate-50 dark:hover:bg-slate-600 transition-all"
                title="收起左侧面板"
              >
                <ChevronLeft className="w-4 h-4 text-slate-600 dark:text-slate-300" />
              </button>
            </div>
          </div>

          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 dark:text-slate-500" />
            <input
              type="text"
              placeholder="搜索笔记本..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none"
            />
          </div>
        </div>

        {/* Notebook List */}
        <div className="flex-1 overflow-y-auto p-2">
          {loading ? (
            <div className="p-8 text-center text-slate-400 dark:text-slate-500">
              加载中...
            </div>
          ) : filteredNotebooks.length === 0 ? (
            <div className="p-8 text-center">
              <FolderOpen className="w-12 h-12 text-slate-200 dark:text-slate-600 mx-auto mb-3" />
              <p className="text-slate-500 dark:text-slate-400 text-sm">
                暂无笔记本
              </p>
              <p className="text-slate-400 dark:text-slate-500 text-xs mt-1">
                创建你的第一个笔记本开始使用
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {filteredNotebooks.map((nb) => (
                <div
                  key={nb.id}
                  onClick={() => fetchNotebookDetail(nb.id)}
                  className={`p-3 rounded-xl cursor-pointer transition-all group ${
                    selectedNotebook?.id === nb.id
                      ? "bg-indigo-50 dark:bg-indigo-900/30 border-2 border-indigo-200 dark:border-indigo-700"
                      : "hover:bg-slate-50 dark:hover:bg-slate-700/50 border-2 border-transparent"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <div
                      className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
                      style={{
                        backgroundColor: `${nb.color}20`,
                        color: nb.color,
                      }}
                    >
                      <BookOpen className="w-5 h-5" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <h3 className="font-semibold text-slate-900 dark:text-slate-100 truncate text-sm">
                          {nb.name}
                        </h3>
                        <div className="opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setEditingNotebook({
                                id: nb.id,
                                name: nb.name,
                                description: nb.description,
                                color: nb.color,
                              });
                              setShowEditModal(true);
                            }}
                            className="p-1 hover:bg-slate-200 dark:hover:bg-slate-600 rounded"
                          >
                            <Edit3 className="w-3 h-3 text-slate-500 dark:text-slate-400" />
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setShowDeleteConfirm(nb.id);
                            }}
                            className="p-1 hover:bg-red-100 dark:hover:bg-red-900/40 rounded"
                          >
                            <Trash2 className="w-3 h-3 text-red-500 dark:text-red-400" />
                          </button>
                        </div>
                      </div>
                      {nb.description && (
                        <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">
                          {nb.description}
                        </p>
                      )}
                      <div className="flex items-center gap-3 mt-2 text-[10px] text-slate-400 dark:text-slate-500">
                        <span className="flex items-center gap-1">
                          <FileText className="w-3 h-3" />
                          {nb.record_count} 条记录
                        </span>
                        <span className="flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {new Date(nb.updated_at * 1000).toLocaleDateString()}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      {leftCollapsed && (
        <button
          onClick={() => setLeftCollapsed(false)}
          className="p-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg shadow-sm hover:bg-slate-50 dark:hover:bg-slate-700 transition-all self-start mt-4 shrink-0"
          title="展开左侧面板"
        >
          <ChevronRight className="w-4 h-4 text-slate-600 dark:text-slate-300" />
        </button>
      )}

      {/* Middle Panel: Records List */}
      <div
        className={`flex flex-col bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden transition-all duration-300 flex-shrink-0 ${middleCollapsed ? "overflow-hidden" : ""}`}
        style={{
          width: middleCollapsed ? 0 : "320px",
          minWidth: middleCollapsed ? 0 : "320px",
          maxWidth: middleCollapsed ? 0 : "320px",
          opacity: middleCollapsed ? 0 : 1,
        }}
      >
        {/* Notebook Header */}
        <div
          className="p-4 border-b border-slate-100 dark:border-slate-700 shrink-0"
          style={{
            backgroundColor: selectedNotebook
              ? `${selectedNotebook.color}10`
              : "transparent",
          }}
        >
          <div className="flex items-center justify-between gap-3">
            {selectedNotebook ? (
              <>
                <div className="flex items-center gap-3 flex-1 min-w-0">
                  <div
                    className="w-12 h-12 rounded-xl flex items-center justify-center shrink-0"
                    style={{
                      backgroundColor: `${selectedNotebook.color}20`,
                      color: selectedNotebook.color,
                    }}
                  >
                    <BookOpen className="w-6 h-6" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h2 className="font-bold text-slate-900 dark:text-slate-100 truncate">
                      {selectedNotebook.name}
                    </h2>
                    {selectedNotebook.description && (
                      <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 truncate">
                        {selectedNotebook.description}
                      </p>
                    )}
                  </div>
                </div>
              </>
            ) : (
              <div className="flex-1" />
            )}
            <button
              onClick={() => setMiddleCollapsed(true)}
              className="p-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg shadow-sm hover:bg-slate-50 dark:hover:bg-slate-600 transition-all shrink-0"
              title="收起中间面板"
            >
              <ChevronLeft className="w-4 h-4 text-slate-600 dark:text-slate-300" />
            </button>
          </div>
        </div>

        {selectedNotebook ? (
          <>
            {/* Records List */}
            <div className="flex-1 overflow-y-auto p-3">
              {selectedNotebook.records.length === 0 ? (
                <div className="p-8 text-center">
                  <FileText className="w-12 h-12 text-slate-200 dark:text-slate-600 mx-auto mb-3" />
                  <p className="text-slate-500 dark:text-slate-400 text-sm">
                    暂无记录
                  </p>
                  <p className="text-slate-400 dark:text-slate-500 text-xs mt-1">
                    可从解题、出题、研究或写作中添加记录
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  {selectedNotebook.records.map((record) => (
                    <div
                      key={record.id}
                      onClick={() => setSelectedRecord(record)}
                      className={`p-3 rounded-xl cursor-pointer transition-all group border ${
                        selectedRecord?.id === record.id
                          ? "bg-slate-50 dark:bg-slate-700/50 border-slate-300 dark:border-slate-600"
                          : "hover:bg-slate-50 dark:hover:bg-slate-700/50 border-transparent hover:border-slate-200 dark:hover:border-slate-600"
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        <div
                          className={`p-2 rounded-lg border ${getRecordColor(record.type)}`}
                        >
                          {getRecordIcon(record.type)}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <span
                              className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${getRecordColor(record.type)}`}
                            >
                              {getRecordLabel(record.type)}
                            </span>
                            {record.kb_name && (
                              <span className="text-[10px] text-slate-400 dark:text-slate-500 flex items-center gap-0.5">
                                <Database className="w-3 h-3" />
                                {record.kb_name}
                              </span>
                            )}
                          </div>
                          <h4 className="text-sm font-medium text-slate-900 dark:text-slate-100 line-clamp-1">
                            {record.title}
                          </h4>
                          <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2 mt-1">
                            {record.user_query}
                          </p>
                          <div className="flex items-center justify-between mt-2">
                            <span className="text-[10px] text-slate-400 dark:text-slate-500">
                              {new Date(
                                record.created_at * 1000,
                              ).toLocaleString()}
                            </span>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeleteRecord(record.id);
                              }}
                              className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-100 dark:hover:bg-red-900/40 rounded transition-all"
                            >
                              <Trash2 className="w-3 h-3 text-red-500 dark:text-red-400" />
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-400 dark:text-slate-500 p-8">
            <BookOpen className="w-16 h-16 text-slate-200 dark:text-slate-600 mb-4" />
            <p className="text-slate-500 dark:text-slate-400">
              请选择一个笔记本查看记录
            </p>
          </div>
        )}
      </div>
      {middleCollapsed && (
        <button
          onClick={() => setMiddleCollapsed(false)}
          className="p-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg shadow-sm hover:bg-slate-50 dark:hover:bg-slate-700 transition-all self-start mt-4 shrink-0"
          title="展开中间面板"
        >
          <ChevronRight className="w-4 h-4 text-slate-600 dark:text-slate-300" />
        </button>
      )}

      {/* Right Panel: Record Detail */}
      <div
        className={`flex flex-col bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden transition-all duration-300 ${rightCollapsed ? "flex-shrink-0 overflow-hidden" : "flex-1"}`}
        style={{
          width: rightCollapsed ? 0 : undefined,
          minWidth: rightCollapsed ? 0 : undefined,
          maxWidth: rightCollapsed ? 0 : undefined,
          opacity: rightCollapsed ? 0 : 1,
          marginLeft: "auto",
          order: 3,
        }}
      >
        {/* Record Header with Action Buttons */}
        <div className="p-4 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 shrink-0">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3 flex-1 min-w-0">
              <button
                onClick={() => setRightCollapsed(true)}
                className="p-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg shadow-sm hover:bg-slate-50 dark:hover:bg-slate-600 transition-all shrink-0"
                title="收起右侧面板"
              >
                <ChevronRight className="w-4 h-4 text-slate-600 dark:text-slate-300" />
              </button>
              {selectedRecord ? (
                <>
                  <div
                    className={`p-2 rounded-lg border ${getRecordColor(selectedRecord.type)} shrink-0`}
                  >
                    {getRecordIcon(selectedRecord.type)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <h2 className="font-bold text-slate-900 dark:text-slate-100 truncate">
                      {selectedRecord.title}
                    </h2>
                    <div className="flex items-center gap-2 mt-1">
                      <span
                        className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${getRecordColor(selectedRecord.type)}`}
                      >
                        {getRecordLabel(selectedRecord.type)}
                      </span>
                      <span className="text-xs text-slate-400 dark:text-slate-500">
                        {new Date(
                          selectedRecord.created_at * 1000,
                        ).toLocaleString()}
                      </span>
                    </div>
                  </div>
                </>
              ) : (
                <div className="flex-1" />
              )}
            </div>

            {/* Action Buttons - Export and History */}
            {selectedRecord && (
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={exportAsMarkdown}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
                  title="导出为 Markdown"
                >
                  <Download className="w-3.5 h-3.5" />
                  .md
                </button>
                <button
                  onClick={exportAsPDF}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
                  title="导出为 PDF"
                >
                  <Download className="w-3.5 h-3.5" />
                  .pdf
                </button>
                <button
                  onClick={openImportModal}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/40 rounded-lg transition-colors"
                  title="从其他笔记本导入记录"
                >
                  <Upload className="w-3.5 h-3.5" />
                  导入
                </button>
              </div>
            )}
          </div>
        </div>

        {selectedRecord ? (
          <>
            {/* Record Content */}
            <div className="flex-1 overflow-y-auto p-6">
              {/* User Query */}
              <div className="mb-6">
                <h3 className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                  用户问题
                </h3>
                <div className="p-4 bg-blue-50 dark:bg-blue-900/30 rounded-xl border border-blue-100 dark:border-blue-800">
                  <p className="text-slate-700 dark:text-slate-200">
                    {selectedRecord.user_query}
                  </p>
                </div>
              </div>

              {/* Output */}
              <div>
                <h3 className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                  输出
                </h3>
                <div className="p-4 bg-slate-50 dark:bg-slate-700/50 rounded-xl border border-slate-100 dark:border-slate-600">
                  <div className="prose prose-slate dark:prose-invert max-w-none prose-sm">
                    <ReactMarkdown
                      remarkPlugins={[remarkMath]}
                      rehypePlugins={[rehypeKatex]}
                    >
                      {processLatexContent(selectedRecord.output)}
                    </ReactMarkdown>
                  </div>
                </div>
              </div>

              {/* Metadata */}
              {Object.keys(selectedRecord.metadata).length > 0 && (
                <div className="mt-6">
                  <h3 className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                    元数据
                  </h3>
                  <div className="p-4 bg-slate-50 dark:bg-slate-700/50 rounded-xl border border-slate-100 dark:border-slate-600">
                    <pre className="text-xs text-slate-600 dark:text-slate-300 overflow-x-auto">
                      {JSON.stringify(selectedRecord.metadata, null, 2)}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-400 dark:text-slate-500 p-8">
            <FileText className="w-16 h-16 text-slate-200 dark:text-slate-600 mb-4" />
            <p className="text-slate-500 dark:text-slate-400">
              请选择一条记录查看详情
            </p>
          </div>
        )}
      </div>
      {rightCollapsed && (
        <button
          onClick={() => setRightCollapsed(false)}
          className="p-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg shadow-sm hover:bg-slate-50 dark:hover:bg-slate-700 transition-all self-start mt-4 shrink-0"
          title="展开右侧面板"
        >
          <ChevronLeft className="w-4 h-4 text-slate-600 dark:text-slate-300" />
        </button>
      )}

      {/* Create Notebook Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 animate-in fade-in">
          <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl w-[400px] animate-in zoom-in-95">
            <div className="p-4 border-b border-slate-100 dark:border-slate-700 flex items-center justify-between">
              <h3 className="font-bold text-slate-900 dark:text-slate-100">
                创建新笔记本
              </h3>
              <button
                onClick={() => setShowCreateModal(false)}
                className="p-1 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg"
              >
                <X className="w-5 h-5 text-slate-500 dark:text-slate-400" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                  名称
                </label>
                <input
                  type="text"
                  value={newNotebook.name}
                  onChange={(e) =>
                    setNewNotebook((prev) => ({
                      ...prev,
                      name: e.target.value,
                    }))
                  }
                  placeholder="我的笔记本"
                  className="w-full px-4 py-2 border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none"
                />
              </div>
              <div>
                <label className="block text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                  描述（可选）
                </label>
                <textarea
                  value={newNotebook.description}
                  onChange={(e) =>
                    setNewNotebook((prev) => ({
                      ...prev,
                      description: e.target.value,
                    }))
                  }
                  placeholder="例如：机器学习笔记..."
                  rows={3}
                  className="w-full px-4 py-2 border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none resize-none"
                />
              </div>
              <div>
                <label className="block text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                  颜色
                </label>
                <div className="flex gap-2 flex-wrap">
                  {COLORS.map((color) => (
                    <button
                      key={color}
                      onClick={() =>
                        setNewNotebook((prev) => ({ ...prev, color }))
                      }
                      className={`w-8 h-8 rounded-lg transition-all ${
                        newNotebook.color === color
                          ? "ring-2 ring-offset-2 ring-slate-400 dark:ring-slate-500 dark:ring-offset-slate-800 scale-110"
                          : ""
                      }`}
                      style={{ backgroundColor: color }}
                    />
                  ))}
                </div>
              </div>
            </div>
            <div className="p-4 border-t border-slate-100 dark:border-slate-700 flex justify-end gap-2">
              <button
                onClick={() => setShowCreateModal(false)}
                className="px-4 py-2 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleCreateNotebook}
                disabled={!newNotebook.name.trim()}
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50 flex items-center gap-2"
              >
                <Plus className="w-4 h-4" />
                创建
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Notebook Modal */}
      {showEditModal && editingNotebook && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 animate-in fade-in">
          <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl w-[400px] animate-in zoom-in-95">
            <div className="p-4 border-b border-slate-100 dark:border-slate-700 flex items-center justify-between">
              <h3 className="font-bold text-slate-900 dark:text-slate-100">
                Edit Notebook
              </h3>
              <button
                onClick={() => {
                  setShowEditModal(false);
                  setEditingNotebook(null);
                }}
                className="p-1 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg"
              >
                <X className="w-5 h-5 text-slate-500 dark:text-slate-400" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                  Name
                </label>
                <input
                  type="text"
                  value={editingNotebook.name}
                  onChange={(e) =>
                    setEditingNotebook((prev) =>
                      prev ? { ...prev, name: e.target.value } : null,
                    )
                  }
                  className="w-full px-4 py-2 border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none"
                />
              </div>
              <div>
                <label className="block text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                  Description
                </label>
                <textarea
                  value={editingNotebook.description}
                  onChange={(e) =>
                    setEditingNotebook((prev) =>
                      prev ? { ...prev, description: e.target.value } : null,
                    )
                  }
                  rows={3}
                  className="w-full px-4 py-2 border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none resize-none"
                />
              </div>
              <div>
                <label className="block text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                  Color
                </label>
                <div className="flex gap-2 flex-wrap">
                  {COLORS.map((color) => (
                    <button
                      key={color}
                      onClick={() =>
                        setEditingNotebook((prev) =>
                          prev ? { ...prev, color } : null,
                        )
                      }
                      className={`w-8 h-8 rounded-lg transition-all ${
                        editingNotebook.color === color
                          ? "ring-2 ring-offset-2 ring-slate-400 dark:ring-slate-500 dark:ring-offset-slate-800 scale-110"
                          : ""
                      }`}
                      style={{ backgroundColor: color }}
                    />
                  ))}
                </div>
              </div>
            </div>
            <div className="p-4 border-t border-slate-100 dark:border-slate-700 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowEditModal(false);
                  setEditingNotebook(null);
                }}
                className="px-4 py-2 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleUpdateNotebook}
                disabled={!editingNotebook.name.trim()}
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50 flex items-center gap-2"
              >
                <Check className="w-4 h-4" />
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 animate-in fade-in">
          <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl w-[360px] animate-in zoom-in-95">
            <div className="p-6 text-center">
              <div className="w-12 h-12 bg-red-100 dark:bg-red-900/40 rounded-full flex items-center justify-center mx-auto mb-4">
                <Trash2 className="w-6 h-6 text-red-600 dark:text-red-400" />
              </div>
              <h3 className="font-bold text-slate-900 dark:text-slate-100 mb-2">
                Delete Notebook?
              </h3>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                This action cannot be undone. All records in this notebook will
                be permanently deleted.
              </p>
            </div>
            <div className="p-4 border-t border-slate-100 dark:border-slate-700 flex justify-center gap-2">
              <button
                onClick={() => setShowDeleteConfirm(null)}
                className="px-4 py-2 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={() => handleDeleteNotebook(showDeleteConfirm)}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors flex items-center gap-2"
              >
                <Trash2 className="w-4 h-4" />
                删除
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Import Records Modal */}
      {showImportModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 animate-in fade-in">
          <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl w-[500px] max-h-[80vh] flex flex-col animate-in zoom-in-95">
            <div className="p-4 border-b border-slate-100 dark:border-slate-700 flex items-center justify-between shrink-0">
              <h3 className="font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                <Upload className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
                导入记录
              </h3>
              <button
                onClick={() => {
                  setShowImportModal(false);
                  setImportSourceNotebook("");
                  setImportSourceRecords([]);
                  setSelectedImportRecords(new Set());
                }}
                className="p-1 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg"
              >
                <X className="w-5 h-5 text-slate-500 dark:text-slate-400" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {/* Source Notebook Selection */}
              <div>
                <label className="block text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                  源笔记本
                </label>
                <select
                  value={importSourceNotebook}
                  onChange={(e) => loadImportSourceRecords(e.target.value)}
                  className="w-full px-4 py-2 border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none"
                >
                  <option value="">选择一个笔记本...</option>
                  {availableNotebooks.map((nb) => (
                    <option key={nb.id} value={nb.id}>
                      {nb.name}（{nb.record_count} 条记录）
                    </option>
                  ))}
                </select>
              </div>

              {/* Records Selection */}
              {importSourceNotebook && (
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                      选择记录（已选 {selectedImportRecords.size} 条）
                    </label>
                    <div className="flex gap-2">
                      <button
                        onClick={() =>
                          setSelectedImportRecords(
                            new Set(importSourceRecords.map((r) => r.id)),
                          )
                        }
                        className="text-xs text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300"
                      >
                        全选
                      </button>
                      <button
                        onClick={() => setSelectedImportRecords(new Set())}
                        className="text-xs text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300"
                      >
                        清空
                      </button>
                    </div>
                  </div>

                  {loadingImport ? (
                    <div className="py-8 text-center text-slate-400 dark:text-slate-500">
                      正在加载记录...
                    </div>
                  ) : importSourceRecords.length === 0 ? (
                    <div className="py-8 text-center text-slate-400 dark:text-slate-500">
                      此笔记本暂无记录
                    </div>
                  ) : (
                    <div className="space-y-2 max-h-64 overflow-y-auto">
                      {importSourceRecords.map((record) => (
                        <div
                          key={record.id}
                          onClick={() => toggleImportRecord(record.id)}
                          className={`p-3 rounded-xl cursor-pointer transition-all border ${
                            selectedImportRecords.has(record.id)
                              ? "bg-indigo-50 dark:bg-indigo-900/30 border-indigo-200 dark:border-indigo-700"
                              : "hover:bg-slate-50 dark:hover:bg-slate-700/50 border-slate-200 dark:border-slate-600"
                          }`}
                        >
                          <div className="flex items-center gap-3">
                            <div
                              className={`w-5 h-5 rounded border-2 flex items-center justify-center shrink-0 ${
                                selectedImportRecords.has(record.id)
                                  ? "bg-indigo-500 border-indigo-500 text-white"
                                  : "border-slate-300 dark:border-slate-500"
                              }`}
                            >
                              {selectedImportRecords.has(record.id) && (
                                <Check className="w-3 h-3" />
                              )}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <span
                                  className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${getRecordColor(record.type)}`}
                                >
                                  {getRecordLabel(record.type)}
                                </span>
                                <span className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">
                                  {record.title}
                                </span>
                              </div>
                              <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-1">
                                {record.user_query}
                              </p>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="p-4 border-t border-slate-100 dark:border-slate-700 flex justify-end gap-2 shrink-0">
              <button
                onClick={() => {
                  setShowImportModal(false);
                  setImportSourceNotebook("");
                  setImportSourceRecords([]);
                  setSelectedImportRecords(new Set());
                }}
                className="px-4 py-2 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleImportRecords}
                disabled={selectedImportRecords.size === 0 || loadingImport}
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Upload className="w-4 h-4" />
                导入{" "}
                {selectedImportRecords.size > 0 &&
                  `(${selectedImportRecords.size})`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
