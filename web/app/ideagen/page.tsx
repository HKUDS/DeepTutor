"use client";

import { useState, useEffect, useRef } from "react";
import {
  Lightbulb,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Loader2,
  Check,
  Save,
  Sparkles,
  Brain,
  Zap,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { apiUrl, wsUrl } from "@/lib/api";
import { processLatexContent } from "@/lib/latex";
import AddToNotebookModal from "@/components/AddToNotebookModal";
import { useGlobal } from "@/context/GlobalContext";

interface Notebook {
  id: string;
  name: string;
  description: string;
  record_count: number;
  color: string;
}

interface NotebookRecord {
  id: string;
  title: string;
  user_query: string;
  output: string;
  type: string;
}

interface ResearchIdea {
  id: string;
  knowledge_point: string;
  description: string;
  research_ideas: string[];
  statement: string;
  expanded: boolean;
  selected: boolean;
}

// Extended interface to include notebook info
interface SelectedRecord extends NotebookRecord {
  notebookId: string;
  notebookName: string;
}

export default function IdeaGenPage() {
  // Global state for persistence across page navigation
  const { ideaGenState, setIdeaGenState } = useGlobal();

  // Notebook selection - now supports multiple notebooks
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [expandedNotebooks, setExpandedNotebooks] = useState<Set<string>>(
    new Set(),
  );
  const [notebookRecordsMap, setNotebookRecordsMap] = useState<
    Map<string, NotebookRecord[]>
  >(new Map());
  const [selectedRecords, setSelectedRecords] = useState<
    Map<string, SelectedRecord>
  >(new Map()); // recordId -> record with notebook info
  const [loadingNotebooks, setLoadingNotebooks] = useState(true);
  const [loadingRecordsFor, setLoadingRecordsFor] = useState<Set<string>>(
    new Set(),
  );

  // User thoughts input
  const [userThoughts, setUserThoughts] = useState("");

  // Use global state for generation (persists across navigation)
  const isGenerating = ideaGenState.isGenerating;
  const generationStatus = ideaGenState.generationStatus;
  const generatedIdeas = ideaGenState.generatedIdeas;
  const progress = ideaGenState.progress;

  const setIsGenerating = (val: boolean) =>
    setIdeaGenState((prev) => ({ ...prev, isGenerating: val }));
  const setGenerationStatus = (val: string) =>
    setIdeaGenState((prev) => ({ ...prev, generationStatus: val }));
  const setGeneratedIdeas = (
    updater: ResearchIdea[] | ((prev: ResearchIdea[]) => ResearchIdea[]),
  ) => {
    setIdeaGenState((prev) => ({
      ...prev,
      generatedIdeas:
        typeof updater === "function" ? updater(prev.generatedIdeas) : updater,
    }));
  };
  const setProgress = (val: { current: number; total: number } | null) =>
    setIdeaGenState((prev) => ({ ...prev, progress: val }));

  // Save modal
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [ideaToSave, setIdeaToSave] = useState<ResearchIdea | null>(null);

  const wsRef = useRef<WebSocket | null>(null);

  // Load notebooks
  useEffect(() => {
    fetchNotebooks();
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  const fetchNotebooks = async () => {
    try {
      const res = await fetch(apiUrl("/api/v1/notebook/list"));
      const data = await res.json();
      const notebooksWithRecords = (data.notebooks || []).filter(
        (nb: Notebook) => nb.record_count > 0,
      );
      setNotebooks(notebooksWithRecords);
      setLoadingNotebooks(false);
    } catch (err) {
      console.error("Failed to fetch notebooks:", err);
      setLoadingNotebooks(false);
    }
  };

  const fetchNotebookRecords = async (notebookId: string) => {
    if (notebookRecordsMap.has(notebookId)) return; // Already fetched

    setLoadingRecordsFor((prev) => new Set([...prev, notebookId]));
    try {
      const res = await fetch(apiUrl(`/api/v1/notebook/${notebookId}`));
      const data = await res.json();
      setNotebookRecordsMap((prev) =>
        new Map(prev).set(notebookId, data.records || []),
      );
    } catch (err) {
      console.error("Failed to fetch notebook records:", err);
    } finally {
      setLoadingRecordsFor((prev) => {
        const newSet = new Set(prev);
        newSet.delete(notebookId);
        return newSet;
      });
    }
  };

  const toggleNotebookExpanded = (notebookId: string) => {
    const notebook = notebooks.find((nb) => nb.id === notebookId);
    if (!notebook) return;

    setExpandedNotebooks((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(notebookId)) {
        newSet.delete(notebookId);
      } else {
        newSet.add(notebookId);
        // Fetch records when expanding
        fetchNotebookRecords(notebookId);
      }
      return newSet;
    });
  };

  const toggleRecordSelection = (
    record: NotebookRecord,
    notebookId: string,
    notebookName: string,
  ) => {
    setSelectedRecords((prev) => {
      const newMap = new Map(prev);
      if (newMap.has(record.id)) {
        newMap.delete(record.id);
      } else {
        newMap.set(record.id, { ...record, notebookId, notebookName });
      }
      return newMap;
    });
  };

  const selectAllFromNotebook = (notebookId: string, notebookName: string) => {
    const records = notebookRecordsMap.get(notebookId) || [];
    setSelectedRecords((prev) => {
      const newMap = new Map(prev);
      records.forEach((r) =>
        newMap.set(r.id, { ...r, notebookId, notebookName }),
      );
      return newMap;
    });
  };

  const deselectAllFromNotebook = (notebookId: string) => {
    const records = notebookRecordsMap.get(notebookId) || [];
    const recordIds = new Set(records.map((r) => r.id));
    setSelectedRecords((prev) => {
      const newMap = new Map(prev);
      recordIds.forEach((id) => newMap.delete(id));
      return newMap;
    });
  };

  const clearAllSelections = () => {
    setSelectedRecords(new Map());
  };

  // Check if we can generate (either have records or user thoughts)
  const canGenerate =
    selectedRecords.size > 0 || userThoughts.trim().length > 0;

  const startGeneration = () => {
    if (!canGenerate) return;

    setIsGenerating(true);
    setGenerationStatus("Connecting...");
    setGeneratedIdeas([]);
    setProgress(null);

    const ws = new WebSocket(wsUrl("/api/v1/ideagen/generate"));
    wsRef.current = ws;

    ws.onopen = () => {
      setGenerationStatus("Initializing...");
      // Send records directly for cross-notebook support (can be empty if only user thoughts)
      const recordsArray = Array.from(selectedRecords.values()).map((r) => ({
        id: r.id,
        title: r.title,
        user_query: r.user_query,
        output: r.output,
        type: r.type,
      }));
      ws.send(
        JSON.stringify({
          records: recordsArray.length > 0 ? recordsArray : undefined,
          user_thoughts: userThoughts.trim() || undefined,
        }),
      );
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case "status":
          setGenerationStatus(data.message);
          // Check if this is the "complete" stage from backend
          if (data.stage === "complete") {
            setIsGenerating(false);
          }
          // Update progress from status data if available
          if (data.data?.index && data.data?.total) {
            setProgress({ current: data.data.index, total: data.data.total });
          }
          break;
        case "progress":
          if (data.data?.index && data.data?.total) {
            setProgress({ current: data.data.index, total: data.data.total });
          }
          break;
        case "idea":
          setGeneratedIdeas((prev) => [
            ...prev,
            { ...data.data, selected: false },
          ]);
          break;
        case "complete":
          setGenerationStatus("Completed!");
          setIsGenerating(false);
          break;
        case "error":
          setGenerationStatus(
            `Error: ${data.message || data.content || "Unknown error"}`,
          );
          setIsGenerating(false);
          break;
      }
    };

    ws.onerror = () => {
      setGenerationStatus("Connection Error");
      setIsGenerating(false);
    };

    ws.onclose = () => {
      wsRef.current = null;
    };
  };

  const toggleIdeaExpanded = (ideaId: string) => {
    setGeneratedIdeas((prev) =>
      prev.map((idea) =>
        idea.id === ideaId ? { ...idea, expanded: !idea.expanded } : idea,
      ),
    );
  };

  const toggleIdeaSelected = (ideaId: string) => {
    setGeneratedIdeas((prev) =>
      prev.map((idea) =>
        idea.id === ideaId ? { ...idea, selected: !idea.selected } : idea,
      ),
    );
  };

  const selectAllIdeas = () => {
    setGeneratedIdeas((prev) =>
      prev.map((idea) => ({ ...idea, selected: true })),
    );
  };

  const saveIdea = (idea: ResearchIdea) => {
    setIdeaToSave(idea);
    setShowSaveModal(true);
  };

  const saveSelectedIdeas = () => {
    const selected = generatedIdeas.filter((i) => i.selected);
    if (selected.length > 0) {
      // Merge all selected ideas
      const combinedIdea: ResearchIdea = {
        id: "combined",
        knowledge_point: "Collection of Research Ideas",
        description: `Research ideas containing ${selected.length} knowledge points`,
        research_ideas: selected.flatMap((i) => i.research_ideas),
        statement: selected.map((i) => i.statement).join("\n\n---\n\n"),
        expanded: false,
        selected: false,
      };
      setIdeaToSave(combinedIdea);
      setShowSaveModal(true);
    }
  };

  const getTypeColor = (type: string) => {
    switch (type) {
      case "solve":
        return "bg-blue-100 text-blue-700 border-blue-200";
      case "question":
        return "bg-purple-100 text-purple-700 border-purple-200";
      case "research":
        return "bg-emerald-100 text-emerald-700 border-emerald-200";
      case "co_writer":
        return "bg-amber-100 text-amber-700 border-amber-200";
      default:
        return "bg-slate-100 text-slate-700 border-slate-200";
    }
  };

  return (
    <div className="h-screen flex gap-4 p-4 animate-fade-in">
      {/* Left Panel: Source Selection */}
      <div className="flex-[1_1_33%] min-w-[350px] max-w-[500px] flex flex-col gap-4">
        {/* Multi-Notebook Selection */}
        <div className="flex-1 bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 flex flex-col overflow-hidden">
          <div className="p-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex justify-between items-center">
            <h2 className="font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <BookOpen className="w-5 h-5 text-amber-600 dark:text-amber-400" />
              选择来源（跨笔记本）
            </h2>
            {selectedRecords.size > 0 && (
              <button
                onClick={clearAllSelections}
                className="text-xs text-slate-500 dark:text-slate-400 hover:text-red-600 dark:hover:text-red-400"
              >
                清空（{selectedRecords.size}）
              </button>
            )}
          </div>

          <div className="flex-1 overflow-y-auto">
            {loadingNotebooks ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-5 h-5 animate-spin text-amber-600 dark:text-amber-400" />
              </div>
            ) : notebooks.length === 0 ? (
              <div className="p-4 text-center text-sm text-slate-400 dark:text-slate-500">
                未找到包含记录的笔记本
              </div>
            ) : (
              <div className="divide-y divide-slate-100 dark:divide-slate-700">
                {notebooks.map((notebook) => {
                  const isExpanded = expandedNotebooks.has(notebook.id);
                  const records = notebookRecordsMap.get(notebook.id) || [];
                  const isLoading = loadingRecordsFor.has(notebook.id);
                  const selectedFromThis = records.filter((r) =>
                    selectedRecords.has(r.id),
                  ).length;

                  return (
                    <div key={notebook.id}>
                      {/* Notebook Header */}
                      <div
                        className="p-3 flex items-center gap-2 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
                        onClick={() => toggleNotebookExpanded(notebook.id)}
                      >
                        {isExpanded ? (
                          <ChevronDown className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                        ) : (
                          <ChevronRight className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                        )}
                        <div
                          className="w-3 h-3 rounded-full"
                          style={{
                            backgroundColor: notebook.color || "#94a3b8",
                          }}
                        />
                        <span className="flex-1 text-sm font-medium text-slate-700 dark:text-slate-200 truncate">
                          {notebook.name}
                        </span>
                        <span className="text-xs text-slate-400 dark:text-slate-500">
                          {selectedFromThis > 0 && (
                            <span className="text-amber-600 dark:text-amber-400 font-medium">
                              {selectedFromThis}/
                            </span>
                          )}
                          {notebook.record_count}
                        </span>
                      </div>

                      {/* Records List */}
                      {isExpanded && (
                        <div className="pl-6 pr-2 pb-2 bg-slate-50/50 dark:bg-slate-800/50">
                          {isLoading ? (
                            <div className="flex items-center justify-center py-4">
                              <Loader2 className="w-4 h-4 animate-spin text-amber-600 dark:text-amber-400" />
                            </div>
                          ) : records.length === 0 ? (
                            <div className="py-2 text-xs text-slate-400 dark:text-slate-500 text-center">
                              暂无记录
                            </div>
                          ) : (
                            <>
                              <div className="flex gap-2 mb-2">
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    selectAllFromNotebook(
                                      notebook.id,
                                      notebook.name,
                                    );
                                  }}
                                  className="text-xs text-amber-600 dark:text-amber-400 hover:text-amber-700 dark:hover:text-amber-300"
                                >
                                  全选
                                </button>
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    deselectAllFromNotebook(notebook.id);
                                  }}
                                  className="text-xs text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300"
                                >
                                  取消选择
                                </button>
                              </div>
                              <div className="space-y-1">
                                {records.map((record) => (
                                  <div
                                    key={record.id}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      toggleRecordSelection(
                                        record,
                                        notebook.id,
                                        notebook.name,
                                      );
                                    }}
                                    className={`p-2 rounded-lg cursor-pointer transition-all border ${
                                      selectedRecords.has(record.id)
                                        ? "bg-amber-50 dark:bg-amber-900/30 border-amber-200 dark:border-amber-700"
                                        : "hover:bg-white dark:hover:bg-slate-700 border-transparent hover:border-slate-200 dark:hover:border-slate-600"
                                    }`}
                                  >
                                    <div className="flex items-center gap-2">
                                      <div
                                        className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                                          selectedRecords.has(record.id)
                                            ? "bg-amber-500 border-amber-500 text-white"
                                            : "border-slate-300 dark:border-slate-500"
                                        }`}
                                      >
                                        {selectedRecords.has(record.id) && (
                                          <Check className="w-2.5 h-2.5" />
                                        )}
                                      </div>
                                      <div className="flex-1 min-w-0">
                                        <span
                                          className={`text-[10px] font-bold uppercase px-1 py-0.5 rounded ${getTypeColor(record.type)}`}
                                        >
                                          {record.type}
                                        </span>
                                        <span className="text-xs text-slate-700 dark:text-slate-200 ml-2 truncate">
                                          {record.title}
                                        </span>
                                      </div>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* User Thoughts Input */}
          <div className="p-3 border-t border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50">
            <label className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider block mb-2">
              你的想法 {selectedRecords.size > 0 ? "（可选）" : "（必填）"}
            </label>
            <textarea
              value={userThoughts}
              onChange={(e) => setUserThoughts(e.target.value)}
              placeholder={
                selectedRecords.size > 0
                  ? "基于这些材料描述你的想法或研究方向..."
                  : "描述你的研究主题或想法（无需选择笔记本）..."
              }
              className="w-full px-3 py-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500 resize-none focus:ring-2 focus:ring-amber-500/20 focus:border-amber-500 outline-none"
              rows={3}
            />
            {selectedRecords.size === 0 && (
              <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                💡
                你可以仅用文字描述生成想法，也可以选择上方笔记记录获得更丰富的上下文。
              </p>
            )}
          </div>

          {/* Generate Button */}
          <div className="p-3 border-t border-slate-100 dark:border-slate-700">
            <button
              onClick={startGeneration}
              disabled={isGenerating || !canGenerate}
              className="w-full px-4 py-2.5 bg-gradient-to-r from-amber-500 to-orange-500 text-white rounded-xl hover:from-amber-600 hover:to-orange-600 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 font-medium shadow-md shadow-amber-500/20"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  生成中...
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4" />
                  {selectedRecords.size > 0
                    ? `生成想法（已选 ${selectedRecords.size} 条）`
                    : "生成想法（仅文本）"}
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Right Panel: Generated Ideas */}
      <div className="flex-[2_1_67%] min-w-0 flex flex-col bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden">
        {/* Header */}
        <div className="p-4 border-b border-slate-100 dark:border-slate-700 bg-gradient-to-r from-amber-50 to-orange-50 dark:from-amber-900/20 dark:to-orange-900/20 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-amber-100 dark:bg-amber-900/40 rounded-xl">
              <Lightbulb className="w-5 h-5 text-amber-600 dark:text-amber-400" />
            </div>
            <div>
              <h1 className="font-bold text-slate-900 dark:text-slate-100">
                IdeaGen
              </h1>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                从你的笔记中发现研究灵感
              </p>
            </div>
          </div>

          {generatedIdeas.length > 0 && (
            <div className="flex items-center gap-2">
              <button
                onClick={selectAllIdeas}
                className="px-3 py-1.5 text-xs text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/40 rounded-lg transition-colors"
              >
                全选
              </button>
              <button
                onClick={saveSelectedIdeas}
                disabled={!generatedIdeas.some((i) => i.selected)}
                className="px-3 py-1.5 text-xs bg-amber-600 text-white rounded-lg hover:bg-amber-700 transition-colors disabled:opacity-50 flex items-center gap-1"
              >
                <Save className="w-3 h-3" />
                保存所选
              </button>
            </div>
          )}
        </div>

        {/* Status Bar */}
        {(isGenerating || generationStatus) && (
          <div className="px-4 py-2 bg-amber-50 dark:bg-amber-900/30 border-b border-amber-100 dark:border-amber-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              {isGenerating && (
                <Loader2 className="w-4 h-4 animate-spin text-amber-600 dark:text-amber-400" />
              )}
              <span className="text-sm text-amber-700 dark:text-amber-300">
                {generationStatus}
              </span>
            </div>
            {progress && (
              <span className="text-xs text-amber-600 dark:text-amber-400">
                {progress.current} / {progress.total}
              </span>
            )}
          </div>
        )}

        {/* Ideas List */}
        <div className="flex-1 overflow-y-auto p-4">
          {generatedIdeas.length === 0 && !isGenerating ? (
            <div className="h-full flex flex-col items-center justify-center text-slate-400 dark:text-slate-500">
              <Brain className="w-16 h-16 text-slate-200 dark:text-slate-600 mb-4" />
              <p className="text-slate-500 dark:text-slate-400 text-center max-w-md">
                选择笔记记录或描述你的研究主题
                <br />
                <span className="text-xs text-slate-400 dark:text-slate-500 mt-2 block">
                  你可以选择笔记记录作为上下文，也可以直接在文本框描述研究方向
                </span>
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {generatedIdeas.map((idea) => (
                <div
                  key={idea.id}
                  className={`rounded-2xl border transition-all ${
                    idea.selected
                      ? "bg-amber-50 dark:bg-amber-900/30 border-amber-200 dark:border-amber-700 shadow-md shadow-amber-100 dark:shadow-amber-900/20"
                      : "bg-white dark:bg-slate-700 border-slate-200 dark:border-slate-600 hover:border-slate-300 dark:hover:border-slate-500"
                  }`}
                >
                  {/* Idea Header */}
                  <div className="p-4 flex items-start gap-3">
                    {/* Selection Checkbox */}
                    <button
                      onClick={() => toggleIdeaSelected(idea.id)}
                      className={`w-6 h-6 rounded-full border-2 flex items-center justify-center shrink-0 transition-all ${
                        idea.selected
                          ? "bg-amber-500 border-amber-500 text-white"
                          : "border-slate-300 dark:border-slate-500 hover:border-amber-400 dark:hover:border-amber-500"
                      }`}
                    >
                      {idea.selected && <Check className="w-4 h-4" />}
                    </button>

                    {/* Main Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <h3 className="font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                          <Zap className="w-4 h-4 text-amber-500 dark:text-amber-400" />
                          {idea.knowledge_point}
                        </h3>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-slate-400 dark:text-slate-500 bg-slate-100 dark:bg-slate-600 px-2 py-0.5 rounded-full">
                            {idea.research_ideas.length} 个想法
                          </span>
                          <button
                            onClick={() => saveIdea(idea)}
                            className="p-1.5 text-slate-400 dark:text-slate-500 hover:text-amber-600 dark:hover:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/40 rounded-lg transition-colors"
                            title="保存到笔记本"
                          >
                            <Save className="w-4 h-4" />
                          </button>
                        </div>
                      </div>

                      <p className="text-sm text-slate-500 dark:text-slate-400 mt-1 line-clamp-2">
                        {idea.description}
                      </p>

                      {/* Research Ideas Preview */}
                      <div className="flex flex-wrap gap-2 mt-3">
                        {idea.research_ideas.slice(0, 3).map((ri, idx) => (
                          <span
                            key={idx}
                            className="text-xs bg-slate-100 dark:bg-slate-600 text-slate-600 dark:text-slate-300 px-2 py-1 rounded-lg line-clamp-1 max-w-[200px]"
                          >
                            {ri.substring(0, 50)}...
                          </span>
                        ))}
                        {idea.research_ideas.length > 3 && (
                          <span className="text-xs text-slate-400 dark:text-slate-500">
                            +{idea.research_ideas.length - 3} 个更多
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Expand Button */}
                    <button
                      onClick={() => toggleIdeaExpanded(idea.id)}
                      className="p-1.5 text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-600 rounded-lg transition-colors"
                    >
                      {idea.expanded ? (
                        <ChevronDown className="w-5 h-5" />
                      ) : (
                        <ChevronRight className="w-5 h-5" />
                      )}
                    </button>
                  </div>

                  {/* Expanded Content */}
                  {idea.expanded && (
                    <div className="px-4 pb-4 pt-0 border-t border-slate-100 dark:border-slate-600 mt-0">
                      <div className="mt-4 prose prose-sm prose-slate dark:prose-invert max-w-none">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm, remarkMath]}
                          rehypePlugins={[rehypeKatex]}
                        >
                          {processLatexContent(idea.statement)}
                        </ReactMarkdown>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Save Modal */}
      {ideaToSave && (
        <AddToNotebookModal
          isOpen={showSaveModal}
          onClose={() => {
            setShowSaveModal(false);
            setIdeaToSave(null);
          }}
          recordType="research"
          title={`Research Idea: ${ideaToSave.knowledge_point}`}
          userQuery={ideaToSave.description}
          output={ideaToSave.statement}
          metadata={{
            ideas_count: ideaToSave.research_ideas.length,
            source: "ideagen",
          }}
        />
      )}
    </div>
  );
}
