"use client";

import {
  AlertCircle,
  CheckCircle2,
  CircleStop,
  Clock3,
  Loader2,
  MessageCircleQuestion,
  RefreshCw,
  RotateCcw,
  WifiOff,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button, StatusChip, cn, type StatusTone } from "@/shared/ui";
import {
  turnPrimaryAction,
  type TurnPrimaryAction,
  type TurnViewState,
} from "../../model/turn-state";
import { TurnFailureActions } from "./TurnFailureActions";

interface Presentation {
  label: string;
  detail?: string;
  tone: StatusTone;
  icon: LucideIcon;
  spin?: boolean;
}

export interface TurnStatusBarProps {
  state: TurnViewState;
  stage?: string;
  className?: string;
  showSettled?: boolean;
  onCancel?: () => void;
  onAnswer?: () => void;
  onReconnect?: () => void;
  onRegenerate?: () => void;
  onShowDetails?: () => void;
}

export function TurnStatusBar({
  state,
  stage,
  className,
  showSettled = false,
  onCancel,
  onAnswer,
  onReconnect,
  onRegenerate,
  onShowDetails,
}: TurnStatusBarProps) {
  const { t } = useTranslation();
  const presentation = present(state, t);
  const action = turnPrimaryAction(state);
  const settled = state.kind === "idle" || state.kind === "completed";

  if (settled && !showSettled) return null;

  return (
    <>
      <div
        data-turn-state={state.kind}
        className={cn(
          "flex min-h-11 items-center gap-3 rounded-xl border border-border bg-card px-3 py-2 text-sm shadow-sm",
          className,
        )}
      >
        <StatusChip
          tone={presentation.tone}
          icon={
            <presentation.icon
              aria-hidden
              className={cn("h-3.5 w-3.5", presentation.spin && "animate-spin")}
            />
          }
        >
          {presentation.label}
        </StatusChip>
        <p className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          {stage || presentation.detail}
        </p>
        <PrimaryAction
          action={action}
          onCancel={onCancel}
          onAnswer={onAnswer}
          onReconnect={onReconnect}
        />
        <TurnFailureActions
          state={state}
          compact
          onRegenerate={onRegenerate}
          onShowDetails={onShowDetails}
        />
      </div>
      <span
        className="sr-only"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {presentation.label}
      </span>
    </>
  );
}

function PrimaryAction({
  action,
  onCancel,
  onAnswer,
  onReconnect,
}: {
  action: TurnPrimaryAction;
  onCancel?: () => void;
  onAnswer?: () => void;
  onReconnect?: () => void;
}) {
  const { t } = useTranslation();
  if (action === "cancel" && onCancel) {
    return (
      <Button
        size="sm"
        variant="ghost"
        onClick={onCancel}
        icon={<CircleStop aria-hidden className="h-4 w-4" />}
      >
        {t("Stop")}
      </Button>
    );
  }
  if (action === "answer" && onAnswer) {
    return (
      <Button size="sm" variant="secondary" onClick={onAnswer}>
        {t("Answer")}
      </Button>
    );
  }
  if (action === "reconnect" && onReconnect) {
    return (
      <Button
        size="sm"
        variant="secondary"
        onClick={onReconnect}
        icon={<RefreshCw aria-hidden className="h-4 w-4" />}
      >
        {t("Reconnect")}
      </Button>
    );
  }
  return null;
}

function present(
  state: TurnViewState,
  t: (key: string) => string,
): Presentation {
  switch (state.kind) {
    case "idle":
      return {
        label: t("Ready"),
        detail: t("Ask a question when you're ready."),
        tone: "neutral",
        icon: CheckCircle2,
      };
    case "connecting":
      return {
        label: t("Connecting"),
        detail: t("Opening a secure connection…"),
        tone: "info",
        icon: Loader2,
        spin: true,
      };
    case "queued":
      return {
        label: t("Queued"),
        detail: t("Your request is waiting for a worker."),
        tone: "info",
        icon: Clock3,
      };
    case "running":
      return {
        label: t("Working"),
        detail: t("The tutor is preparing a response."),
        tone: "info",
        icon: Loader2,
        spin: true,
      };
    case "waiting_input":
      return {
        label: t("Waiting for your answer"),
        detail: t("Reply below to continue this turn."),
        tone: "warning",
        icon: MessageCircleQuestion,
      };
    case "cancelling":
      return {
        label: t("Stopping"),
        detail: t("Finishing the current operation safely…"),
        tone: "warning",
        icon: Loader2,
        spin: true,
      };
    case "recovering":
      return {
        label: t("Reconnecting"),
        detail: t("Your response is safe. Restoring the live connection…"),
        tone: "warning",
        icon: WifiOff,
      };
    case "completed":
      return {
        label: t("Completed"),
        detail: t("The response is complete."),
        tone: "success",
        icon: CheckCircle2,
      };
    case "cancelled":
      return {
        label: t("Stopped"),
        detail: t("This turn was stopped."),
        tone: "neutral",
        icon: XCircle,
      };
    case "retryable_failure":
      return {
        label: t("Response interrupted"),
        detail: state.failure.message,
        tone: "danger",
        icon: RotateCcw,
      };
    case "terminal_failure":
      return {
        label: t("Turn failed"),
        detail: state.failure.message,
        tone: "danger",
        icon: AlertCircle,
      };
  }
}
