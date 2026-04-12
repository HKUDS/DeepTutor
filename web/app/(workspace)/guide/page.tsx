"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CalendarRange,
  BookOpen,
  Flag,
  LineChart,
  ChevronRight,
  ChevronLeft,
  ArrowRight,
  Loader2,
  Sparkles,
  Target,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import "katex/dist/katex.min.css";

import type { SelectedRecord } from "./types";
import NotebookRecordPicker from "@/components/notebook/NotebookRecordPicker";
import SaveToNotebookModal from "@/components/notebook/SaveToNotebookModal";
import {
  ChatPanel,
  HTMLViewer,
  DebugModal,
  CompletionSummary,
  KnowledgeTabBar,
  SessionSwitcher,
  SessionHistoryList,
} from "./components";
import { useGuideSession, useGuideHistory } from "./hooks";
import { useTranslation } from "react-i18next";

export default function GuidePage() {
  const { t } = useTranslation();

  const {
    sessionState,
    chatMessages,
    isLoading,
    loadingMessage,
    sessionError,
    canStart,
    isCompleted,
    readyCount,
    allPagesReady,
    currentPageReady,
    createSession,
    startLearning,
    navigateTo,
    retryPage,
    completeLearning,
    sendMessage,
    fixHtml,
    resetSession,
    loadSession,
  } = useGuideSession();

  const { sessions, loading: historyLoading, refresh: refreshHistory } = useGuideHistory();

  const [showDebugModal, setShowDebugModal] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWide, setSidebarWide] = useState(false);
  const [topicInput, setTopicInput] = useState("");
  const [showNotebookPicker, setShowNotebookPicker] = useState(false);
  const [selectedNotebookRecords, setSelectedNotebookRecords] = useState<
    SelectedRecord[]
  >([]);
  const [showSaveModal, setShowSaveModal] = useState(false);

  const [hiddenSummaryBySession, setHiddenSummaryBySession] = useState<
    Record<string, boolean>
  >({});

  const leftWidthPercent = sidebarCollapsed ? 0 : sidebarWide ? 75 : 25;
  const rightWidthPercent = sidebarCollapsed ? 100 : sidebarWide ? 25 : 75;
  const isIdle = sessionState.status === "idle";
  const totalPoints = sessionState.knowledge_points.length;
  const statusLabelMap: Record<string, string> = {
    idle: t("Idle"),
    initialized: t("Initialized"),
    learning: t("Learning"),
    completed: t("Completed"),
  };
  const currentSessionKey = sessionState.session_id || "__guide__";
  const showingSummary =
    sessionState.status === "completed" &&
    Boolean(sessionState.summary) &&
    !hiddenSummaryBySession[currentSessionKey];
  const notebookReferenceGroups = useMemo(() => {
    const groups = new Map<string, { notebookName: string; count: number }>();
    selectedNotebookRecords.forEach((record) => {
      const existing = groups.get(record.notebookId);
      if (existing) {
        existing.count += 1;
      } else {
        groups.set(record.notebookId, {
          notebookName: record.notebookName,
          count: 1,
        });
      }
    });
    return Array.from(groups.entries()).map(([notebookId, value]) => ({
      notebookId,
      ...value,
    }));
  }, [selectedNotebookRecords]);
  const notebookReferencesPayload = useMemo(() => {
    const grouped = new Map<string, string[]>();
    selectedNotebookRecords.forEach((record) => {
      const current = grouped.get(record.notebookId) || [];
      current.push(record.id);
      grouped.set(record.notebookId, current);
    });
    return Array.from(grouped.entries()).map(([notebook_id, record_ids]) => ({
      notebook_id,
      record_ids,
    }));
  }, [selectedNotebookRecords]);
  const guideSavePayload = useMemo(() => {
    if (sessionState.status === "idle" || !sessionState.session_id) return null;
    return {
      recordType: "guided_learning" as const,
      title: sessionState.topic || t("Guided Learning"),
      userQuery: sessionState.topic || "",
      output: JSON.stringify(
        {
          topic: sessionState.topic,
          status: sessionState.status,
          knowledge_points: sessionState.knowledge_points,
          current_index: sessionState.current_index,
          html_pages: sessionState.html_pages,
          page_statuses: sessionState.page_statuses,
          summary: sessionState.summary,
        },
        null,
        2,
      ),
      metadata: {
        source: "guided_learning",
        progress: sessionState.progress,
        session_id: sessionState.session_id,
      },
    };
  }, [sessionState, t]);

  const handleCreateSession = () => {
    createSession(topicInput, notebookReferencesPayload);
  };

  const handleResetSession = async () => {
    await resetSession();
    refreshHistory();
  };

  const handleLoadSession = async (sessionId: string) => {
    await loadSession(sessionId);
  };

  const handleFixHtml = async (description: string) => {
    return await fixHtml(description);
  };

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const session = params.get("session");
    if (session) {
      void loadSession(session);
    }
  }, [loadSession]);

  return (
    <div className="h-screen overflow-y-auto bg-[radial-gradient(circle_at_top_left,_rgba(195,90,44,0.14),_transparent_28%),linear-gradient(180deg,_rgba(255,255,255,0.3),_transparent_40%)] px-6 py-8 animate-fade-in">
      <div className="mx-auto flex max-w-7xl flex-col gap-5">
      <section className="surface-card overflow-hidden border-0 bg-[linear-gradient(135deg,#fff7f0_0%,#f8f1e6_52%,#f4efe8_100%)]">
        <div className="grid gap-6 px-6 py-7 md:grid-cols-[1.3fr_0.9fr] md:px-8">
          <div className="space-y-4">
            <div className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1 text-xs font-medium text-[var(--primary)] shadow-sm">
              <Sparkles className="h-3.5 w-3.5" />
              {t("Guided Learning")}
            </div>
            <h1 className="max-w-3xl text-3xl font-semibold tracking-tight text-[var(--foreground)] md:text-4xl">
              {t("从概念到理解闭环，逐步构建可迁移的知识结构。")}
            </h1>
            <p className="max-w-2xl text-sm leading-7 text-[var(--muted-foreground)] md:text-base">
              {t("引导式学习强调概念拆解、原理解释与交互式课件学习，适合从0到1建立系统理解，再衔接备考式学习做提分训练。")}
            </p>
          </div>

          <div className="grid gap-3 rounded-[28px] border border-white/70 bg-white/80 p-5 shadow-[0_18px_60px_rgba(195,90,44,0.08)] backdrop-blur">
            <Metric icon={Target} label={t("知识点数量")} value={String(totalPoints)} />
            <Metric icon={CalendarRange} label={t("已就绪页面")} value={`${readyCount}/${Math.max(totalPoints, 1)}`} />
            <Metric icon={LineChart} label={t("学习状态")} value={statusLabelMap[sessionState.status] || sessionState.status} />
            <Metric icon={Flag} label={t("当前会话")} value={sessionState.session_id || t("尚未创建")} />
          </div>
        </div>
      </section>

      <div className="flex gap-4">
      {/* LEFT PANEL */}
      <div
        className={`flex flex-col gap-3 h-[calc(100vh-4rem)] transition-all duration-300 flex-shrink-0 ${sidebarCollapsed ? "overflow-hidden" : ""}`}
        style={{
          width: sidebarCollapsed ? 0 : `${leftWidthPercent}%`,
          minWidth: sidebarCollapsed
            ? 0
            : `${Math.max(leftWidthPercent * 0.01 * 1200, 300)}px`,
          maxWidth: sidebarCollapsed ? 0 : `${leftWidthPercent}%`,
        }}
      >
        {isIdle ? (
          <div className="surface-card overflow-hidden border-0 bg-[linear-gradient(135deg,#fff7f0_0%,#f8f1e6_52%,#f4efe8_100%)]">
            <div className="border-b border-white/70 bg-white/55 p-4">
              <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--foreground)]">
                <Sparkles className="h-5 w-5 text-[var(--primary)]" />
                {t("Describe what you want to learn")}
              </h2>
              <p className="mt-2 text-sm text-[var(--muted-foreground)]">
                {t(
                  "Write a short learning request, and the system will design a progressive guided learning plan for you.",
                )}
              </p>
            </div>

            <div className="p-4 space-y-4">
              <textarea
                value={topicInput}
                onChange={(e) => setTopicInput(e.target.value)}
                placeholder={t(
                  "For example: Teach me linear algebra from the basics, with intuition, key formulas, and common mistakes.",
                )}
                rows={8}
                className="w-full resize-none rounded-xl border bg-[var(--card)] px-4 py-3 text-sm text-[var(--foreground)] outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/10"
              />

              <div className="rounded-xl border bg-white/80 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-[var(--foreground)]">
                      {t("Notebook Context")}
                    </div>
                    <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                      {t("Optionally ground the learning plan with saved notebook records.")}
                    </p>
                  </div>
                  <button
                    onClick={() => setShowNotebookPicker(true)}
                    className="inline-flex items-center gap-2 rounded-lg border bg-[var(--card)] px-3 py-2 text-xs font-medium text-[var(--foreground)] transition hover:bg-[var(--secondary)]"
                  >
                    <BookOpen className="h-4 w-4" />
                    {t("Select Records")}
                  </button>
                </div>
                {notebookReferenceGroups.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {notebookReferenceGroups.map((group) => (
                      <span
                        key={group.notebookId}
                        className="inline-flex items-center gap-2 rounded-full border bg-[var(--card)] px-3 py-1 text-[11px] text-[var(--foreground)]"
                      >
                        {group.notebookName} ({group.count})
                      </span>
                    ))}
                  </div>
                )}
              </div>

              <button
                onClick={handleCreateSession}
                disabled={isLoading || !topicInput.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2.5 text-sm font-medium text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Sparkles className="w-4 h-4" />
                )}
                {t("Generate learning plan")}
              </button>
              {sessionError ? (
                <div className="rounded-xl border border-[var(--destructive)]/20 bg-[var(--destructive)]/5 px-3 py-2 text-xs text-[var(--destructive)]">
                  {sessionError}
                </div>
              ) : null}
            </div>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-end">
              <button
                onClick={() => setShowSaveModal(true)}
                className="inline-flex items-center gap-2 rounded-xl border bg-[var(--card)] px-3 py-2 text-sm font-medium text-[var(--foreground)] transition hover:bg-[var(--secondary)]"
              >
                <BookOpen className="h-4 w-4" />
                {t("Add to Notebook")}
              </button>
            </div>
            <SessionSwitcher
              currentSessionId={sessionState.session_id}
              currentTopic={sessionState.topic}
              currentStatus={sessionState.status}
              sessions={sessions}
              onLoadSession={handleLoadSession}
              onNewSession={handleResetSession}
            />
            <ChatPanel
              messages={chatMessages}
              isLearning={sessionState.status === "learning" && currentPageReady}
              currentKnowledgeTitle={
                sessionState.current_index >= 0
                  ? sessionState.knowledge_points[sessionState.current_index]
                      ?.knowledge_title
                  : undefined
              }
              currentKnowledgeIndex={
                sessionState.current_index >= 0
                  ? sessionState.current_index
                  : undefined
              }
              onSendMessage={sendMessage}
            />
          </>
        )}
      </div>

      {/* RIGHT PANEL */}
      <div
        className="relative flex h-[calc(100vh-4rem)] flex-1 flex-col overflow-hidden transition-all duration-300"
        style={{ width: `${rightWidthPercent}%` }}
      >
        {/* Collapse/Expand buttons */}
        {isIdle && (
          <div className="absolute top-4 left-4 z-20 flex gap-2">
            <button
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              className="rounded-lg border bg-white/90 p-2 shadow-sm transition-all hover:bg-[var(--secondary)]"
              title={
                sidebarCollapsed ? t("Expand sidebar") : t("Collapse sidebar")
              }
            >
              {sidebarCollapsed ? (
                <ChevronRight className="h-4 w-4 text-[var(--muted-foreground)]" />
              ) : (
                <ChevronLeft className="h-4 w-4 text-[var(--muted-foreground)]" />
              )}
            </button>
            {!sidebarCollapsed && (
              <button
                onClick={() => setSidebarWide(!sidebarWide)}
                className="rounded-lg border bg-white/90 p-2 shadow-sm transition-all hover:bg-[var(--secondary)]"
                title={
                  sidebarWide
                    ? t("Switch to narrow sidebar (1:3)")
                    : t("Switch to wide sidebar (3:1)")
                }
              >
                <ArrowRight
                  className={`h-4 w-4 text-[var(--muted-foreground)] transition-transform ${sidebarWide ? "rotate-180" : ""}`}
                />
              </button>
            )}
          </div>
        )}

        {isIdle ? (
          <div className="surface-card flex flex-1 flex-col overflow-hidden">
            <SessionHistoryList
              sessions={sessions}
              loading={historyLoading}
              onLoadSession={handleLoadSession}
            />
          </div>
        ) : (
          <>
            {/* Knowledge tab bar */}
            <KnowledgeTabBar
              sessionState={sessionState}
              isLoading={isLoading}
              canStart={canStart}
              readyCount={readyCount}
              allPagesReady={allPagesReady}
              isCompleted={showingSummary}
              onStartLearning={startLearning}
              onNavigate={(index) => {
                setHiddenSummaryBySession((prev) => ({
                  ...prev,
                  [currentSessionKey]: true,
                }));
                navigateTo(index);
              }}
              onRetryPage={retryPage}
              onCompleteLearning={() => {
                completeLearning();
                setHiddenSummaryBySession((prev) => ({
                  ...prev,
                  [currentSessionKey]: false,
                }));
              }}
              onResetSession={handleResetSession}
              onShowSummary={() =>
                setHiddenSummaryBySession((prev) => ({
                  ...prev,
                  [currentSessionKey]: false,
                }))
              }
            />

            {/* Main content */}
            <div className="flex-1 min-h-0 flex flex-col">
              {showingSummary && sessionState.summary ? (
                <CompletionSummary summary={sessionState.summary} />
              ) : sessionState.status === "learning" || (isCompleted && !showingSummary) ? (
                <HTMLViewer
                  html={
                    sessionState.current_index >= 0
                      ? sessionState.html_pages[sessionState.current_index] ||
                        ""
                      : ""
                  }
                  currentIndex={sessionState.current_index}
                  loadingMessage={
                    sessionState.current_index >= 0 &&
                    sessionState.page_statuses[sessionState.current_index] ===
                      "failed"
                      ? t(
                          "This page failed to generate. You can retry it from the tab bar.",
                        )
                      : loadingMessage ||
                        t("Waiting for the selected interactive page...")
                  }
                  onOpenDebugModal={() => setShowDebugModal(true)}
                />
              ) : sessionState.status === "initialized" ? (
                <div className="flex h-full flex-col items-center justify-center rounded-b-2xl border border-t-0 bg-white/90 p-8 text-center">
                  <Sparkles className="mb-4 h-10 w-10 text-[var(--primary)]" />
                  <p className="text-base font-medium text-[var(--foreground)]">
                    {t("Plan created successfully.")}
                  </p>
                  <p className="mt-2 text-sm text-[var(--muted-foreground)]">
                    {t("Click Start to generate interactive pages.")}
                  </p>
                </div>
              ) : (
                <div className="flex h-full flex-col items-center justify-center rounded-b-2xl border border-t-0 bg-white/90 p-8 text-[var(--muted-foreground)]">
                  <Loader2 className="mb-4 h-12 w-12 animate-spin text-[var(--primary)]/70" />
                  <p className="text-[var(--muted-foreground)]">
                    {loadingMessage || t("Loading learning content...")}
                  </p>
                </div>
              )}
            </div>
          </>
        )}
      </div>

      <DebugModal
        isOpen={showDebugModal}
        onClose={() => setShowDebugModal(false)}
        onFix={handleFixHtml}
      />
      <NotebookRecordPicker
        open={showNotebookPicker}
        onClose={() => setShowNotebookPicker(false)}
        onApply={(records) => setSelectedNotebookRecords(records)}
      />
      <SaveToNotebookModal
        open={showSaveModal}
        payload={guideSavePayload}
        onClose={() => setShowSaveModal(false)}
      />
      </div>
      </div>
    </div>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-[var(--border)]/80 bg-[var(--card)]/90 px-4 py-3">
      <div className="rounded-full bg-[var(--secondary)] p-2 text-[var(--primary)]">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <div className="text-xs text-[var(--muted-foreground)]">{label}</div>
        <div className="truncate text-2xl font-semibold leading-none text-[var(--foreground)] mt-1">{value}</div>
      </div>
    </div>
  );
}
