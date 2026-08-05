"use client";

import { useParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import FeynmanWorkspace from "@/components/learning/FeynmanWorkspace";

/**
 * Vertical Feynman learning workspace (§13.1).
 *
 * One URL per learning path (the chat session id), rendered as the approved
 * r9 three-column workbench on desktop and the 知识地图 / 对话 / 证据 tabs on
 * mobile. The read APIs recover the map, attempt and evidence panel on every
 * reload (§8.4).
 */
export default function FeynmanWorkspacePage() {
  const params = useParams<{ pathId?: string }>();
  const { t } = useTranslation();
  const pathId = params?.pathId ?? "";
  if (!pathId) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-sm text-[var(--muted-foreground)]">
        {t("Missing learning path id")}
      </div>
    );
  }
  return <FeynmanWorkspace pathId={pathId} />;
}
