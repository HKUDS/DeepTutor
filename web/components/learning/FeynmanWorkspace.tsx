"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { MessageSquare } from "lucide-react";
import { listLLMOptions, type LLMOption } from "@/lib/llm-options";
import {
  createChallenge,
  confirmMap,
  fetchAttemptDetail,
  fetchFeynmanMap,
  fetchReviews,
  reopenConflict,
  resolveConflict,
  resumeAttempt,
  type AttemptDetail,
} from "@/lib/feynman-learning";
import {
  writeBrowserFeynmanHandoff,
  type FeynmanHandoffKind,
} from "@/lib/feynman-learning-handoff";
import { masteryDisplay, toContractError } from "./contract";
import { FeynmanWorkspaceProps, WorkspaceProps } from "./types";
import {
  initialState,
  workspaceReducer,
  type WorkspaceAction,
  type WorkspaceState,
} from "./workspaceReducer";
import { stagesFor, visibleConversation } from "./workspaceReducer";
import { KnowledgeMapPanel, kpRows } from "./panels/KnowledgeMapPanel";
import { TeachBackPanel } from "./panels/TeachBackPanel";
import { EvidencePanel } from "./panels/EvidencePanel";
import { KnowledgeCardDialog } from "./KnowledgeCardDialog";
import { KnowledgeCardEditor } from "./KnowledgeCardEditor";
import { KnowledgeCardMobileEditor } from "./KnowledgeCardMobileEditor";
import { KnowledgeCardOverview } from "./KnowledgeCardOverview";
import { ReviewQueue } from "./ReviewQueue";
import { MobileTabs } from "./MobileTabs";
import { anyCardBusy } from "./knowledgeCard";
import { selectedCard } from "./knowledgeCardReducer";
import { useKnowledgeCards } from "./useKnowledgeCards";
import type { TeachingModelInfo } from "./ModelIdentity";
import {
  EmptyPathState,
  FatalErrorState,
  LoadingState,
  RecoverableErrorBanner,
} from "./ui";
import { useFeynmanTr, type TrFn } from "./locale";
import "./learning-workspace.css";

/** Composer draft for a progressive-help request. The learner confirms the
 *  wording in the real chat composer before it is sent to the tutor. */
function helpRequestMessage(level: string, tr: TrFn): string {
  switch (level) {
    case "question":
      return tr("请换个方式追问。", "Please ask another way.");
    case "hint":
      return tr("请给我最小提示。", "Please give me a minimal hint.");
    case "source_locator":
      return tr("请帮我定位相关资料。", "Please point me to the relevant source.");
    case "full_explanation":
      return tr("请给我完整讲解。", "Please give me a full explanation.");
    default:
      return tr("请求帮助", "Request help");
  }
}

export type { FeynmanWorkspaceProps, WorkspaceProps };

/**
 * Vertical Feynman learning workspace (UI-01).
 *
 * Desktop: three-column workbench (knowledge map | Teach-Back | evidence).
 * Mobile: three tabs — 知识地图 / 对话 / 证据. Reads LRN-03/MOD-03 read APIs;
 * mutations are version/idempotency guarded with recoverable refresh states.
 */
