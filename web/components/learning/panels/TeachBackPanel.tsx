"use client";

import { Check, Mic, Send, Sparkles } from "lucide-react";
import type { ConversationItem, StageState, MasteryDisplay } from "../contract";
import { StageBar } from "../StageBar";
import type { TrFn } from "../locale";

const HELP_LEVELS = ["question", "hint", "source_locator", "full_explanation"] as const;

export function helpLevelLabel(level: string, tr: TrFn): string {
  switch (level) {
    case "question":
      return tr("换个追问", "Ask another way");
    case "hint":
      return tr("给最小提示", "Minimal hint");
    case "source_locator":
      return tr("定位资料", "Locate source");
    case "full_explanation":
      return tr("完整讲解", "Full explanation");
    default:
      return level;
  }
}

export function conversationLabel(item: ConversationItem, tr: TrFn): string {
  switch (item.labelKey) {
    case "conversation.explanation":
      return tr("我的复教", "My explanation");
    case "conversation.probe":
      return tr("AI 学生 · 新手追问", "AI student · probe");
    case "conversation.probeAnswer":
      return tr("我的回答", "My answer");
    case "conversation.transfer":
      return tr("AI 学生 · 迁移题", "AI student · transfer");
    case "conversation.transferAnswer":
      return tr("我的迁移回答", "My transfer answer");
    case "conversation.reteach":
      return tr("系统 · 重新复教", "System · reteach");
    case "conversation.sourceRef":
      return tr("系统 · 来源", "System · source");
    case "conversation.voice":
      return tr("我的语音复教（已确认转写）", "My voice explanation (confirmed)");
    case "help.requested":
      return tr("帮助已请求", "Help requested");
    default:
      return item.role === "assistant"
        ? tr("AI 学生", "AI student")
        : tr("我", "Me");
  }
}

function messageColor(item: ConversationItem): string {
  if (item.kind === "probe_question" || item.kind === "transfer_question")
    return "fw-amber";
  if (item.kind === "reteach") return "fw-coral";
  if (item.kind === "source_reference") return "fw-violet";
  if (item.kind === "help") return "fw-amber";
  if (item.inputMode === "voice_transcript") return "fw-violet";
  return "fw-green";
}

