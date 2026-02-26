"use client";

import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  PenTool,
  CheckCircle2,
  AlertCircle,
  Loader2,
  BookOpen,
  BrainCircuit,
  Sparkles,
  RefreshCw,
  FileText,
  Book,
  Upload,
  Database,
  FileQuestion,
  Activity,
  Zap,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { useGlobal } from "@/context/GlobalContext";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { apiUrl } from "@/lib/api";
import { processLatexContent } from "@/lib/latex";
import AddToNotebookModal from "@/components/AddToNotebookModal";
import { QuestionDashboard } from "@/components/question";
import { useQuestionReducer } from "@/hooks/useQuestionReducer";

interface KnowledgeBase {
  name: string;
  display_name?: string;
  is_default?: boolean;
  owner?: {
    type?: string;
    notebook_id?: string;
    notebook_name?: string;
  } | null;
}

function QuestionPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const entryNotebookId = (searchParams.get("notebook_id") || "").trim();
  const entryNotebookName = (searchParams.get("notebook_name") || "").trim();

  const {
    questionState,
    setQuestionState,
    startQuestionGen,
    startMimicQuestionGen,
    resetQuestionGen,
  } = useGlobal();

  // Dashboard state for parallel generation
  const [dashboardState] = useQuestionReducer();
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

  // Tab state: "questions" shows the quiz, "process" shows the dashboard
  const [activeTab, setActiveTab] = useState<"questions" | "process">(
    "questions",
  );

  // Local interaction state
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);

  // Answering state
  const [activeIdx, setActiveIdx] = useState(0);
  const [userAnswers, setUserAnswers] = useState<Record<number, string>>({});
  const [submittedMap, setSubmittedMap] = useState<Record<number, boolean>>({});
  const [showValidation, setShowValidation] = useState(false);

  // Notebook modal state
  const [showNotebookModal, setShowNotebookModal] = useState(false);

  // Check if generation is in progress
  const isGenerating =
    questionState.step === "generating" || questionState.step === "result";
  const isConfigMode = questionState.step === "config";

  // Fetch KBs on mount only
  useEffect(() => {
    fetch(apiUrl("/api/v1/knowledge/list"))
      .then((res) => res.json())
      .then((data) => {
        const kbList: KnowledgeBase[] = Array.isArray(data) ? data : [];
        setKbs(kbList);

        if (kbList.length === 0) {
          setQuestionState((prev) => ({ ...prev, selectedKb: "" }));
          return;
        }

        const notebookSourceKb =
          (entryNotebookId &&
            (kbList.find(
              (kb) =>
                kb.owner?.type === "notebook_sources" &&
                kb.owner?.notebook_id === entryNotebookId,
            )?.name ||
              kbList.find(
                (kb) => kb.name === `notebook_${entryNotebookId}_sources`,
              )?.name)) ||
          "";
        const defaultKb =
          kbList.find((kb) => kb.is_default)?.name || kbList[0]?.name || "";

        setQuestionState((prev) => {
          if (notebookSourceKb) {
            if (prev.selectedKb === notebookSourceKb) return prev;
            return { ...prev, selectedKb: notebookSourceKb };
          }
          if (kbList.some((kb) => kb.name === prev.selectedKb)) {
            return prev;
          }
          return { ...prev, selectedKb: defaultKb };
        });
      })
      .catch((err) => console.error("Failed to fetch KBs:", err));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entryNotebookId]);

  const handleStart = () => {
    if (questionState.mode === "knowledge") {
      startQuestionGen(
        questionState.topic,
        questionState.difficulty,
        questionState.type,
        questionState.count,
        questionState.selectedKb,
      );
    } else {
      // Mimic mode - use PDF file or pre-parsed directory
      startMimicQuestionGen(
        questionState.uploadedFile,
        questionState.paperPath,
        questionState.selectedKb,
        questionState.count > 0 ? questionState.count : undefined,
      );
    }
    // Reset interaction state
    setUserAnswers({});
    setSubmittedMap({});
    setActiveIdx(0);
    setShowValidation(false);
    // Switch to process tab when generating
    setActiveTab("process");
  };

  const handleAnswer = (val: string) => {
    if (submittedMap[activeIdx]) return;
    setUserAnswers((prev) => ({ ...prev, [activeIdx]: val }));
  };

  const handleSubmit = () => {
    setSubmittedMap((prev) => ({ ...prev, [activeIdx]: true }));
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] || null;
    if (file && file.type !== "application/pdf") {
      alert("请上传 PDF 试卷文件");
      return;
    }
    setQuestionState((prev) => ({
      ...prev,
      uploadedFile: file,
      paperPath: file ? "" : prev.paperPath,
    }));
  };

  const currentQuestion = questionState.results[activeIdx];
  const totalQuestions = questionState.results.length;
  const extendedCount = questionState.results.filter(
    (r: any) => r.extended,
  ).length;

  // Auto-switch to questions tab when generation completes
  useEffect(() => {
    if (questionState.step === "result" && totalQuestions > 0) {
      setActiveTab("questions");
    }
  }, [questionState.step, totalQuestions]);

  const hasEntryNotebook = entryNotebookId.length > 0;
  const handleBackToNotebook = () => {
    if (!hasEntryNotebook) return;
    router.push(`/notebooks/${encodeURIComponent(entryNotebookId)}`);
  };

  return (
    <div className="h-screen flex flex-col animate-fade-in overflow-hidden p-4">
      {/* Main Panel */}
      <div className="flex-1 flex flex-col bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden min-h-0">
        {/* Header Row */}
        <div className="p-4 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex justify-between items-center backdrop-blur-sm shrink-0">
          <div className="flex items-center gap-4">
            {hasEntryNotebook && (
              <button
                onClick={handleBackToNotebook}
                className="p-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg shadow-sm hover:bg-slate-50 dark:hover:bg-slate-700 transition-all text-slate-500 dark:text-slate-300"
                title={
                  entryNotebookName
                    ? `返回笔记本：${entryNotebookName}`
                    : "返回来源笔记本"
                }
              >
                <ArrowLeft className="w-4 h-4" />
              </button>
            )}
            <div className="flex items-center gap-2 text-slate-700 dark:text-slate-200 font-semibold">
              <PenTool className="w-5 h-5 text-purple-600 dark:text-purple-400" />
              题目生成器
            </div>

            {/* Mode Switching - disabled when generating */}
            <div
              className={`flex bg-slate-100 dark:bg-slate-700 p-1 rounded-lg border border-slate-200 dark:border-slate-600 ${isGenerating ? "opacity-50" : ""}`}
            >
              <button
                onClick={() =>
                  !isGenerating &&
                  setQuestionState((prev) => ({
                    ...prev,
                    mode: "knowledge",
                  }))
                }
                disabled={isGenerating}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-all ${
                  questionState.mode === "knowledge"
                    ? "bg-white dark:bg-slate-600 text-purple-700 dark:text-purple-400 shadow-sm"
                    : isGenerating
                      ? "text-slate-400 dark:text-slate-500 cursor-not-allowed"
                      : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                }`}
              >
                <BrainCircuit className="w-4 h-4" />
                自定义
              </button>
              <button
                onClick={() =>
                  !isGenerating &&
                  setQuestionState((prev) => ({ ...prev, mode: "mimic" }))
                }
                disabled={isGenerating}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-all ${
                  questionState.mode === "mimic"
                    ? "bg-white dark:bg-slate-600 text-purple-700 dark:text-purple-400 shadow-sm"
                    : isGenerating
                      ? "text-slate-400 dark:text-slate-500 cursor-not-allowed"
                      : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                }`}
              >
                <FileText className="w-4 h-4" />
                仿真试卷
              </button>
            </div>

            {/* Separator */}
            <div className="h-6 w-px bg-slate-200 dark:bg-slate-600" />

            {/* Questions/Process Tabs */}
            <div className="flex bg-slate-100 dark:bg-slate-700 p-1 rounded-lg border border-slate-200 dark:border-slate-600">
              <button
                onClick={() => !isConfigMode && setActiveTab("questions")}
                disabled={isConfigMode}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-all ${
                  !isConfigMode && activeTab === "questions"
                    ? "bg-white dark:bg-slate-600 text-purple-700 dark:text-purple-400 shadow-sm"
                    : isConfigMode
                      ? "text-slate-300 dark:text-slate-500 cursor-not-allowed"
                      : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                }`}
              >
                <FileQuestion className="w-4 h-4" />
                题目
                {totalQuestions > 0 && (
                  <span className="px-1.5 py-0.5 bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300 text-xs rounded-full">
                    {totalQuestions}
                  </span>
                )}
              </button>
              <button
                onClick={() => !isConfigMode && setActiveTab("process")}
                disabled={isConfigMode}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-all ${
                  !isConfigMode && activeTab === "process"
                    ? "bg-white dark:bg-slate-600 text-purple-700 dark:text-purple-400 shadow-sm"
                    : isConfigMode
                      ? "text-slate-300 dark:text-slate-500 cursor-not-allowed"
                      : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                }`}
              >
                <Activity className="w-4 h-4" />
                过程
                {questionState.step === "generating" && (
                  <Loader2 className="w-3 h-3 animate-spin text-purple-500 dark:text-purple-400" />
                )}
              </button>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {/* Knowledge Base Selection */}
            <div className="flex items-center gap-2">
              <Database className="w-4 h-4 text-slate-400 dark:text-slate-500" />
              <select
                value={questionState.selectedKb}
                onChange={(e) =>
                  setQuestionState((prev) => ({
                    ...prev,
                    selectedKb: e.target.value,
                  }))
                }
                disabled={isGenerating}
                className={`text-sm bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-1.5 outline-none focus:border-purple-400 focus:ring-2 focus:ring-purple-500/20 dark:text-slate-200 ${isGenerating ? "opacity-50 cursor-not-allowed" : ""}`}
              >
                {kbs.map((kb) => {
                  const label =
                    kb.display_name ||
                    (kb.owner?.type === "notebook_sources"
                      ? `${kb.owner?.notebook_name || "笔记本"} · 来源库`
                      : kb.name);
                  return (
                    <option key={kb.name} value={kb.name}>
                      {label}
                    </option>
                  );
                })}
              </select>
            </div>

            {!isConfigMode && (
              <button
                onClick={resetQuestionGen}
                className="text-sm flex items-center gap-1.5 text-slate-500 dark:text-slate-400 hover:text-purple-600 dark:hover:text-purple-400 transition-colors px-3 py-1.5 hover:bg-purple-50 dark:hover:bg-purple-900/30 rounded-lg border border-slate-200 dark:border-slate-600"
              >
                <RefreshCw className="w-4 h-4" />
                新建
              </button>
            )}
          </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto bg-slate-50/30 dark:bg-slate-900/30 min-h-0">
          {/* MODE: CONFIG - Show config form */}
          {isConfigMode && (
            <div className="p-6">
              <div className="max-w-2xl mx-auto space-y-8 animate-in fade-in slide-in-from-bottom-4">
                {/* Mode Info Banner */}
                <div
                  className={`p-4 rounded-xl border ${
                    questionState.mode === "knowledge"
                      ? "bg-purple-50 dark:bg-purple-900/30 border-purple-200 dark:border-purple-800"
                      : "bg-blue-50 dark:bg-blue-900/30 border-blue-200 dark:border-blue-800"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    {questionState.mode === "knowledge" ? (
                      <BrainCircuit className="w-6 h-6 text-purple-600 dark:text-purple-400" />
                    ) : (
                      <FileText className="w-6 h-6 text-blue-600 dark:text-blue-400" />
                    )}
                    <div>
                      <h3
                        className={`font-semibold ${
                          questionState.mode === "knowledge"
                            ? "text-purple-800 dark:text-purple-300"
                            : "text-blue-800 dark:text-blue-300"
                        }`}
                      >
                        {questionState.mode === "knowledge"
                          ? "自定义模式"
                          : "仿真试卷模式"}
                      </h3>
                      <p className="text-sm text-slate-600 dark:text-slate-400">
                        {questionState.mode === "knowledge"
                          ? "基于知识库内容生成题目"
                          : "基于试卷生成相似题目"}
                      </p>
                    </div>
                  </div>
                </div>

                {/* Knowledge Base Mode Config */}
                {questionState.mode === "knowledge" && (
                  <>
                    <div className="grid grid-cols-2 gap-6">
                      <div className="space-y-2">
                        <label className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                          题目数量
                        </label>
                        <div className="flex items-center gap-4">
                          <input
                            type="range"
                            min="1"
                            max="10"
                            step="1"
                            value={Math.min(questionState.count, 10)}
                            onChange={(e) =>
                              setQuestionState((prev) => ({
                                ...prev,
                                count: parseInt(e.target.value),
                              }))
                            }
                            className="flex-1 accent-purple-600 h-2 bg-slate-200 dark:bg-slate-600 rounded-lg appearance-none cursor-pointer"
                          />
                          <input
                            type="number"
                            min="1"
                            max="50"
                            value={questionState.count}
                            onChange={(e) => {
                              const val = parseInt(e.target.value) || 1;
                              setQuestionState((prev) => ({
                                ...prev,
                                count: Math.max(1, Math.min(50, val)),
                              }));
                            }}
                            className="w-16 text-center font-bold text-purple-700 dark:text-purple-300 bg-purple-50 dark:bg-purple-900/30 py-1 rounded-md border border-purple-100 dark:border-purple-800 outline-none focus:border-purple-400 focus:ring-2 focus:ring-purple-500/20"
                          />
                        </div>
                        <p className="text-[10px] text-slate-400 dark:text-slate-500">
                          可用滑块（1-10）或直接输入（1-50）
                        </p>
                      </div>
                    </div>

                    <div className="space-y-2">
                      <label className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                        知识点 / 主题
                      </label>
                      <input
                        type="text"
                        value={questionState.topic}
                        onChange={(e) =>
                          setQuestionState((prev) => ({
                            ...prev,
                            topic: e.target.value,
                          }))
                        }
                        placeholder={entryNotebookName || "例如：梯度下降优化"}
                        className="w-full p-4 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-xl outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/10 transition-all text-lg dark:text-slate-200 dark:placeholder:text-slate-500"
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-6">
                      <div className="space-y-2">
                        <label className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                          难度
                        </label>
                        <div className="flex bg-slate-50 dark:bg-slate-700 p-1 rounded-xl border border-slate-200 dark:border-slate-600">
                          {["easy", "medium", "hard"].map((lvl) => (
                            <button
                              key={lvl}
                              onClick={() =>
                                setQuestionState((prev) => ({
                                  ...prev,
                                  difficulty: lvl,
                                }))
                              }
                              className={`flex-1 py-2 rounded-lg text-sm font-medium capitalize transition-all ${
                                questionState.difficulty === lvl
                                  ? "bg-white dark:bg-slate-600 text-purple-700 dark:text-purple-400 shadow-sm"
                                  : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                              }`}
                            >
                              {lvl === "easy"
                                ? "简单"
                                : lvl === "medium"
                                  ? "中等"
                                  : "困难"}
                            </button>
                          ))}
                        </div>
                      </div>

                      <div className="space-y-2">
                        <label className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                          题型
                        </label>
                        <div className="flex bg-slate-50 dark:bg-slate-700 p-1 rounded-xl border border-slate-200 dark:border-slate-600">
                          {[
                            { id: "choice", label: "选择题" },
                            { id: "written", label: "解答题" },
                          ].map((t) => (
                            <button
                              key={t.id}
                              onClick={() =>
                                setQuestionState((prev) => ({
                                  ...prev,
                                  type: t.id,
                                }))
                              }
                              className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all ${
                                questionState.type === t.id
                                  ? "bg-white dark:bg-slate-600 text-purple-700 dark:text-purple-400 shadow-sm"
                                  : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                              }`}
                            >
                              {t.label}
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>
                  </>
                )}

                {/* Mimic Mode Config */}
                {questionState.mode === "mimic" && (
                  <div className="space-y-6">
                    {/* PDF Upload Section */}
                    <div className="space-y-2">
                      <label className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                        上传试卷（PDF）
                      </label>
                      <div className="relative">
                        <input
                          type="file"
                          accept=".pdf"
                          onChange={handleFileUpload}
                          className="hidden"
                          id="pdf-upload"
                        />
                        <label
                          htmlFor="pdf-upload"
                          className="flex items-center justify-center gap-3 w-full p-6 border-2 border-dashed border-slate-300 dark:border-slate-600 rounded-xl cursor-pointer hover:border-purple-400 dark:hover:border-purple-500 hover:bg-purple-50/50 dark:hover:bg-purple-900/20 transition-all"
                        >
                          {questionState.uploadedFile ? (
                            <div className="flex items-center gap-3 text-purple-700 dark:text-purple-400">
                              <FileText className="w-8 h-8" />
                              <div>
                                <p className="font-medium">
                                  {questionState.uploadedFile.name}
                                </p>
                                <p className="text-xs text-slate-500 dark:text-slate-400">
                                  {(
                                    questionState.uploadedFile.size /
                                    1024 /
                                    1024
                                  ).toFixed(2)}{" "}
                                  MB - Click to change
                                </p>
                              </div>
                            </div>
                          ) : (
                            <div className="text-center text-slate-500 dark:text-slate-400">
                              <Upload className="w-8 h-8 mx-auto mb-2 text-slate-400 dark:text-slate-500" />
                              <p className="font-medium">
                                Click to upload PDF exam paper
                              </p>
                              <p className="text-xs">
                                The system will automatically parse and generate
                                questions
                              </p>
                            </div>
                          )}
                        </label>
                      </div>
                    </div>

                    {/* Divider */}
                    <div className="flex items-center gap-3">
                      <div className="flex-1 h-px bg-slate-200 dark:bg-slate-600"></div>
                      <span className="text-xs text-slate-400 dark:text-slate-500 font-medium">
                        或
                      </span>
                      <div className="flex-1 h-px bg-slate-200 dark:bg-slate-600"></div>
                    </div>

                    {/* Pre-parsed Directory (Optional) */}
                    <div className="space-y-2">
                      <label className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                        预解析目录（可选）
                      </label>
                      <input
                        type="text"
                        value={questionState.paperPath}
                        onChange={(e) =>
                          setQuestionState((prev) => ({
                            ...prev,
                            paperPath: e.target.value,
                            uploadedFile: null,
                          }))
                        }
                        placeholder={entryNotebookName || "例如：2211asm1"}
                        className="w-full p-3 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-xl outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/10 transition-all dark:text-slate-200 dark:placeholder:text-slate-500"
                      />
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        或输入已解析的试卷目录名
                      </p>
                    </div>

                    <div className="space-y-2">
                      <label className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                        最大题目数（可选）
                      </label>
                      <div className="flex items-center gap-4">
                        <input
                          type="number"
                          min="1"
                          max="20"
                          placeholder="全部"
                          value={questionState.count || ""}
                          onChange={(e) => {
                            const val = e.target.value
                              ? parseInt(e.target.value)
                              : 0;
                            setQuestionState((prev) => ({
                              ...prev,
                              count: val > 0 ? Math.min(20, val) : 0,
                            }));
                          }}
                          className="w-24 p-2 text-center bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/10 dark:text-slate-200"
                        />
                        <span className="text-sm text-slate-500 dark:text-slate-400">
                          留空则生成该试卷中的全部题目
                        </span>
                      </div>
                    </div>

                    <div className="p-4 bg-gradient-to-r from-purple-50 to-blue-50 dark:from-purple-900/30 dark:to-blue-900/30 border border-purple-200 dark:border-purple-800 rounded-xl text-sm text-slate-700 dark:text-slate-300">
                      <p className="font-medium mb-2 text-purple-800 dark:text-purple-300">
                        ✨ 仿真试卷模式说明
                      </p>
                      <ol className="text-xs space-y-1 list-decimal list-inside text-slate-600 dark:text-slate-400">
                        <li>上传 PDF 试卷文件</li>
                        <li>选择相关知识库</li>
                        <li>系统将自动：解析 PDF → 提取题目 → 生成相似新题</li>
                        <li>进度将实时显示</li>
                      </ol>
                    </div>
                  </div>
                )}

                <button
                  onClick={handleStart}
                  disabled={
                    questionState.mode === "knowledge"
                      ? !questionState.topic.trim()
                      : !questionState.uploadedFile &&
                        !questionState.paperPath.trim()
                  }
                  className="w-full py-4 bg-purple-600 text-white rounded-xl font-bold text-lg shadow-lg shadow-purple-500/30 hover:bg-purple-700 hover:shadow-purple-500/50 active:scale-[0.98] transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                >
                  <Sparkles className="w-5 h-5" />
                  生成题目
                </button>
              </div>
            </div>
          )}

          {/* QUESTIONS TAB */}
          {!isConfigMode && activeTab === "questions" && (
            <div className="p-6 h-full">
              {/* Question Number Selector */}
              {totalQuestions > 0 && (
                <div className="mb-6 bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                      题目
                    </span>
                    <span className="text-sm text-slate-500 dark:text-slate-400">
                      已完成 {totalQuestions} / {questionState.count}
                      {extendedCount > 0 && (
                        <span className="ml-2 text-amber-600 dark:text-amber-400">
                          （拓展 {extendedCount}）
                        </span>
                      )}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {questionState.results.map((result: any, idx: number) => (
                      <button
                        key={idx}
                        onClick={() => setActiveIdx(idx)}
                        className={`w-10 h-10 rounded-full flex items-center justify-center font-semibold text-sm border-2 transition-all ${
                          activeIdx === idx
                            ? "bg-purple-600 text-white border-purple-600 shadow-lg shadow-purple-500/30 scale-110"
                            : result.extended
                              ? "bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 border-amber-300 dark:border-amber-600 hover:border-amber-400 dark:hover:border-amber-500 hover:bg-amber-100 dark:hover:bg-amber-900/50"
                              : submittedMap[idx]
                                ? "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 border-emerald-300 dark:border-emerald-600 hover:border-emerald-400 dark:hover:border-emerald-500"
                                : "bg-white dark:bg-slate-700 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-600 hover:border-purple-300 dark:hover:border-purple-500 hover:bg-purple-50 dark:hover:bg-purple-900/30"
                        }`}
                      >
                        {submittedMap[idx] && activeIdx !== idx ? (
                          <CheckCircle2 className="w-5 h-5" />
                        ) : result.extended && activeIdx !== idx ? (
                          <Zap className="w-4 h-4" />
                        ) : (
                          idx + 1
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* No Questions Yet */}
              {totalQuestions === 0 && questionState.step === "generating" && (
                <div className="h-full flex flex-col items-center justify-center text-slate-400 dark:text-slate-500 gap-4">
                  <div className="relative">
                    <div className="w-16 h-16 border-4 border-purple-100 dark:border-purple-900 border-t-purple-500 rounded-full animate-spin"></div>
                    <div className="absolute inset-0 flex items-center justify-center">
                      <BrainCircuit className="w-6 h-6 text-purple-500 dark:text-purple-400" />
                    </div>
                  </div>
                  <p className="font-medium text-slate-600 dark:text-slate-300">
                    正在生成题目...
                  </p>
                  <p className="text-sm text-center max-w-xs">
                    切换到「过程」标签页查看详细进度
                  </p>
                </div>
              )}

              {/* Question Display - Left-Right Layout */}
              {totalQuestions > 0 && currentQuestion && (
                <div className="flex-1 flex gap-6 animate-in fade-in slide-in-from-right-4">
                  {/* Left Side: Question Area */}
                  <div className="flex-1 bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-sm overflow-hidden flex flex-col">
                    {/* Question Header */}
                    <div className="px-6 py-4 border-b border-slate-100 dark:border-slate-700 bg-slate-50/30 dark:bg-slate-800/30">
                      <div className="flex items-center gap-2">
                        <span className="px-3 py-1 bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 text-xs font-bold uppercase rounded-full border border-purple-100 dark:border-purple-800">
                          {currentQuestion.question.type ||
                            currentQuestion.question.question_type}
                        </span>
                        {currentQuestion.extended && (
                          <span className="px-3 py-1 bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 text-xs font-bold uppercase rounded-full border border-amber-200 dark:border-amber-800 flex items-center gap-1">
                            <Zap className="w-3 h-3" />
                            拓展
                          </span>
                        )}
                        <button
                          onClick={() => setShowNotebookModal(true)}
                          className="ml-auto text-xs font-medium text-indigo-500 dark:text-indigo-400 hover:text-indigo-600 dark:hover:text-indigo-300 flex items-center gap-1 px-2 py-1 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 rounded-lg transition-colors"
                        >
                          <Book className="w-3 h-3" />
                          加入笔记本
                        </button>
                      </div>
                    </div>

                    {/* Question Content */}
                    <div className="p-6 flex-1 overflow-y-auto">
                      <h3 className="text-lg font-medium text-slate-800 dark:text-slate-200 leading-relaxed mb-6 prose dark:prose-invert max-w-none">
                        <ReactMarkdown
                          remarkPlugins={[remarkMath]}
                          rehypePlugins={[rehypeKatex]}
                        >
                          {processLatexContent(
                            currentQuestion.question.question,
                          )}
                        </ReactMarkdown>
                      </h3>

                      {/* Options / Input Area */}
                      {(currentQuestion.question.question_type === "choice" ||
                        currentQuestion.question.type === "choice") &&
                      currentQuestion.question.options ? (
                        <div className="space-y-3">
                          {Object.entries(currentQuestion.question.options).map(
                            ([key, val]) => (
                              <button
                                key={key}
                                onClick={() => handleAnswer(key)}
                                disabled={submittedMap[activeIdx]}
                                className={`w-full text-left p-4 rounded-xl border transition-all flex items-start gap-4 prose dark:prose-invert max-w-none ${
                                  userAnswers[activeIdx] === key
                                    ? submittedMap[activeIdx]
                                      ? key ===
                                        currentQuestion.question.correct_answer
                                        ? "bg-green-50 dark:bg-green-900/30 border-green-500 text-green-800 dark:text-green-200"
                                        : "bg-red-50 dark:bg-red-900/30 border-red-500 text-red-800 dark:text-red-200"
                                      : "bg-purple-50 dark:bg-purple-900/30 border-purple-500 text-purple-900 dark:text-purple-200 shadow-sm"
                                    : submittedMap[activeIdx] &&
                                        key ===
                                          currentQuestion.question
                                            .correct_answer
                                      ? "bg-green-50 dark:bg-green-900/30 border-green-300 dark:border-green-600 text-green-800 dark:text-green-200"
                                      : "bg-white dark:bg-slate-700 border-slate-200 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-200"
                                }`}
                              >
                                <span className="font-bold shrink-0 w-6">
                                  {key}.
                                </span>
                                <ReactMarkdown
                                  remarkPlugins={[remarkMath]}
                                  rehypePlugins={[rehypeKatex]}
                                >
                                  {processLatexContent(String(val))}
                                </ReactMarkdown>
                                {submittedMap[activeIdx] &&
                                  key ===
                                    currentQuestion.question.correct_answer && (
                                    <CheckCircle2 className="w-5 h-5 text-green-600 dark:text-green-400 ml-auto shrink-0" />
                                  )}
                              </button>
                            ),
                          )}
                        </div>
                      ) : (
                        <textarea
                          value={userAnswers[activeIdx] || ""}
                          onChange={(e) => handleAnswer(e.target.value)}
                          disabled={submittedMap[activeIdx]}
                          placeholder="在此输入你的答案..."
                          className="w-full h-48 p-4 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-xl focus:border-purple-500 focus:ring-2 focus:ring-purple-500/10 outline-none resize-none text-slate-800 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-500"
                        />
                      )}
                    </div>

                    {/* Submit Button Area */}
                    <div className="p-4 border-t border-slate-100 dark:border-slate-700 bg-white dark:bg-slate-800 flex gap-3">
                      {!submittedMap[activeIdx] ? (
                        <button
                          onClick={handleSubmit}
                          disabled={!userAnswers[activeIdx]}
                          className="flex-1 py-3 bg-purple-600 text-white rounded-xl font-bold shadow-lg shadow-purple-500/20 hover:bg-purple-700 disabled:opacity-50 disabled:shadow-none transition-all"
                        >
                          提交答案
                        </button>
                      ) : (
                        <>
                          <div className="flex-1 py-3 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 rounded-xl font-medium text-center border border-emerald-200 dark:border-emerald-800 flex items-center justify-center gap-2">
                            <CheckCircle2 className="w-4 h-4" />
                            已提交
                          </div>
                          {activeIdx < questionState.results.length - 1 && (
                            <button
                              onClick={() => setActiveIdx(activeIdx + 1)}
                              className="flex-1 py-3 bg-purple-600 text-white rounded-xl font-bold shadow-lg shadow-purple-500/20 hover:bg-purple-700 transition-all flex items-center justify-center gap-2"
                            >
                              下一题
                              <ChevronRight className="w-4 h-4" />
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </div>

                  {/* Right Side: Answer & Validation Area (shown after submit) */}
                  <div className="w-[400px] flex flex-col gap-4">
                    {/* Answer & Explanation (shown after submit) */}
                    {submittedMap[activeIdx] ? (
                      <>
                        {/* Collapsible Validation Report - only shown after submit */}
                        <div
                          className={`rounded-xl border overflow-hidden ${
                            currentQuestion.extended
                              ? "bg-amber-50 dark:bg-amber-900/30 border-amber-200 dark:border-amber-800"
                              : "bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700"
                          }`}
                        >
                          <button
                            onClick={() => setShowValidation(!showValidation)}
                            className={`w-full px-4 py-3 flex items-center justify-between text-sm font-medium transition-colors ${
                              currentQuestion.extended
                                ? "text-amber-800 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/50"
                                : "text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700"
                            }`}
                          >
                            <div className="flex items-center gap-2">
                              <AlertCircle className="w-4 h-4" />
                              Validation Report
                              <span
                                className={`px-2 py-0.5 text-xs rounded-full ${
                                  currentQuestion.extended
                                    ? "bg-amber-200 dark:bg-amber-800 text-amber-800 dark:text-amber-200"
                                    : "bg-emerald-100 dark:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300"
                                }`}
                              >
                                {currentQuestion.rounds || 1} round
                                {(currentQuestion.rounds || 1) > 1 ? "s" : ""}
                              </span>
                            </div>
                            {showValidation ? (
                              <ChevronDown className="w-4 h-4" />
                            ) : (
                              <ChevronRight className="w-4 h-4" />
                            )}
                          </button>

                          {showValidation && (
                            <div className="px-4 pb-4 animate-in fade-in slide-in-from-top-2">
                              <div
                                className={`p-3 rounded-lg text-sm ${
                                  currentQuestion.extended
                                    ? "bg-amber-100/50 dark:bg-amber-900/30"
                                    : "bg-white dark:bg-slate-700 border border-slate-100 dark:border-slate-600"
                                }`}
                              >
                                {/* Header with status */}
                                <div className="flex items-center gap-2 mb-3 font-semibold flex-wrap">
                                  {currentQuestion.extended ? (
                                    <>
                                      <Zap className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                                      <span className="text-amber-800 dark:text-amber-300">
                                        Extended Question
                                      </span>
                                    </>
                                  ) : currentQuestion.validation?.relevance ? (
                                    <>
                                      <CheckCircle2 className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
                                      <span className="text-emerald-700 dark:text-emerald-300">
                                        Relevance:{" "}
                                        {currentQuestion.validation
                                          .relevance === "high"
                                          ? "High"
                                          : "Partial"}
                                      </span>
                                      <span
                                        className={`px-2 py-0.5 text-xs rounded-full ${
                                          currentQuestion.validation
                                            .relevance === "high"
                                            ? "bg-emerald-100 dark:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300"
                                            : "bg-amber-100 dark:bg-amber-900/50 text-amber-700 dark:text-amber-300"
                                        }`}
                                      >
                                        {currentQuestion.validation
                                          .relevance === "high"
                                          ? "Fully Covered by KB"
                                          : "Extends Beyond KB"}
                                      </span>
                                    </>
                                  ) : (
                                    <>
                                      <CheckCircle2 className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
                                      <span className="text-emerald-700 dark:text-emerald-300">
                                        Validation Passed
                                      </span>
                                    </>
                                  )}
                                </div>

                                {/* KB Coverage - for custom mode */}
                                {currentQuestion.validation?.kb_coverage && (
                                  <div className="mb-3">
                                    <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-400 uppercase tracking-wider mb-1.5 flex items-center gap-1">
                                      <Database className="w-3 h-3" />
                                      Knowledge Base Coverage
                                    </p>
                                    <div className="text-slate-700 dark:text-slate-300 text-xs leading-relaxed bg-emerald-50/50 dark:bg-emerald-900/20 p-2 rounded border border-emerald-100 dark:border-emerald-800 prose prose-xs dark:prose-invert max-w-none">
                                      <ReactMarkdown
                                        remarkPlugins={[remarkMath]}
                                        rehypePlugins={[rehypeKatex]}
                                      >
                                        {processLatexContent(
                                          currentQuestion.validation
                                            .kb_coverage,
                                        )}
                                      </ReactMarkdown>
                                    </div>
                                  </div>
                                )}

                                {/* Extension Points - for custom mode when relevance is partial */}
                                {currentQuestion.validation
                                  ?.extension_points && (
                                  <div className="mb-3">
                                    <p className="text-xs font-semibold text-amber-700 dark:text-amber-400 uppercase tracking-wider mb-1.5 flex items-center gap-1">
                                      <Zap className="w-3 h-3" />
                                      Extension Points
                                    </p>
                                    <div className="text-amber-900 dark:text-amber-200 text-xs leading-relaxed bg-amber-50/50 dark:bg-amber-900/20 p-2 rounded border border-amber-100 dark:border-amber-800 prose prose-xs dark:prose-invert max-w-none">
                                      <ReactMarkdown
                                        remarkPlugins={[remarkMath]}
                                        rehypePlugins={[rehypeKatex]}
                                      >
                                        {processLatexContent(
                                          currentQuestion.validation
                                            .extension_points,
                                        )}
                                      </ReactMarkdown>
                                    </div>
                                  </div>
                                )}

                                {/* KB Connection - for extended questions */}
                                {currentQuestion.extended &&
                                  currentQuestion.validation?.kb_connection && (
                                    <div className="mb-3">
                                      <p className="text-xs font-semibold text-amber-700 dark:text-amber-400 uppercase tracking-wider mb-1.5">
                                        KB Connection
                                      </p>
                                      <div className="text-amber-900 dark:text-amber-200 text-xs leading-relaxed prose prose-xs dark:prose-invert max-w-none">
                                        <ReactMarkdown
                                          remarkPlugins={[remarkMath]}
                                          rehypePlugins={[rehypeKatex]}
                                        >
                                          {processLatexContent(
                                            currentQuestion.validation
                                              .kb_connection,
                                          )}
                                        </ReactMarkdown>
                                      </div>
                                    </div>
                                  )}

                                {/* Extended Aspects - for extended questions */}
                                {currentQuestion.extended &&
                                  currentQuestion.validation
                                    ?.extended_aspect && (
                                    <div className="mb-3">
                                      <p className="text-xs font-semibold text-amber-700 dark:text-amber-400 uppercase tracking-wider mb-1.5">
                                        Extended Aspects
                                      </p>
                                      <div className="text-amber-900 dark:text-amber-200 text-xs leading-relaxed prose prose-xs dark:prose-invert max-w-none">
                                        <ReactMarkdown
                                          remarkPlugins={[remarkMath]}
                                          rehypePlugins={[rehypeKatex]}
                                        >
                                          {processLatexContent(
                                            currentQuestion.validation
                                              .extended_aspect,
                                          )}
                                        </ReactMarkdown>
                                      </div>
                                    </div>
                                  )}

                                {/* Reasoning - legacy field */}
                                {currentQuestion.validation?.reasoning && (
                                  <div>
                                    <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1.5">
                                      推理过程
                                    </p>
                                    <div className="text-slate-700 dark:text-slate-300 text-xs leading-relaxed prose prose-xs dark:prose-invert max-w-none">
                                      <ReactMarkdown
                                        remarkPlugins={[remarkMath]}
                                        rehypePlugins={[rehypeKatex]}
                                      >
                                        {processLatexContent(
                                          currentQuestion.validation.reasoning,
                                        )}
                                      </ReactMarkdown>
                                    </div>
                                  </div>
                                )}
                              </div>
                            </div>
                          )}
                        </div>

                        {/* Answer & Explanation */}
                        <div className="flex-1 bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden flex flex-col animate-in fade-in slide-in-from-bottom-4">
                          <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 bg-emerald-50 dark:bg-emerald-900/30">
                            <h4 className="text-emerald-800 dark:text-emerald-300 font-semibold flex items-center gap-2">
                              <BookOpen className="w-4 h-4" />
                              答案与解析
                            </h4>
                          </div>
                          <div className="p-4 flex-1 overflow-y-auto">
                            <div className="mb-4 p-3 bg-emerald-50 dark:bg-emerald-900/30 rounded-lg border border-emerald-100 dark:border-emerald-800">
                              <p className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 uppercase tracking-wider mb-1">
                                正确答案
                              </p>
                              <div className="text-emerald-800 dark:text-emerald-200 text-base leading-relaxed [&_.katex]:text-emerald-800 dark:[&_.katex]:text-emerald-200 [&_.katex-display]:my-3 [&_.katex-display]:overflow-x-auto prose prose-emerald dark:prose-invert max-w-none prose-p:my-2 prose-p:leading-relaxed">
                                <ReactMarkdown
                                  remarkPlugins={[remarkMath]}
                                  rehypePlugins={[rehypeKatex]}
                                >
                                  {processLatexContent(
                                    String(
                                      currentQuestion.question.correct_answer ||
                                        "",
                                    ),
                                  )}
                                </ReactMarkdown>
                              </div>
                            </div>

                            <div className="prose prose-sm prose-slate dark:prose-invert max-w-none">
                              <ReactMarkdown
                                remarkPlugins={[remarkMath]}
                                rehypePlugins={[rehypeKatex]}
                              >
                                {processLatexContent(
                                  currentQuestion.question.explanation,
                                )}
                              </ReactMarkdown>
                            </div>
                          </div>
                        </div>
                      </>
                    ) : (
                      <div className="flex-1 bg-slate-50 dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 flex items-center justify-center">
                        <div className="text-center text-slate-400 dark:text-slate-500 p-6">
                          <BookOpen className="w-10 h-10 mx-auto mb-3 opacity-30" />
                          <p className="text-sm font-medium">答案已隐藏</p>
                          <p className="text-xs mt-1">提交答案后显示</p>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* PROCESS TAB */}
          {!isConfigMode && activeTab === "process" && (
            <div className="h-full">
              <QuestionDashboard
                state={dashboardState}
                globalProgress={questionState.progress}
                globalLogs={questionState.logs}
                globalResults={questionState.results}
                globalTopic={questionState.topic}
                globalDifficulty={questionState.difficulty}
                globalType={questionState.type}
                globalCount={questionState.count}
                globalStep={questionState.step}
                globalMode={
                  questionState.mode === "knowledge" ? "custom" : "mimic"
                }
                selectedTaskId={selectedTaskId}
                onTaskSelect={setSelectedTaskId}
                tokenStats={questionState.tokenStats}
              />
            </div>
          )}
        </div>
      </div>

      {/* Add to Notebook Modal */}
      {currentQuestion && (
        <AddToNotebookModal
          isOpen={showNotebookModal}
          onClose={() => setShowNotebookModal(false)}
          recordType="question"
          title={`${questionState.topic} - ${currentQuestion.question.type || currentQuestion.question.question_type}`}
          userQuery={`主题：${questionState.topic}\n难度：${questionState.difficulty}\n题型：${questionState.type}`}
          output={`**题目：**\n${currentQuestion.question.question}\n\n**选项：**\n${
            currentQuestion.question.options
              ? Object.entries(currentQuestion.question.options)
                  .map(([k, v]) => `${k}. ${v}`)
                  .join("\n")
              : "无"
          }\n\n**正确答案：** ${currentQuestion.question.correct_answer}\n\n**解析：**\n${currentQuestion.question.explanation}`}
          metadata={{
            difficulty: questionState.difficulty,
            question_type: questionState.type,
            validation_rounds: currentQuestion.rounds,
            extended: currentQuestion.extended,
          }}
          kbName={questionState.selectedKb}
        />
      )}
    </div>
  );
}

export default function QuestionPage() {
  return (
    <Suspense
      fallback={
        <div className="h-screen flex items-center justify-center">
          加载中...
        </div>
      }
    >
      <QuestionPageContent />
    </Suspense>
  );
}