export default function FeynmanWorkspace({ pathId }: WorkspaceProps) {
  const tr = useFeynmanTr();
  const router = useRouter();
  const [state, dispatch] = useReducer(workspaceReducer, initialState);
  const [teachingModel, setTeachingModel] = useState<TeachingModelInfo | null>(null);
  const [isMobile, setIsMobile] = useState(false);
  const requestSeq = useRef(0);
  const kc = useKnowledgeCards(pathId);

  // r9 responsive: Review opens the desktop center editor at wide widths and
  // the full-screen editor at 390px (§13.5).
  useEffect(() => {
    const mql = window.matchMedia("(max-width: 820px)");
    const update = () => setIsMobile(mql.matches);
    update();
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, []);

  // Initialise path + load map + reviews.
  useEffect(() => {
    let cancelled = false;
    const seq = ++requestSeq.current;
    dispatch({ type: "INIT", pathId });
    Promise.all([fetchFeynmanMap(pathId), fetchReviews(pathId)])
      .then(([map, reviews]) => {
        if (cancelled || seq !== requestSeq.current) return;
        dispatch({ type: "MAP_LOADED", map, reviews });
      })
      .catch((e: unknown) => {
        if (cancelled || seq !== requestSeq.current) return;
        dispatch({ type: "MAP_LOAD_FAILED", error: toContractError(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [pathId]);

  // Teaching model identity (session default; switchable in chat).
  useEffect(() => {
    let cancelled = false;
    listLLMOptions()
      .then((payload) => {
        if (cancelled) return;
        const opts = payload.options as LLMOption[];
        const active = opts.find((o) => o.is_active_default) ?? opts[0] ?? null;
        if (active) {
          setTeachingModel({
            provider: active.provider || active.profile_name || active.profile_id,
            profile: active.profile_name || active.profile_id,
            model: active.model_name || active.model || active.model_id,
            protocol: active.api_protocol || "",
          });
        }
      })
      .catch(() => {
        if (!cancelled) setTeachingModel(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Load attempt detail for the selected knowledge point.
  useEffect(() => {
    if (!state.map || !state.selectedKpId) return;
    const active = state.map.active_attempts[state.selectedKpId];
    if (!active) {
      dispatch({ type: "ATTEMPT_LOADED", attempt: null });
      return;
    }
    let cancelled = false;
    fetchAttemptDetail(pathId, active.attempt_id)
      .then((attempt) => {
        if (!cancelled) dispatch({ type: "ATTEMPT_LOADED", attempt });
      })
      .catch((e: unknown) => {
        if (!cancelled) dispatch({ type: "ATTEMPT_LOAD_FAILED", error: toContractError(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [state.map, state.selectedKpId, pathId]);

  const kpName = useCallback(
    (kpId: string) => {
      if (!state.map) return kpId;
      for (const mod of state.map.map.modules) {
        for (const kp of mod.knowledge_points) {
          if (kp.id === kpId) return kp.name;
        }
      }
      return kpId;
    },
    [state.map],
  );

  const refresh = useCallback(() => {
    if (!pathId) return;
    Promise.all([fetchFeynmanMap(pathId), fetchReviews(pathId)])
      .then(([map, reviews]) => dispatch({ type: "MAP_LOADED", map, reviews }))
      .catch((e: unknown) =>
        dispatch({ type: "MAP_LOAD_FAILED", error: toContractError(e) }),
      );
  }, [pathId]);

  const handleRecover = useCallback(() => {
    dispatch({ type: "RECOVER" });
    refresh();
  }, [refresh]);

  const handleSelectKp = useCallback((kpId: string) => {
    dispatch({ type: "SELECT_KP", kpId });
    dispatch({ type: "TAB_CHANGED", tab: "chat" });
  }, []);

  const goChat = useCallback(() => {
    router.push(`/home/${encodeURIComponent(pathId)}`);
  }, [pathId, router]);

  const handleStartResume = useCallback(async () => {
    if (!state.map || !state.selectedKpId) return;
    const active = state.map.active_attempts[state.selectedKpId];
    if (!active) {
      goChat();
      return;
    }
    dispatch({ type: "RESUME_STARTED" });
    try {
      const resumed = await resumeAttempt(pathId, active.attempt_id);
      const detail = await fetchAttemptDetail(pathId, active.attempt_id);
      dispatch({
        type: "RESUME_SUCCEEDED",
        attempt: detail,
        refreshMeta: {
          attemptVersion: resumed.status === "resumed" ? resumed.attempt_version : 0,
          mapVersion: state.map.map_version,
        },
      });
    } catch (e: unknown) {
      dispatch({ type: "RESUME_FAILED", error: toContractError(e) });
    }
  }, [pathId, state.map, state.selectedKpId, goChat]);

  const handleTestSkip = useCallback(() => {
    // A test-out attempt is started by the tutor loop in chat (§6.5).
    goChat();
  }, [goChat]);

  const handleEditGoal = useCallback(() => {
    goChat();
  }, [goChat]);

  const handleConfirmMap = useCallback(async () => {
    if (!state.map) return;
    try {
      await confirmMap(pathId, {
        expected_map_version: state.map.map_version,
        request_id: `ui-confirm-${Date.now()}`,
        source_snapshot_ids: state.map.map_versions[state.map.map_versions.length - 1]?.source_snapshot_ids ?? null,
      });
      refresh();
    } catch (e: unknown) {
      const err = toContractError(e);
      if (err.kind === "recoverable") {
        dispatch({ type: "ATTEMPT_LOAD_FAILED", error: err });
      }
    }
  }, [pathId, state.map, refresh]);

  const handleResolveConflict = useCallback(
    async (conflictId: string, acceptedSnapshotId: string) => {
      if (!state.map) return;
      const conflict = state.map.conflicts.find((c) => c.id === conflictId);
      if (!conflict) return;
      try {
        await resolveConflict(pathId, conflictId, {
          accepted_snapshot_id: acceptedSnapshotId,
          resolution_note: "采纳此来源作为当前评估依据",
          request_id: `ui-resolve-${Date.now()}`,
          expected_conflict_version: conflict.version,
          expected_map_version: state.map.map_version,
        });
        dispatch({ type: "CONFLICT_RESOLVED", conflictId });
        refresh();
      } catch (e: unknown) {
        const err = toContractError(e);
        if (err.kind === "recoverable") {
          dispatch({ type: "ATTEMPT_LOAD_FAILED", error: err });
        }
      }
    },
    [pathId, state.map, refresh],
  );

  const handleReopenConflict = useCallback(
    async (conflictId: string) => {
      if (!state.map) return;
      const conflict = state.map.conflicts.find((c) => c.id === conflictId);
      if (!conflict) return;
      try {
        await reopenConflict(pathId, conflictId, {
          request_id: `ui-reopen-${Date.now()}`,
          expected_conflict_version: conflict.version,
          expected_map_version: state.map.map_version,
        });
        dispatch({ type: "CONFLICT_REOPENED", conflictId });
        refresh();
      } catch (e: unknown) {
        const err = toContractError(e);
        if (err.kind === "recoverable") {
          dispatch({ type: "ATTEMPT_LOAD_FAILED", error: err });
        }
      }
    },
    [pathId, state.map, refresh],
  );

  const handleChallenge = useCallback(
    async (mode: "reassess_existing" | "collect_new_evidence") => {
      if (!state.attempt) return;
      dispatch({ type: "CHALLENGE_REQUESTED" });
      try {
        const result = await createChallenge(pathId, state.attempt.attempt.id, {
          mode,
          reason: "用户质疑本轮评分",
          request_id: `ui-challenge-${Date.now()}`,
          expected_attempt_version: state.refreshMeta?.attemptVersion ?? 0,
        });
        dispatch({ type: "CHALLENGE_SUCCEEDED", attemptVersion: result.attempt_version });
      } catch (e: unknown) {
        dispatch({ type: "CHALLENGE_FAILED", error: toContractError(e) });
      }
    },
    [pathId, state.attempt, state.refreshMeta],
  );

  // ── knowledge-card review/publication actions (UI-02, §13.5) ────────────
  const kcState = kc.state;
  const currentCard = selectedCard(kcState);
  const cardEditorRef = useRef<HTMLElement | null>(null);

  /** Focus a sensible target inside the center editor after React commits. */
  const focusCardEditor = useCallback(() => {
    const editorEl = cardEditorRef.current;
    if (!editorEl) return;
    const titleInput = editorEl.querySelector<HTMLElement>('[data-testid="kc-title-input"]');
    if (titleInput && !(titleInput as HTMLInputElement).disabled) {
      titleInput.focus();
      return;
    }
    const closeBtn = editorEl.querySelector<HTMLElement>('[data-testid="close-card-editor"]');
    if (closeBtn) {
      closeBtn.focus();
      return;
    }
    editorEl.tabIndex = -1;
    editorEl.focus();
  }, []);

  const openCardEditor = useCallback(
    (cardId: string, source: "panel" | "overview" = "panel") => {
      kc.dispatch({ type: isMobile ? "OPEN_MOBILE_EDITOR" : "OPEN_EDITOR", cardId });
      // From the lower aggregate list the new center editor sits above the
      // fold: bring it into the visible workspace and focus its content once
      // React has committed. Review from the already-visible Evidence Panel
      // must not be scrolled or re-focused (round-1).
      if (!isMobile && source === "overview") {
        requestAnimationFrame(() => {
          cardEditorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
          focusCardEditor();
        });
      }
    },
    [kc, isMobile, focusCardEditor],
  );

  const handleReviewCard = useCallback(
    (cardId: string, source: "panel" | "overview" = "panel") => openCardEditor(cardId, source),
    [openCardEditor],
  );

  const handleDiscardCard = useCallback(
    (cardId: string) => kc.dispatch({ type: "CONFIRM_OPEN", confirm: { kind: "discard", cardId } }),
    [kc],
  );

  const handleCreateCard = useCallback(async () => {
    const card = await kc.ensure(state.selectedKpId);
    if (card) openCardEditor(card.card_id);
  }, [kc, state.selectedKpId, openCardEditor]);

  const handlePublishRequest = useCallback(
    (cardId: string, targetKbName: string) =>
      kc.dispatch({ type: "CONFIRM_OPEN", confirm: { kind: "publish", cardId, targetKbName } }),
    [kc],
  );

  const handleRetractRequest = useCallback(
    (cardId: string) => kc.dispatch({ type: "CONFIRM_OPEN", confirm: { kind: "retract", cardId } }),
    [kc],
  );

  const handleConfirmAction = useCallback(async () => {
    const confirm = kcState.confirm;
    if (!confirm) return;
    try {
      // Keep the dialog open (buttons disabled, Escape ignored) until the
      // confirmed mutation settles so the user cannot double-submit or cancel
      // a mutation that has already been accepted by the server (round-1).
      if (confirm.kind === "publish" && confirm.targetKbName) {
        await kc.publish(confirm.cardId, confirm.targetKbName);
      } else if (confirm.kind === "retract") {
        await kc.retract(confirm.cardId);
      } else if (confirm.kind === "discard") {
        await kc.discard(confirm.cardId);
      }
    } finally {
      kc.dispatch({ type: "CONFIRM_CLOSE" });
    }
  }, [kcState.confirm, kc]);

  const selectedKp = useMemo(() => {
    if (!state.map || !state.selectedKpId) return null;
    const rows = kpRows(state.map, state.selectedKpId);
    return rows.find((r) => r.id === state.selectedKpId) ?? null;
  }, [state.map, state.selectedKpId]);

  const stages = useMemo(() => stagesFor(state), [state]);
  const mastery = useMemo(
    () => masteryDisplay(state.attempt?.projection ?? null),
    [state.attempt],
  );
  const conversation = useMemo(() => visibleConversation(state), [state]);

  const handoffToChat = useCallback(
    (kind: FeynmanHandoffKind, draft: string) => {
      writeBrowserFeynmanHandoff(pathId, kind, draft);
      goChat();
    },
    [pathId, goChat],
  );

  const handleSend = useCallback(
    (text: string) => {
      // Text send is never local evidence: stash the draft for the real chat
      // composer and navigate. The learner confirms before it reaches the tutor.
      handoffToChat("text", text);
    },
    [handoffToChat],
  );

  const handleTranscriptConfirm = useCallback(() => {
    handoffToChat("voice_transcript", state.transcriptText);
  }, [handoffToChat, state.transcriptText]);

  const handleRequestHelp = useCallback(
    (level: string) => {
      const draft = helpRequestMessage(level, tr);
      handoffToChat("help", draft);
    },
    [handoffToChat, tr],
  );

  if (state.loadStatus === "loading" || state.loadStatus === "error") {
    return (
      <div className="feynman-workspace h-full">
        {state.loadStatus === "error" ? (
          <FatalErrorState message={state.fatalError ?? ""} tr={tr} />
        ) : (
          <LoadingState tr={tr} />
        )}
      </div>
    );
  }

  if (state.loadStatus === "empty" || !state.map) {
    return (
      <div className="feynman-workspace h-full">
        <EmptyPathState tr={tr} />
      </div>
    );
  }

  return (
    <div className="feynman-workspace h-full" data-testid="feynman-workspace">
      <header className="fw-appbar" data-testid="workspace-appbar">
        <div className="fw-appbar-context">
          <span className="fw-brand-mark fw-filled fw-blue" aria-hidden="true">
            D
          </span>
          <strong>{"DeepTutor"}</strong>
          <span className="fw-tag fw-blue">{tr("Mastery Path", "Mastery Path")}</span>
        </div>
        <div className="fw-legend" aria-label={tr("颜色语义", "Color semantics")}>
          <span className="fw-legend-tag fw-blue">{tr("复用", "reuse")}</span>
          <span className="fw-legend-tag fw-green">{tr("费曼", "Feynman")}</span>
          <span className="fw-legend-tag fw-amber">{tr("模型", "model")}</span>
          <span className="fw-legend-tag fw-coral">{tr("门禁", "gate")}</span>
          <span className="fw-legend-tag fw-violet">{tr("来源 / ASR", "source / ASR")}</span>
        </div>
        <button
          type="button"
          className="fw-ghost-button"
          onClick={goChat}
          data-testid="continue-in-chat"
        >
          <MessageSquare className="h-4 w-4" />
          {tr("在对话中继续", "Continue in chat")}
        </button>
      </header>

      <MobileTabs
        activeTab={state.activeTab}
        tr={tr}
        onChange={(tab) => dispatch({ type: "TAB_CHANGED", tab })}
      />

      {state.recoverableError ? (
        <div className="p-3">
          <RecoverableErrorBanner
            message={state.recoverableError.message}
            tr={tr}
            onRefresh={handleRecover}
          />
        </div>
      ) : null}

      {kcState.recoverableError ? (
        <div className="p-3">
          <RecoverableErrorBanner
            message={kcState.recoverableError.message}
            tr={tr}
            onRefresh={kc.refreshCards}
          />
        </div>
      ) : null}

      {kcState.mutationError ? (
        <div className="p-3">
          <div className="fw-kc-note coral" role="alert" data-testid="card-mutation-error">
            <span>{kcState.mutationError}</span>
            <button
              type="button"
              className="fw-ghost-button"
              onClick={() => kc.dispatch({ type: "MUTATION_ERROR_CLEAR" })}
              data-testid="card-mutation-error-dismiss"
            >
              {tr("关闭", "Dismiss")}
            </button>
          </div>
        </div>
      ) : null}

      <div className="fw-workspace" data-active-tab={state.activeTab}>
        <KnowledgeMapPanel
          payload={state.map}
          selectedKpId={state.selectedKpId}
          conflicts={state.map.conflicts}
          gapRecords={state.attempt?.gaps ?? []}
          tr={tr}
          onSelectKp={handleSelectKp}
          onStartResume={() => void handleStartResume()}
          onTestSkip={handleTestSkip}
          onConfirmMap={() => void handleConfirmMap()}
          onEditGoal={handleEditGoal}
          busy={state.busy}
        />

        {kcState.editorOpen && currentCard ? (
          <KnowledgeCardEditor
            ref={cardEditorRef}
            card={currentCard}
            kbs={kcState.kbs}
            artifacts={kcState.artifacts}
            busy={kcState.busy}
            tr={tr}
            onSaveDraft={(cardId, changes) => kc.saveDraft(cardId, changes)}
            onRetryGeneration={(cardId) => kc.retryGeneration(cardId)}
            onPublish={handlePublishRequest}
            onRetryPublish={(cardId) => kc.retryPublish(cardId)}
            onReconcilePublication={(cardId) => kc.reconcilePublication(cardId)}
            onRetract={handleRetractRequest}
            onReconcileRetraction={(cardId) => kc.reconcileRetraction(cardId)}
            onDiscard={handleDiscardCard}
            onClose={() => kc.dispatch({ type: "CLOSE_EDITOR" })}
          />
        ) : (
          <TeachBackPanel
            stages={stages}
            mastery={mastery}
            conceptName={selectedKp?.name ?? ""}
            conceptType={selectedKp?.type ?? ""}
            conversation={conversation}
            helpLevel={state.helpLevel}
            usedFullExplanation={state.usedFullExplanation}
            transcriptText={state.transcriptText}
            transcriptState={state.transcriptState}
            composerText={state.composerText}
            busy={state.busy}
            tr={tr}
            onComposerChange={(text) => dispatch({ type: "COMPOSER_CHANGED", text })}
            onSend={handleSend}
            onTranscriptStart={() => dispatch({ type: "TRANSCRIPT_START" })}
            onTranscriptChange={(text) => dispatch({ type: "TRANSCRIPT_CHANGED", text })}
            onTranscriptCancel={() => dispatch({ type: "TRANSCRIPT_CANCEL" })}
            onTranscriptConfirm={handleTranscriptConfirm}
            onRequestHelp={handleRequestHelp}
            onOpenSourceDetail={() => dispatch({ type: "TAB_CHANGED", tab: "evidence" })}
          />
        )}

        <EvidencePanel
          attempt={state.attempt}
          teaching={teachingModel}
          tr={tr}
          onChallenge={(mode) => void handleChallenge(mode)}
          busy={{ ...state.busy, ...kcState.busy }}
          cards={kcState.cards}
          kpId={state.selectedKpId}
          onReviewCard={(cardId) => handleReviewCard(cardId, "panel")}
          onDiscardCard={handleDiscardCard}
          onCreateCard={() => void handleCreateCard()}
        />
      </div>

      <ReviewQueue
        reviews={state.reviews}
        kpName={kpName}
        tr={tr}
        onOpenKp={handleSelectKp}
      />

      <KnowledgeCardOverview
        cards={kcState.cards}
        kpName={kpName}
        tr={tr}
        busy={kcState.busy}
        onReview={(cardId) => handleReviewCard(cardId, "overview")}
        onDiscard={handleDiscardCard}
      />

      {kcState.mobileEditorOpen && currentCard ? (
        <KnowledgeCardMobileEditor
          card={currentCard}
          kbs={kcState.kbs}
          artifacts={kcState.artifacts}
          busy={kcState.busy}
          tr={tr}
          onSaveDraft={(cardId, changes) => kc.saveDraft(cardId, changes)}
          onRetryGeneration={(cardId) => kc.retryGeneration(cardId)}
          onPublish={handlePublishRequest}
          onRetryPublish={(cardId) => kc.retryPublish(cardId)}
          onReconcilePublication={(cardId) => kc.reconcilePublication(cardId)}
          onRetract={handleRetractRequest}
          onReconcileRetraction={(cardId) => kc.reconcileRetraction(cardId)}
          onDiscard={handleDiscardCard}
          onClose={() => kc.dispatch({ type: "CLOSE_MOBILE_EDITOR" })}
        />
      ) : null}

      {kcState.confirm ? (
        <KnowledgeCardDialog
          confirm={kcState.confirm}
          tr={tr}
          busy={anyCardBusy(kcState.busy)}
          onConfirm={handleConfirmAction}
          onCancel={() => kc.dispatch({ type: "CONFIRM_CLOSE" })}
        />
      ) : null}
    </div>
  );
}
