"use client";

import { ArrowLeft } from "lucide-react";
import type { MediaArtifact } from "@/lib/media-types";
import type { KnowledgeCardView } from "@/lib/knowledge-card-api";
import type { KbOption } from "./knowledgeCard";
import { CardStatusTag } from "./KnowledgeCardPanel";
import { KnowledgeCardForm, type KnowledgeCardFormProps } from "./KnowledgeCardForm";
import type { TrFn } from "./locale";

/**
 * Mobile full-screen knowledge-card editor (§13.5, r9 390px).
 *
 * ``Review`` on the 390px Evidence tab opens a true full-screen editor with a
 * usable back action; the three workspace tabs stay outside the editor. The
 * form content is shared with the desktop center editor.
 */
export function KnowledgeCardMobileEditor({
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
}: KnowledgeCardFormProps & { onClose: () => void }) {
  return (
    <div className="fw-kc-mobile-editor" data-testid="knowledge-card-mobile-editor">
      <header className="fw-kc-mobile-top">
        <button
          type="button"
          className="fw-icon-button h-8 w-8"
          aria-label={tr("返回", "Back")}
          onClick={onClose}
          data-testid="mobile-editor-back"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <h3 className="fw-kc-mobile-title">{tr("审核知识卡片", "Review knowledge card")}</h3>
        <CardStatusTag status={card.status} tr={tr} />
      </header>
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
    </div>
  );
}
