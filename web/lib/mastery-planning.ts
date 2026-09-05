export const PLAN_BRIEF_LABELS = {
  "Topic": "masteryPlanning.brief.topic", "Goal": "masteryPlanning.brief.goal", "Level": "masteryPlanning.brief.level", "Known topics": "masteryPlanning.brief.knownTopics", "Skipped topics": "masteryPlanning.brief.skippedTopics", "Scope": "masteryPlanning.brief.scope", "Approach": "masteryPlanning.brief.approach", "Activities": "masteryPlanning.brief.activities", "Time": "masteryPlanning.brief.time", "Weekly hours": "masteryPlanning.brief.weeklyHours", "Duration (weeks)": "masteryPlanning.brief.durationWeeks", "Session minutes": "masteryPlanning.brief.sessionMinutes",
} as const;

const DISPLAY_VALUES: Record<string, string> = {
  beginner: "masteryPlanning.value.beginner", intermediate: "masteryPlanning.value.intermediate", advanced: "masteryPlanning.value.advanced",
  unconstrained: "masteryPlanning.value.flexible", limited: "masteryPlanning.value.limited", deadline: "masteryPlanning.value.deadline",
  broad: "masteryPlanning.value.broad", focused: "masteryPlanning.value.focused", theory: "masteryPlanning.value.theory", practice: "masteryPlanning.value.practice", balanced: "masteryPlanning.value.balanced",
};

export function planBriefEntries(brief: Record<string, unknown> | null | undefined, translate: (key: string) => string = (key) => key): Array<[string, string]> {
  if (!brief) return [];
  const entries: Array<[string, string]> = [];
  const display = (value: unknown): string => Array.isArray(value) ? value.map(display).join(", ") : typeof value === "string" ? translate(DISPLAY_VALUES[value] || value) : String(value);
  const add = (label: keyof typeof PLAN_BRIEF_LABELS, value: unknown) => { if (value == null || value === "" || (Array.isArray(value) && value.length === 0)) return; entries.push([translate(PLAN_BRIEF_LABELS[label]), display(value)]); };
  add("Topic", brief.name ?? (brief.topic as Record<string, unknown> | undefined)?.name);
  add("Goal", brief.goal ?? (brief.topic as Record<string, unknown> | undefined)?.purpose);
  const learner = brief.learner_context as Record<string, unknown> | undefined;
  add("Level", learner?.current_level); add("Known topics", learner?.known_topics); add("Skipped topics", learner?.skipped_topics);
  const scope = brief.scope as Record<string, unknown> | undefined; add("Scope", scope?.mode);
  const prefs = brief.learning_preferences as Record<string, unknown> | undefined; add("Approach", prefs?.theory_practice); add("Activities", prefs?.activities);
  const time = brief.time_constraints as Record<string, unknown> | undefined; add("Time", time?.mode); add("Weekly hours", time?.weekly_hours); add("Duration (weeks)", time?.target_duration_weeks); add("Session minutes", time?.session_duration_minutes);
  return entries;
}
import type { LearningPlanMessage } from "./learning-api";
import { isLearningPlanConflict } from "./learning-api";

export function planningErrorMessage(
  error: unknown,
  fallback: string,
  translate: (key: string) => string = (key) => key,
): string {
  return isLearningPlanConflict(error) ? translate("Planning conflict") : fallback;
}

export function planningMessagesToChat(messages: LearningPlanMessage[]) {
  return messages.map((message, index) => ({
    id: index + 1,
    role: message.role,
    content: message.content,
  }));
}
