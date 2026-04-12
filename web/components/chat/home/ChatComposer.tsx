"use client";

import dynamic from "next/dynamic";
import type { RefObject } from "react";
import Image from "next/image";
import {
  ArrowUp,
  BookOpen,
  ChevronDown,
  FilePlus2,
  Loader2,
  MessageSquare,
  Paperclip,
  Sparkles,
  X,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { SelectedHistorySession } from "@/components/chat/HistorySessionPicker";
import AtMentionPopup from "@/components/chat/AtMentionPopup";
import type { SelectedRecord } from "@/app/(workspace)/guide/types";
import type { DeepQuestionFormConfig } from "@/lib/quiz-types";
import type { MathAnimatorFormConfig } from "@/lib/math-animator-types";
import type { DeepResearchFormConfig, ResearchSource } from "@/lib/research-types";
import { ReferenceChips } from "./ChatMessages";

const QuizConfigPanel = dynamic(() => import("@/components/quiz/QuizConfigPanel"), {
  ssr: false,
});
const MathAnimatorConfigPanel = dynamic(
  () => import("@/components/math-animator/MathAnimatorConfigPanel"),
  { ssr: false },
);
const ResearchConfigPanel = dynamic(
  () => import("@/components/research/ResearchConfigPanel"),
  { ssr: false },
);

interface PendingAttachment {
  type: string;
  filename: string;
  base64?: string;
  previewUrl?: string;
}

interface KnowledgeBase {
  name: string;
}

interface CapabilityDef {
  value: string;
  label: string;
  description: string;
  icon: LucideIcon;
  allowedTools: string[];
}

interface ToolDef {
  name: string;
  label: string;
  icon: LucideIcon;
}

interface ResearchSourceDef {
  name: ResearchSource;
  label: string;
  icon: LucideIcon;
}

export default function ChatComposer({
  composerRef,
  textareaRef,
  capMenuRef,
  capBtnRef,
  toolMenuRef,
  toolBtnRef,
  dragCounter,
  dragging,
  capMenuOpen,
  toolMenuOpen,
  showAtPopup,
  hasMessages,
  input,
  attachments,
  activeCap,
  visibleTools,
  selectedTools,
  ragActive,
  knowledgeBases,
  selectedNotebookRecords,
  selectedHistorySessions,
  notebookReferenceGroups,
  stateKnowledgeBase,
  isStreaming,
  isResearchMode,
  isQuizMode,
  isMathAnimatorMode,
  quizConfig,
  quizPdf,
  mathAnimatorConfig,
  researchConfig,
  researchValidationErrors,
  researchPanelCollapsed,
  capabilities,
  researchSources,
  onSetCapMenuOpen,
  onSetToolMenuOpen,
  onSetShowAtPopup,
  onInputChange,
  onSetKB,
  onSelectNotebookPicker,
  onSelectHistoryPicker,
  onToggleTool,
  onToggleResearchSource,
  onSend,
  onRemoveAttachment,
  onRemoveHistory,
  onRemoveNotebook,
  onDragEnter,
  onDragLeave,
  onDragOver,
  onDrop,
  onPaste,
  onTextareaClick,
  onTextareaKeyDown,
  onSelectCapability,
  onChangeQuizConfig,
  onUploadQuizPdf,
  onChangeMathAnimatorConfig,
  onChangeResearchConfig,
  onToggleResearchCollapsed,
}: {
  composerRef: RefObject<HTMLDivElement | null>;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  capMenuRef: RefObject<HTMLDivElement | null>;
  capBtnRef: RefObject<HTMLButtonElement | null>;
  toolMenuRef: RefObject<HTMLDivElement | null>;
  toolBtnRef: RefObject<HTMLButtonElement | null>;
  dragCounter: RefObject<number>;
  dragging: boolean;
  capMenuOpen: boolean;
  toolMenuOpen: boolean;
  showAtPopup: boolean;
  hasMessages: boolean;
  input: string;
  attachments: PendingAttachment[];
  activeCap: CapabilityDef;
  visibleTools: ToolDef[];
  selectedTools: Set<string>;
  ragActive: boolean;
  knowledgeBases: KnowledgeBase[];
  selectedNotebookRecords: SelectedRecord[];
  selectedHistorySessions: SelectedHistorySession[];
  notebookReferenceGroups: Array<{ notebookId: string; notebookName: string; count: number }>;
  stateKnowledgeBase: string;
  isStreaming: boolean;
  isResearchMode: boolean;
  isQuizMode: boolean;
  isMathAnimatorMode: boolean;
  quizConfig: DeepQuestionFormConfig;
  quizPdf: File | null;
  mathAnimatorConfig: MathAnimatorFormConfig;
  researchConfig: DeepResearchFormConfig;
  researchValidationErrors: Record<string, string>;
  researchPanelCollapsed: boolean;
  capabilities: CapabilityDef[];
  researchSources: ResearchSourceDef[];
  onSetCapMenuOpen: (open: boolean | ((prev: boolean) => boolean)) => void;
  onSetToolMenuOpen: (open: boolean | ((prev: boolean) => boolean)) => void;
  onSetShowAtPopup: (open: boolean) => void;
  onInputChange: (value: string, cursorPos: number) => void;
  onSetKB: (kb: string) => void;
  onSelectNotebookPicker: () => void;
  onSelectHistoryPicker: () => void;
  onToggleTool: (tool: ToolDef["name"]) => void;
  onToggleResearchSource: (source: ResearchSource) => void;
  onSend: () => void;
  onRemoveAttachment: (index: number) => void;
  onRemoveHistory: (sessionId: string) => void;
  onRemoveNotebook: (notebookId: string) => void;
  onDragEnter: (event: React.DragEvent) => void;
  onDragLeave: (event: React.DragEvent) => void;
  onDragOver: (event: React.DragEvent) => void;
  onDrop: (event: React.DragEvent) => void;
  onPaste: (event: React.ClipboardEvent) => void;
  onTextareaClick: (event: React.MouseEvent<HTMLTextAreaElement>) => void;
  onTextareaKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onSelectCapability: (value: string) => void;
  onChangeQuizConfig: (next: DeepQuestionFormConfig) => void;
  onUploadQuizPdf: (file: File | null) => void;
  onChangeMathAnimatorConfig: (next: MathAnimatorFormConfig) => void;
  onChangeResearchConfig: (next: DeepResearchFormConfig) => void;
  onToggleResearchCollapsed: () => void;
}) {
  const { t } = useTranslation();
  const CapIcon = activeCap.icon;

  return (
    <div
      ref={composerRef}
      className={`relative z-20 mx-auto w-full shrink-0 pb-5 ${hasMessages ? "pt-4" : ""}`}
    >
      {hasMessages && (
        <div className="pointer-events-none absolute inset-x-0 top-0 h-6 bg-gradient-to-b from-transparent to-[var(--background)]/72" />
      )}

      {capMenuOpen && (
        <div
          ref={capMenuRef}
          className="absolute bottom-full left-0 right-0 z-50 mb-1"
        >
          <div className="mx-auto">
            <div className="w-[280px] rounded-xl border border-[var(--border)] bg-[var(--card)] py-1.5 shadow-lg">
              {capabilities.map((cap) => {
                const Icon = cap.icon;
                const selected = activeCap.value === cap.value;
                return (
                  <button
                    key={cap.value}
                    onClick={() => onSelectCapability(cap.value)}
                    className={`flex w-full items-center gap-3 px-3.5 py-2 text-left transition-colors ${
                      selected ? "bg-[var(--muted)]" : "hover:bg-[var(--muted)]/50"
                    }`}
                  >
                    <Icon
                      size={16}
                      strokeWidth={1.6}
                      className={`shrink-0 ${selected ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]"}`}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-medium text-[var(--foreground)]">{cap.label}</div>
                      <div className="truncate text-[11px] text-[var(--muted-foreground)]">{cap.description}</div>
                    </div>
                    {selected && <div className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--primary)]" />}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}

      <div className="relative">
        <AtMentionPopup
          open={showAtPopup}
          onSelectNotebook={() => {
            onSetShowAtPopup(false);
            onSelectNotebookPicker();
          }}
          onSelectHistory={() => {
            onSetShowAtPopup(false);
            onSelectHistoryPicker();
          }}
        />

        <div
          className={`relative rounded-2xl border bg-[var(--card)] shadow-[0_1px_8px_rgba(0,0,0,0.03)] transition-colors ${
            dragging
              ? "border-[var(--primary)] bg-[var(--primary)]/[0.03]"
              : "border-[var(--border)]"
          }`}
          onDragEnter={onDragEnter}
          onDragLeave={onDragLeave}
          onDragOver={onDragOver}
          onDrop={onDrop}
          data-drag-counter={dragCounter.current}
        >
          {dragging && (
            <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-2xl border-2 border-dashed border-[var(--primary)]/50 bg-[var(--primary)]/[0.04]">
              <div className="flex flex-col items-center gap-1.5 text-[var(--primary)]">
                <Paperclip size={22} strokeWidth={1.6} />
                <span className="text-[13px] font-medium">{t("Drop images here")}</span>
              </div>
            </div>
          )}

          <div className="px-4 pt-3.5 pb-2">
            <ReferenceChips
              historySessions={selectedHistorySessions}
              notebookGroups={notebookReferenceGroups}
              onRemoveHistory={onRemoveHistory}
              onRemoveNotebook={onRemoveNotebook}
            />
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => onInputChange(e.target.value, e.target.selectionStart ?? e.target.value.length)}
              onKeyDown={onTextareaKeyDown}
              onClick={onTextareaClick}
              onPaste={onPaste}
              rows={1}
              placeholder={
                isMathAnimatorMode
                  ? t("Describe the math animation or storyboard you want...")
                  : t("How can I help you today?")
              }
              className="w-full resize-none overflow-hidden bg-transparent text-[15px] leading-relaxed text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
              style={{ transition: "height 0.15s ease-out", minHeight: 28 }}
            />
          </div>

          {!!attachments.length && (
            <div className="flex flex-wrap gap-2 px-4 pb-2">
              {attachments.map((a, i) => (
                <div key={`${a.filename}-${i}`} className="group relative">
                  {a.type === "image" && a.previewUrl ? (
                    <div className="relative h-16 w-16 overflow-hidden rounded-lg border border-[var(--border)]">
                      <Image
                        src={a.previewUrl}
                        alt={a.filename || t("Attachment preview")}
                        fill
                        unoptimized
                        className="object-cover"
                      />
                      <button
                        onClick={() => onRemoveAttachment(i)}
                        className="absolute -right-1.5 -top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-[var(--foreground)] text-[var(--background)] opacity-0 shadow-sm transition-opacity group-hover:opacity-100"
                      >
                        <X size={10} />
                      </button>
                    </div>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-md bg-[var(--muted)] px-2 py-0.5 text-[11px] text-[var(--muted-foreground)]">
                      <FilePlus2 size={10} /> {a.filename}
                      <button onClick={() => onRemoveAttachment(i)} className="ml-0.5 opacity-60 hover:opacity-100">
                        <X size={10} />
                      </button>
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          <div className="border-t border-[var(--border)]/35 px-3 py-2">
            <div className="flex items-center gap-2">
                <button
                ref={capBtnRef}
                onClick={() => onSetCapMenuOpen((v) => !v)}
                className={`inline-flex shrink-0 items-center gap-1.5 py-1.5 px-1 text-[12px] transition-colors ${
                  capMenuOpen
                    ? "text-[var(--foreground)]"
                    : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                <CapIcon size={14} strokeWidth={1.6} />
                <span className="font-medium">{activeCap.label}</span>
                <ChevronDown size={11} className={`transition-transform ${capMenuOpen ? "rotate-180" : ""}`} />
              </button>

              <div className="h-3.5 w-px bg-[var(--border)]/30" />

              <div className="flex min-w-0 flex-1 items-center gap-1">
                {isResearchMode ? (
                  researchSources.map((source) => {
                    const active = researchConfig.sources.includes(source.name);
                    const Icon = source.icon;
                    return (
                      <button
                        key={source.name}
                        onClick={() => onToggleResearchSource(source.name)}
                        className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-[3px] text-[10px] font-medium transition-all ${
                          active
                            ? "border-[var(--primary)]/25 bg-[var(--primary)]/8 text-[var(--primary)]"
                            : "border-[var(--border)]/30 text-[var(--muted-foreground)]/60 hover:border-[var(--border)]/50 hover:text-[var(--foreground)]"
                        }`}
                      >
                        <Icon size={11} strokeWidth={1.7} />
                        {source.label}
                      </button>
                    );
                  })
                ) : visibleTools.length > 0 ? (
                  <div className="relative flex items-center gap-0.5">
                    <button
                      ref={toolBtnRef}
                      onClick={() => onSetToolMenuOpen((v) => !v)}
                      className="inline-flex shrink-0 items-center gap-1 py-1 px-1.5 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
                    >
                      <Sparkles size={12} strokeWidth={1.7} />
                      {t("Tools")}
                      <ChevronDown size={10} className={`transition-transform ${toolMenuOpen ? "rotate-180" : ""}`} />
                    </button>
                    {selectedTools.size > 0 && (
                      <div className="flex items-center gap-[3px] overflow-hidden">
                        {visibleTools.filter((vt) => selectedTools.has(vt.name)).map((vt, i) => (
                          <span key={vt.name} className="shrink-0 text-[10px] text-[var(--muted-foreground)]/35">
                            {i > 0 && <span className="text-[12px] leading-none">·</span>}
                            {vt.label}
                          </span>
                        ))}
                      </div>
                    )}
                    {toolMenuOpen && (
                      <div
                        ref={toolMenuRef}
                        className="absolute bottom-full left-0 z-50 mb-1.5 min-w-[180px] rounded-lg border border-[var(--border)] bg-[var(--card)] py-1 shadow-lg"
                      >
                        {visibleTools.map((tool) => {
                          const active = selectedTools.has(tool.name);
                          const Icon = tool.icon;
                          return (
                            <button
                              key={tool.name}
                              onClick={() => onToggleTool(tool.name)}
                              className={`flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-[12px] transition-colors ${
                                active
                                  ? "text-[var(--primary)]"
                                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                              } hover:bg-[var(--muted)]/40`}
                            >
                              <Icon size={13} strokeWidth={1.7} />
                              <span className="flex-1 font-medium">{tool.label}</span>
                              {active && <div className="h-1.5 w-1.5 rounded-full bg-[var(--primary)]" />}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                ) : null}
              </div>

              <div className="ml-auto flex shrink-0 items-center gap-1.5">
                <select
                  value={stateKnowledgeBase}
                  onChange={(e) => onSetKB(e.target.value)}
                  disabled={!ragActive}
                  title={ragActive ? "Select knowledge base" : "Enable Knowledge Base source first"}
                  className={`h-[28px] appearance-none rounded-full border bg-transparent py-0 pl-2.5 pr-5 text-[11px] outline-none transition-colors ${
                    ragActive
                      ? "cursor-pointer border-[var(--border)]/40 text-[var(--muted-foreground)] hover:border-[var(--border)] hover:text-[var(--foreground)]"
                      : "cursor-not-allowed border-transparent text-[var(--border)]"
                  }`}
                  style={{ backgroundImage: ragActive ? "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")" : "none", backgroundRepeat: "no-repeat", backgroundPosition: "right 6px center" }}
                >
                  <option value="">{ragActive ? "No KB" : "—"}</option>
                  {knowledgeBases.map((kb) => (
                    <option key={kb.name} value={kb.name}>{kb.name}</option>
                  ))}
                </select>

                <button
                  onClick={onSend}
                  disabled={
                    (!input.trim() &&
                      !attachments.length &&
                      !selectedNotebookRecords.length &&
                      !selectedHistorySessions.length) ||
                    isStreaming ||
                    (isResearchMode && Object.keys(researchValidationErrors).length > 0)
                  }
                  className="rounded-full bg-[var(--primary)] p-[7px] text-white shadow-[0_4px_12px_rgba(195,90,44,0.15)] transition-[transform,opacity,box-shadow] hover:shadow-[0_6px_16px_rgba(195,90,44,0.22)] disabled:opacity-25 disabled:shadow-none"
                  aria-label={t("Send")}
                >
                  {isStreaming ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <ArrowUp size={15} strokeWidth={2.5} />
                  )}
                </button>
              </div>
            </div>
          </div>

          {(isQuizMode || isMathAnimatorMode || isResearchMode) && (
            <div className="border-t border-[var(--border)]/15">
              {isQuizMode ? (
                <QuizConfigPanel
                  value={quizConfig}
                  onChange={onChangeQuizConfig}
                  uploadedPdf={quizPdf}
                  onUploadPdf={onUploadQuizPdf}
                />
              ) : isMathAnimatorMode ? (
                <MathAnimatorConfigPanel
                  value={mathAnimatorConfig}
                  onChange={onChangeMathAnimatorConfig}
                />
              ) : (
                <ResearchConfigPanel
                  value={researchConfig}
                  errors={researchValidationErrors}
                  collapsed={researchPanelCollapsed}
                  onChange={onChangeResearchConfig}
                  onToggleCollapsed={onToggleResearchCollapsed}
                />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
