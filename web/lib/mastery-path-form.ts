import type { StructuredTopicDraftInput, TopicSourceInput } from "./learning-api";

export interface MasteryPathFormValues {
  name: string;
  goal: string;
  learningPurpose: string | null;
  customPurpose: string;
  level: string | null;
  knownTopics: string;
  skippedTopics: string;
  scopeMode: string | null;
  scopeInclude: string;
  scopeExclude: string;
  approach: string | null;
  granularity: string | null;
  rigor: string | null;
  activities: string[];
  timeMode: string | null;
  weeklyHours: string;
  durationWeeks: string;
  deadline: string;
  sessionMinutes: string;
  milestonePreference: string | null;
  milestones: Array<{ name: string; description: string; target_week: string }>;
}

const split = (value: string) => value.split(",").map((part) => part.trim()).filter(Boolean);

export function structuredPlanIssues(values: MasteryPathFormValues): string[] {
  const issues: string[] = [];
  if (!values.name.trim()) issues.push("name");
  if (!values.goal.trim()) issues.push("goal");
  if (values.learningPurpose === "custom" && !values.customPurpose.trim()) issues.push("custom_purpose");
  if (values.scopeMode === "selected" && split(values.scopeInclude).length === 0) issues.push("scope_include");
  if (values.timeMode === "weekly" && !(Number(values.weeklyHours) > 0)) issues.push("weekly_hours");
  if (values.timeMode === "duration" && !(Number(values.durationWeeks) > 0)) issues.push("duration_weeks");
  if (values.timeMode === "deadline" && !values.deadline) issues.push("target_date");
  return issues;
}

export function buildStructuredTopicDraftInput(
  values: MasteryPathFormValues,
  sources: TopicSourceInput[],
  mustCover: string[] = [],
): StructuredTopicDraftInput {
  const timeMode = values.timeMode;
  return {
    name: values.name.trim(),
    goal: values.goal.trim(),
    sources,
    topic: {
      name: values.name.trim(),
      purpose: values.goal.trim(),
      learning_purpose: values.learningPurpose,
      custom_purpose: values.learningPurpose === "custom" ? values.customPurpose.trim() || null : null,
    },
    learner_context: {
      current_level: values.level,
      known_topics: values.knownTopics.trim() ? split(values.knownTopics) : null,
      skipped_topics: values.skippedTopics.trim() ? split(values.skippedTopics) : null,
    },
    scope: {
      mode: values.scopeMode,
      include: values.scopeMode === "selected" || values.scopeMode === "custom" ? split(values.scopeInclude) : [],
      exclude: values.scopeMode === "custom" ? split(values.scopeExclude) : [],
    },
    learning_preferences: {
      theory_practice: values.approach,
      granularity: values.granularity,
      mathematical_rigor: values.rigor,
      activities: values.activities.length ? values.activities : null,
    },
    time_constraints: {
      mode: timeMode,
      weekly_hours: timeMode === "weekly" && values.weeklyHours ? Number(values.weeklyHours) : null,
      target_date: timeMode === "deadline" ? values.deadline || null : null,
      target_duration_weeks: timeMode === "duration" && values.durationWeeks ? Number(values.durationWeeks) : null,
      session_duration_minutes: timeMode && timeMode !== "unconstrained" && values.sessionMinutes ? Number(values.sessionMinutes) : null,
    },
    milestones: {
      preference: values.milestonePreference,
      items: values.milestones.length
        ? values.milestones.map((milestone) => ({ name: milestone.name.trim(), description: milestone.description.trim() || null, target_week: milestone.target_week ? Number(milestone.target_week) : null })).filter((milestone) => milestone.name)
        : null,
    },
    ...(mustCover.length ? { must_cover: mustCover } : {}),
  };
}
