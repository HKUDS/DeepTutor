"use client";

import Link from "next/link";
import { ArrowRight, Info } from "lucide-react";
import { useTranslation } from "react-i18next";
import { subPanelClass } from "./shared";

export type ModelSectionGuideKind =
  | "connections"
  | "llm"
  | "task-models"
  | "embedding"
  | "search"
  | "voice"
  | "multimodal";

const GUIDE_CONFIG: Record<
  ModelSectionGuideKind,
  {
    badgeKey: string;
    tone: "required" | "recommended" | "optional";
    purposeKey: string;
    ifUnsetKey: string;
  }
> = {
  connections: {
    badgeKey: "modelGuide.badge.sharedCredentials",
    tone: "required",
    purposeKey: "modelGuide.connections.purpose",
    ifUnsetKey: "modelGuide.connections.ifUnset",
  },
  llm: {
    badgeKey: "quickSetup.progress.required",
    tone: "required",
    purposeKey: "modelGuide.llm.purpose",
    ifUnsetKey: "modelGuide.llm.ifUnset",
  },
  "task-models": {
    badgeKey: "modelGuide.badge.autoByDefault",
    tone: "optional",
    purposeKey: "modelGuide.taskModels.purpose",
    ifUnsetKey: "modelGuide.taskModels.ifUnset",
  },
  embedding: {
    badgeKey: "quickSetup.progress.recommended",
    tone: "recommended",
    purposeKey: "modelGuide.embedding.purpose",
    ifUnsetKey: "modelGuide.embedding.ifUnset",
  },
  search: {
    badgeKey: "quickSetup.progress.optional",
    tone: "optional",
    purposeKey: "modelGuide.search.purpose",
    ifUnsetKey: "modelGuide.search.ifUnset",
  },
  voice: {
    badgeKey: "quickSetup.progress.optional",
    tone: "optional",
    purposeKey: "modelGuide.voice.purpose",
    ifUnsetKey: "modelGuide.voice.ifUnset",
  },
  multimodal: {
    badgeKey: "quickSetup.progress.optional",
    tone: "optional",
    purposeKey: "modelGuide.multimodal.purpose",
    ifUnsetKey: "modelGuide.multimodal.ifUnset",
  },
};

export function ModelSectionGuideBanner({
  kind,
}: {
  kind: ModelSectionGuideKind;
}) {
  const { t } = useTranslation();
  const cfg = GUIDE_CONFIG[kind];
  const badgeToneClass =
    cfg.tone === "required"
      ? "bg-[color-mix(in_srgb,var(--foreground)_10%,transparent)] text-[var(--foreground)]"
      : cfg.tone === "recommended"
        ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
        : "bg-[color-mix(in_srgb,var(--muted)_95%,transparent)] text-[var(--muted-foreground)]";

  return (
    <aside
      className={`mb-5 flex flex-col gap-2 px-4 py-3 text-[12.5px] leading-[1.55] sm:flex-row sm:items-center sm:justify-between ${subPanelClass}`}
    >
      <div className="flex min-w-0 items-start gap-2.5">
        <Info
          size={15}
          strokeWidth={1.8}
          className="mt-0.5 shrink-0 text-[var(--muted-foreground)]"
        />
        <div className="min-w-0 space-y-0.5">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded-md px-1.5 py-0.5 text-[11px] font-medium leading-4 ${badgeToneClass}`}
            >
              {t(cfg.badgeKey)}
            </span>
            <span className="font-medium text-[var(--foreground)]">
              {t(cfg.purposeKey)}
            </span>
          </div>
          <p className="text-[12px] text-[var(--muted-foreground)]">
            {t(cfg.ifUnsetKey)}
          </p>
        </div>
      </div>

      <Link
        href="/settings/quick-setup"
        className="inline-flex shrink-0 items-center gap-1 self-start text-[12px] font-medium text-[var(--muted-foreground)] underline decoration-[var(--border)] underline-offset-4 transition-colors hover:text-[var(--foreground)] sm:self-center"
      >
        {t("modelGuide.quickSetupLink")}
        <ArrowRight size={12} />
      </Link>
    </aside>
  );
}