export function TeachBackPanel({
  stages,
  mastery,
  conceptName,
  conceptType,
  conversation,
  helpLevel,
  usedFullExplanation,
  transcriptText,
  transcriptState,
  composerText,
  busy,
  tr,
  onComposerChange,
  onSend,
  onTranscriptStart,
  onTranscriptChange,
  onTranscriptCancel,
  onTranscriptConfirm,
  onRequestHelp,
  onOpenSourceDetail,
}: {
  stages: StageState[];
  mastery: MasteryDisplay;
  conceptName: string;
  conceptType: string;
  conversation: ConversationItem[];
  helpLevel: string | null;
  usedFullExplanation: boolean;
  transcriptText: string;
  transcriptState: "idle" | "editing";
  composerText: string;
  busy: Record<string, boolean>;
  tr: TrFn;
  onComposerChange: (text: string) => void;
  onSend: (text: string) => void;
  onTranscriptStart: () => void;
  onTranscriptChange: (text: string) => void;
  onTranscriptCancel: () => void;
  onTranscriptConfirm: () => void;
  onRequestHelp: (level: string) => void;
  onOpenSourceDetail: () => void;
}) {
  const send = () => {
    const text = composerText.trim();
    if (!text) return;
    onSend(text);
  };

  return (
    <main className="fw-panel fw-chat-panel" data-testid="chat-panel">
      <div className="fw-concept-head">
        <div className="fw-concept-row">
          <div className="fw-panel-title">
            <span className="text-xs text-[var(--fw-muted)]">
              {tr("当前概念", "Current concept")}
            </span>
            <strong>{conceptName || tr("选择知识点", "Select a knowledge point")}</strong>
          </div>
          <span className="fw-tag fw-amber shrink-0">{conceptType || tr("概念", "concept")}</span>
        </div>
        <StageBar stages={stages} mastery={mastery} tr={tr} />
      </div>

      <div className="fw-chat-stream" data-testid="conversation-stream" aria-live="polite">
        {conversation.length === 0 ? (
          <div className="fw-empty" data-testid="conversation-empty">
            <Sparkles className="h-5 w-5" />
            <span>
              {tr(
                "用自己的话讲解这个知识点，AI 会先作为新手追问。",
                "Explain this point in your own words; the AI student will probe from there.",
              )}
            </span>
          </div>
        ) : (
          conversation.map((item) => (
            <article
              key={item.key}
              className={`fw-message ${item.role} ${messageColor(item)}`}
              data-turn-key={item.key}
            >
              <div className="fw-message-head">
                <strong>{conversationLabel(item, tr)}</strong>
                <span className="fw-message-meta">
                  {item.inputMode === "voice_transcript" && item.transcriptConfirmed
                    ? tr("语音 · 已确认", "voice · confirmed")
                    : item.inputMode === "voice_transcript"
                      ? tr("语音", "voice")
                      : tr("文字", "text")}
                </span>
              </div>
              <span>{item.content}</span>
            </article>
          ))
        )}
      </div>

      {/* Progressive help (§6.3) */}
      <div className="fw-help-bar" data-testid="help-bar">
        <div className="fw-meta-row flex items-center gap-2">
          <strong className="text-sm">{tr("渐进帮助", "Progressive help")}</strong>
          <span className="fw-tag fw-amber">
            {helpLevel
              ? `${tr("Help", "Help")} ${HELP_LEVELS.indexOf(helpLevel as (typeof HELP_LEVELS)[number])}`
              : tr("未使用", "unused")}
          </span>
        </div>
        <div className="fw-help-actions">
          {HELP_LEVELS.map((level) => (
            <button
              key={level}
              type="button"
              className={`fw-help-button${level === "full_explanation" ? " full" : ""}`}
              onClick={() => onRequestHelp(level)}
              data-help-level={level}
            >
              {helpLevelLabel(level, tr)}
            </button>
          ))}
        </div>
        {usedFullExplanation ? (
          <span className="text-xs text-[var(--fw-coral)]">
            {tr(
              "已使用完整讲解：本轮旧证据链已关闭，需要重新完成完整复教。",
              "Full explanation used: the current chain is closed — restart the full reteach.",
            )}
          </span>
        ) : (
          <span className="text-xs text-[var(--fw-muted)]">
            {tr(
              "使用完整讲解后，本轮必须重新完整复教。",
              "Using the full explanation requires a full reteach.",
            )}
          </span>
        )}
      </div>

      {/* Composer + ASR transcript boundary (§7.2, §13.1) */}
      <div className="fw-composer" data-testid="composer">
        {transcriptState === "editing" ? (
          <div className="fw-asr-review" data-testid="transcript-review">
            <div className="fw-asr-head">
              <strong className="text-sm">{tr("ASR 转写 · 待确认", "ASR transcript · pending")}</strong>
              <span className="fw-tag fw-violet">{tr("可编辑", "editable")}</span>
            </div>
            <textarea
              aria-label={tr("编辑语音转写文本", "Edit voice transcript")}
              value={transcriptText}
              onChange={(e) => onTranscriptChange(e.target.value)}
              placeholder={tr("粘贴或编辑语音转写…", "Paste or edit the voice transcript…")}
            />
            <div className="fw-asr-foot">
              <span className="text-xs text-[var(--fw-muted)]">
                {tr("确认后将在对话中继续，尚未成为评估证据。", "Confirming continues in chat; nothing is evidence yet.")}
              </span>
              <div className="flex gap-2">
                <button type="button" className="fw-ghost-button" onClick={onTranscriptCancel}>
                  {tr("取消", "Cancel")}
                </button>
                <button
                  type="button"
                  className="fw-confirm-button"
                  onClick={onTranscriptConfirm}
                  disabled={!transcriptText.trim()}
                  data-testid="confirm-transcript"
                >
                  <Check className="h-4 w-4" />
                  {tr("去对话发送", "Send in chat")}
                </button>
              </div>
            </div>
          </div>
        ) : null}

        <div className="fw-compose-row">
          <textarea
            aria-label={tr("输入复教内容", "Teach-back input")}
            value={composerText}
            onChange={(e) => onComposerChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder={tr("继续解释，或回答 AI 学生的问题……", "Continue explaining, or answer the AI student…")}
          />
          <button
            type="button"
            className="fw-icon-button violet"
            aria-label={tr("开始语音输入", "Start voice input")}
            title={tr("语音转写边界（编辑后确认）", "Voice transcript (edit then confirm)")}
            onClick={onTranscriptStart}
            data-testid="voice-input"
          >
            <Mic className="h-4 w-4" />
          </button>
          <button
            type="button"
            className="fw-icon-button send"
            aria-label={tr("发送复教内容", "Send teach-back")}
            title={tr("发送复教内容", "Send teach-back")}
            onClick={send}
            disabled={!composerText.trim() || busy.resume}
            data-testid="send-message"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
        <button
          type="button"
          className="fw-ghost-button justify-self-start"
          onClick={onOpenSourceDetail}
          data-testid="open-source-detail"
        >
          {tr("查看来源详情", "View source detail")}
        </button>
      </div>
    </main>
  );
}
