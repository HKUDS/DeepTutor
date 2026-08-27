"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { GraduationCap } from "lucide-react";
import { useTranslation } from "react-i18next";

import { fetchMasteryMap, type MasteryMapResult } from "@/lib/learning-api";
import { useMasteryPathActivity } from "@/hooks/useMasteryPathActivity";

/**
 * What this conversation is working on, above the composer.
 *
 * A mastery conversation is bound to a path that outlives it, and until now
 * nothing in the chat said so — the learner arrived from the dashboard to an
 * empty composer with no sign of which path, how far along, or what is next.
 * This is that missing anchor. It reads the same event feed as the dashboard,
 * so the counts tick up as the tutor grades, without the learner switching
 * screens to find out whether an answer landed.
 */
const ACTION_LABEL: Record<string, { cn: string; en: string }> = {
  probe: { cn: "先探查", en: "probing first" },
  practice: { cn: "练到达标", en: "practising to the gate" },
  assess: { cn: "用自己的话解释", en: "explaining it back" },
  review: { cn: "到期复习", en: "due for review" },
  answer_pending: { cn: "等你作答", en: "awaiting your answer" },
  complete: { cn: "已全部掌握 🎉", en: "all mastered 🎉" },
};

export default function MasteryPathStrip({ pathId }: { pathId: string }) {
  const { i18n } = useTranslation();
  const zh = !!i18n.language?.toLowerCase().startsWith("zh");
  const tr = (cn: string, en: string) => (zh ? cn : en);
  const { revision } = useMasteryPathActivity(pathId);
  const [result, setResult] = useState<MasteryMapResult | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchMasteryMap(pathId, { signal: controller.signal })
      .then(setResult)
      .catch(() => {
        if (!controller.signal.aborted) setResult(null);
      });
    return () => controller.abort();
  }, [pathId, revision]);

  // A path with no objectives yet is one the tutor is about to build; there is
  // nothing to anchor to, and an empty "0/0" would read as broken.
  if (!result || result.map.counts.total === 0) return null;

  const { map, next } = result;
  const pct = Math.round((map.counts.mastered / map.counts.total) * 100);
  const action = ACTION_LABEL[next.action];

  return (
    <div className="mx-auto mb-2 flex w-full max-w-[760px] items-center gap-2.5 px-1 text-xs text-[var(--muted-foreground)]">
      <GraduationCap className="h-3.5 w-3.5 shrink-0" />
      <span className="shrink-0 font-medium text-[var(--foreground)]">
        {result.name || tr("精通之路", "Mastery Path")}
      </span>
      <span className="h-1 w-16 shrink-0 overflow-hidden rounded-full bg-[var(--accent)]">
        <span
          className="block h-full bg-green-500 transition-all"
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className="shrink-0">
        {map.counts.mastered}/{map.counts.total}
      </span>
      <span className="min-w-0 flex-1 truncate">
        {next.action === "complete"
          ? tr(action.cn, action.en)
          : `${tr("正在攻", "On")} ${next.knowledge_point_name}${
              action ? tr(` · ${action.cn}`, ` · ${action.en}`) : ""
            }`}
      </span>
      <Link
        href="/space/learning"
        className="shrink-0 text-[var(--primary)] hover:underline"
      >
        {tr("查看地图", "Map")}
      </Link>
    </div>
  );
}
