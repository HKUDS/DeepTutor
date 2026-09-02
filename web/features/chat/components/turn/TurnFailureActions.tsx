"use client";

import { useTranslation } from "react-i18next";
import { Button } from "@/shared/ui";
import type { TurnViewState } from "../../model/turn-state";

export interface TurnFailureActionsProps {
  state: TurnViewState;
  onRegenerate?: () => void;
  onShowDetails?: () => void;
  compact?: boolean;
}

export function TurnFailureActions({
  state,
  onRegenerate,
  onShowDetails,
  compact = false,
}: TurnFailureActionsProps) {
  const { t } = useTranslation();
  if (state.kind !== "retryable_failure" && state.kind !== "terminal_failure") {
    return null;
  }

  return (
    <div className="flex shrink-0 items-center gap-2">
      {onShowDetails ? (
        <Button size="sm" variant="ghost" onClick={onShowDetails}>
          {t("View details")}
        </Button>
      ) : null}
      {state.kind === "retryable_failure" && onRegenerate ? (
        <Button size="sm" variant="secondary" onClick={onRegenerate}>
          {compact ? t("Retry") : t("Regenerate response")}
        </Button>
      ) : null}
    </div>
  );
}
