"use client";

import { useState, useEffect } from "react";
import {
  GraduationCap,
  ChevronRight,
  ChevronLeft,
  ArrowRight,
  Loader2,
} from "lucide-react";
import "katex/dist/katex.min.css";

import {
  NotebookSelector,
  ProgressPanel,
  ChatPanel,
  HTMLViewer,
  DebugModal,
  CompletionSummary,
} from "./components";
import { useGuideSession, useNotebookSelection } from "./hooks";

export default function GuidePage() {
  // Notebook selection hook
  const {
    notebooks,
    expandedNotebooks,
    notebookRecordsMap,
    selectedRecords,
    loadingNotebooks,
    loadingRecordsFor,
    fetchNotebooks,
    toggleNotebookExpanded,
    toggleRecordSelection,
    selectAllFromNotebook,
    deselectAllFromNotebook,
    clearAllSelections,
  } = useNotebookSelection();

  // Session management hook
  const {
    sessionState,
    chatMessages,
    isLoading,
    loadingMessage,
    canStart,
    canNext,
    isCompleted,
    isLastKnowledge,
    createSession,
    startLearning,
    nextKnowledge,
    sendMessage,
    fixHtml,
  } = useGuideSession();

  // UI state
  const [showDebugModal, setShowDebugModal] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWide, setSidebarWide] = useState(false);

  // Load notebooks on mount
  useEffect(() => {
    fetchNotebooks();
  }, [fetchNotebooks]);

  // Calculate widths based on ratio
  const leftWidthPercent = sidebarCollapsed ? 0 : sidebarWide ? 75 : 25;
  const rightWidthPercent = sidebarCollapsed ? 100 : sidebarWide ? 25 : 75;

  const handleCreateSession = () => {
    createSession(selectedRecords);
  };

  const handleFixHtml = async (description: string) => {
    return await fixHtml(description);
  };

  return (
    <div className="h-screen flex gap-0 p-4 animate-fade-in relative">
      {/* LEFT PANEL: Chat & Control */}
      <div
        className={`flex flex-col gap-4 h-full transition-all duration-300 flex-shrink-0 mr-4 ${sidebarCollapsed ? "overflow-hidden" : ""}`}
        style={{
          width: sidebarCollapsed ? 0 : `${leftWidthPercent}%`,
          minWidth: sidebarCollapsed
            ? 0
            : `${Math.max(leftWidthPercent * 0.01 * 1200, 300)}px`,
          maxWidth: sidebarCollapsed ? 0 : `${leftWidthPercent}%`,
        }}
      >
        {/* Multi-Notebook Selection */}
        {sessionState.status === "idle" && (
          <NotebookSelector
            notebooks={notebooks}
            expandedNotebooks={expandedNotebooks}
            notebookRecordsMap={notebookRecordsMap}
            selectedRecords={selectedRecords}
            loadingNotebooks={loadingNotebooks}
            loadingRecordsFor={loadingRecordsFor}
            isLoading={isLoading}
            onToggleExpanded={toggleNotebookExpanded}
            onToggleRecord={toggleRecordSelection}
            onSelectAll={selectAllFromNotebook}
            onDeselectAll={deselectAllFromNotebook}
            onClearAll={clearAllSelections}
            onCreateSession={handleCreateSession}
          />
        )}

        {/* Progress Bar with Action Buttons */}
        {sessionState.status !== "idle" && (
          <ProgressPanel
            sessionState={sessionState}
            isLoading={isLoading}
            canStart={canStart}
            canNext={canNext}
            isLastKnowledge={isLastKnowledge}
            onStartLearning={startLearning}
            onNextKnowledge={nextKnowledge}
          />
        )}

        {/* Chat Interface */}
        <ChatPanel
          messages={chatMessages}
          isLearning={sessionState.status === "learning"}
          onSendMessage={sendMessage}
        />
      </div>

      {/* RIGHT PANEL: Interactive Content */}
      <div
        className="flex flex-col h-full overflow-hidden transition-all duration-300 flex-1 relative"
        style={{ width: `${rightWidthPercent}%` }}
      >
        {/* Collapse/Expand and Width Toggle Button */}
        <div className="absolute top-4 left-4 z-20 flex gap-2">
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="p-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg shadow-sm hover:bg-slate-50 dark:hover:bg-slate-700 transition-all"
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {sidebarCollapsed ? (
              <ChevronRight className="w-4 h-4 text-slate-600 dark:text-slate-300" />
            ) : (
              <ChevronLeft className="w-4 h-4 text-slate-600 dark:text-slate-300" />
            )}
          </button>
          {!sidebarCollapsed && (
            <button
              onClick={() => setSidebarWide(!sidebarWide)}
              className="p-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg shadow-sm hover:bg-slate-50 dark:hover:bg-slate-700 transition-all"
              title={
                sidebarWide
                  ? "Switch to narrow sidebar (1:3)"
                  : "Switch to wide sidebar (3:1)"
              }
            >
              <ArrowRight
                className={`w-4 h-4 text-slate-600 dark:text-slate-300 transition-transform ${sidebarWide ? "rotate-180" : ""}`}
              />
            </button>
          )}
        </div>

        {/* Content based on state */}
        {sessionState.status === "idle" ? (
          <div className="flex-1 bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 flex flex-col items-center justify-center text-slate-300 dark:text-slate-600 p-8">
            <GraduationCap className="w-24 h-24 text-slate-200 dark:text-slate-600 mb-6" />
            <h3 className="text-lg font-medium text-slate-600 dark:text-slate-300 mb-2">
              Guided Learning
            </h3>
            <p className="text-sm text-slate-400 dark:text-slate-500 max-w-md text-center leading-relaxed">
              Select a notebook, and the system will generate a personalized
              learning plan. Through interactive pages and intelligent Q&A,
              you&apos;ll gradually master all the content.
            </p>
          </div>
        ) : isCompleted ? (
          <CompletionSummary summary={sessionState.summary} />
        ) : sessionState.status === "learning" ? (
          <HTMLViewer
            html={sessionState.current_html}
            currentIndex={sessionState.current_index}
            loadingMessage={loadingMessage}
            onOpenDebugModal={() => setShowDebugModal(true)}
          />
        ) : (
          <div className="flex-1 bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 flex flex-col items-center justify-center text-slate-300 dark:text-slate-600 p-8">
            <Loader2 className="w-12 h-12 text-indigo-400 dark:text-indigo-500 animate-spin mb-4" />
            <p className="text-slate-500 dark:text-slate-400">
              {loadingMessage || "Loading learning content..."}
            </p>
          </div>
        )}
      </div>

      {/* Debug Modal */}
      <DebugModal
        isOpen={showDebugModal}
        onClose={() => setShowDebugModal(false)}
        onFix={handleFixHtml}
      />
    </div>
  );
}
