"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { AlertTriangle, Settings } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  resolveKnowledgeIndexFailure,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";

interface KbIndexFailureBannerProps {
  kb: KnowledgeBase;
  action?: ReactNode;
}

export default function KbIndexFailureBanner({
  kb,
  action,
}: KbIndexFailureBannerProps) {
  const { t } = useTranslation();
  const failure = resolveKnowledgeIndexFailure(kb);
  if (!failure) return null;

  return (
    <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-red-200 bg-red-50/80 px-3 py-2 text-[12px] text-red-700 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-300">
      <div className="flex min-w-0 flex-1 items-start gap-2">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span className="break-words">
          {failure.message ||
            t(
              "Indexing failed. Review the error details, update the configuration if needed, then retry.",
            )}
        </span>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        {failure.requiresModelChange && (
          <Link
            href={failure.settingsHref || "/settings/models"}
            className="inline-flex items-center gap-1.5 rounded-md border border-red-300 bg-red-100 px-2 py-1 text-[11.5px] font-medium text-red-800 transition-colors hover:bg-red-200 dark:border-red-800 dark:bg-red-950/50 dark:text-red-200"
          >
            <Settings className="h-3 w-3" />
            {t("Open model settings")}
          </Link>
        )}
        {action}
      </div>
    </div>
  );
}
