/** Shared presentation helpers for the Mastery Path dashboard. */

/** The `t` from `useTranslation()`, narrowed to what these helpers need. */
export type Translate = (key: string) => string;

const KNOWLEDGE_TYPE_LABELS: Record<string, string> = {
  concept: "Concept",
  memory: "Memory",
  procedure: "Procedure",
  design: "Design",
};

export function knowledgeTypeLabel(type: string, t: Translate): string {
  const label = KNOWLEDGE_TYPE_LABELS[type];
  return label ? t(label) : type;
}

/**
 * Older paths did not require a human-readable title and sometimes stored the
 * generated path id as the name. Keep a short trace suffix without exposing a
 * database-shaped identifier as the primary label.
 */
export function topicDisplayName(
  topic: { name: string; path_id: string },
  t: Translate,
): string {
  const name = topic.name.trim();
  if (
    name &&
    name !== topic.path_id &&
    !/^unified_\d+_[a-z0-9]+$/i.test(name)
  ) {
    return name;
  }
  const suffix = topic.path_id.split("_").at(-1)?.slice(-4) || "map";
  return `${t("Exploration trail")} · ${suffix}`;
}

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * "3 分钟前" / "in 2 days" — engine timestamps are epoch seconds and can point
 * either way (an attempt happened, a review is due).
 */
export function formatRelative(epochSeconds: number, zh: boolean): string {
  const deltaSeconds = epochSeconds - Date.now() / 1000;
  const past = deltaSeconds < 0;
  const abs = Math.abs(deltaSeconds);

  const [value, unit]: [number, Intl.RelativeTimeFormatUnit] =
    abs < MINUTE
      ? [Math.round(abs), "second"]
      : abs < HOUR
        ? [Math.round(abs / MINUTE), "minute"]
        : abs < DAY
          ? [Math.round(abs / HOUR), "hour"]
          : [Math.round(abs / DAY), "day"];

  return new Intl.RelativeTimeFormat(zh ? "zh-CN" : "en", {
    numeric: "auto",
  }).format(past ? -value : value, unit);
}

/** Calendar form, for when "in 3 days" is not precise enough. */
export function formatAbsolute(epochSeconds: number, zh: boolean): string {
  return new Date(epochSeconds * 1000).toLocaleString(zh ? "zh-CN" : "en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
