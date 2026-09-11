"use client";

import { ArrowRight, Check, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { PartnerInvocation } from "@/lib/partner-groups-api";

/**
 * A partner's proposal to ask one peer a follow-up question.
 *
 * Nothing has happened yet when this appears: the proposal is inert until the
 * user approves it, so the card leads with the question itself and keeps the
 * two actions plain. It stays visible after the decision as the audit trail
 * for why a follow-up round exists.
 */
export default function InvocationCard({
  invocation,
  busy,
  showQuestion,
  onApprove,
  onReject,
}: {
  invocation: PartnerInvocation;
  busy: boolean;
  /** False once the question is published as its own bubble downstream. */
  showQuestion: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  const { t } = useTranslation();
  const { status } = invocation;

  return (
    <div className="mt-2 rounded-xl border border-[var(--border)] bg-[var(--muted)]/30 px-3.5 py-3">
      <div className="flex items-center gap-1.5 text-[10.5px] font-medium text-[var(--muted-foreground)]">
        <span>{invocation.requester_partner_name}</span>
        <ArrowRight size={10} className="shrink-0" />
        <span>{invocation.target_partner_name}</span>
      </div>
      {showQuestion ? (
        <p className="mt-1.5 whitespace-pre-wrap text-[12px] leading-relaxed text-[var(--foreground)]">
          {invocation.question}
        </p>
      ) : null}

      {status === "pending" ? (
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onApprove}
            disabled={busy}
            className="inline-flex h-7 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-2.5 text-[11px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {busy ? (
              <Loader2 size={11} className="animate-spin" />
            ) : (
              <Check size={11} />
            )}
            {t("Let them discuss")}
          </button>
          <button
            type="button"
            onClick={onReject}
            disabled={busy}
            className="inline-flex h-7 items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 text-[11px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:opacity-50"
          >
            {t("Not now")}
          </button>
        </div>
      ) : (
        <div className="mt-2 inline-flex items-center gap-1.5 text-[10.5px] text-[var(--muted-foreground)]">
          {status === "approved" ? (
            <>
              <Loader2 size={11} className="animate-spin" />
              {t("Waiting for {{name}}", {
                name: invocation.target_partner_name,
              })}
            </>
          ) : status === "completed" ? (
            <>
              <Check size={11} />
              {t("Discussed")}
            </>
          ) : status === "failed" ? (
            <span className="text-red-500">
              {invocation.error || t("Follow-up failed")}
            </span>
          ) : (
            <>
              <X size={11} />
              {t("Declined")}
            </>
          )}
        </div>
      )}
    </div>
  );
}
