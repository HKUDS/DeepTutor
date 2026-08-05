"use client";

import type { Ref } from "react";
import { X } from "lucide-react";
import type { MediaArtifact } from "@/lib/media-types";
import type { KnowledgeCardView } from "@/lib/knowledge-card-api";
import type { KbOption } from "./knowledgeCard";
import { CardStatusTag } from "./KnowledgeCardPanel";
import { KnowledgeCardForm, type KnowledgeCardFormProps } from "./KnowledgeCardForm";
import type { TrFn } from "./locale";

/**
 * Desktop center-column knowledge-card editor (§13.5, r9).
 *
 * Replaces/expands the Teach-Back center column while the map and Evidence
 * Panel stay visible. The form content is shared with the mobile full-screen
 * editor.
 *
 * ``ref`` (React 19 function-component ref) lets the workspace scroll the
 * editor into view and focus a sensible target when Review is invoked from the
 * lower aggregate list (round-1).
 */
export interface KnowledgeCardEditorProps extends KnowledgeCardFormProps {
  onClose: () => void;
  ref?: Ref<HTMLElement>;
}

export function KnowledgeCardEditor({
  ref,
  card,
  kbs,
  artifacts,
  busy,
  tr,
  onSaveDraft,
  onRetryGeneration,
  onPublish,
  onRetryPublish,
  onReconcilePublication,
  onRetract,
  onReconcileRetraction,
  onDiscard,
  onClose,
}: KnowledgeCardEditorProps) {
  return (
    <section
      ref={ref}
      className="fw-panel fw-kc-editor"
      aria-label={tr("知识卡片编辑器", "Knowledge card editor")}
      data-testid="knowledge-card-editor"
    >
      <div className="fw-panel-head fw-kc-editor-head">
        <div className="fw-panel-title">
          <div className="text-xs uppercase tracking-wide text-[var(--fw-muted)]">
            {tr("Knowledge card editor", "Knowledge card editor")}
          </div>
          <strong>{tr("审核知识卡片", "Review knowledge card")}</strong>
        </div>
        <div className="flex items-center gap-2">
          <CardStatusTag status={card.status} tr={tr} />
          <button
            type="button"
            className="fw-icon-button h-8 w-8"
            aria-label={tr("关闭编辑器", "Close editor")}
            onClick={onClose}
            data-testid="close-card-editor"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
      <KnowledgeCardForm
        card={card}
        kbs={kbs}
        artifacts={artifacts}
        busy={busy}
        tr={tr}
        onSaveDraft={onSaveDraft}
        onRetryGeneration={onRetryGeneration}
        onPublish={onPublish}
        onRetryPublish={onRetryPublish}
        onReconcilePublication={onReconcilePublication}
        onRetract={onRetract}
        onReconcileRetraction={onReconcileRetraction}
        onDiscard={onDiscard}
      />
    </section>
  );
}

export type { KnowledgeCardView };
