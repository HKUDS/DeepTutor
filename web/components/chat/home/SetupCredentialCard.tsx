"use client";

import { memo } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import type { SetupCredentialData } from "@/lib/setup-signals";

/**
 * The hand-off card for a configuration step that needs a secret.
 *
 * The assistant is not allowed to collect API keys: anything it types passes
 * through the model's context and is written to the session transcript. So
 * `request_credential` stops at the boundary and emits this card, which sends
 * the user to the settings page that already owns the provider form. The value
 * is entered there, straight into DeepTutor, and never travels through the
 * conversation.
 *
 * Mirrors `deeptutor.capabilities.setup.tools.RequestCredentialTool`; the
 * payload is read by `extractSetupCredential` in `lib/setup-signals.ts`.
 */
export const SetupCredentialCard = memo(function SetupCredentialCard({
  data,
}: {
  data: SetupCredentialData;
}) {
  const { t } = useTranslation();
  const router = useRouter();

  return (
    <div className="mt-3 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-[0_1px_2px_rgba(0,0,0,0.04),0_4px_14px_rgba(0,0,0,0.04)]">
      <div className="flex items-start gap-3">
        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--foreground)_8%,transparent)] text-[12px] text-[var(--foreground)]/70">
          🔑
        </div>
        <div className="flex-1">
          <div className="text-[13px] font-medium leading-snug text-[var(--foreground)]">
            {t("This step needs credentials")}
          </div>
          <div className="mt-0.5 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
            {data.reason ||
              t(
                "Enter the key on the settings page — never in chat, so it stays out of the conversation.",
              )}
          </div>
          <button
            type="button"
            onClick={() => router.push(data.settingsPath)}
            className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[11.5px] font-medium text-[var(--foreground)] transition hover:bg-[color-mix(in_srgb,var(--foreground)_5%,transparent)]"
          >
            {t("Open settings")}
            <span aria-hidden>→</span>
          </button>
        </div>
      </div>
    </div>
  );
});
SetupCredentialCard.displayName = "SetupCredentialCard";
