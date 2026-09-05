import { describe, expect, it } from "vitest";
import { planBriefEntries, planningErrorMessage, planningMessagesToChat } from "@/lib/mastery-planning";
import { LEARNING_PLAN_CONFLICT, LearningPlanApiError } from "@/lib/learning-api";

describe("learning plan brief summary", () => {
  it("maps internal enum values through the translation function", () => {
    const translate = (key: string) => ({
      "masteryPlanning.value.beginner": "初学者",
      "masteryPlanning.value.practice": "实践优先",
      "masteryPlanning.brief.topic": "Topic",
      "masteryPlanning.brief.goal": "Goal",
      "masteryPlanning.brief.level": "Level",
      "masteryPlanning.brief.knownTopics": "Known topics",
      "masteryPlanning.brief.activities": "Activities",
      "masteryPlanning.brief.durationWeeks": "Duration (weeks)",
    }[key] || key);
    expect(planBriefEntries({ name: "Linear algebra", goal: "Solve systems", learner_context: { current_level: "beginner", known_topics: ["vectors"] }, learning_preferences: { activities: ["practice"] }, time_constraints: { target_duration_weeks: 6 } }, translate)).toEqual([
      ["Topic", "Linear algebra"], ["Goal", "Solve systems"], ["Level", "初学者"], ["Known topics", "vectors"], ["Activities", "实践优先"], ["Duration (weeks)", "6"],
    ]);
  });
  it("omits empty values", () => expect(planBriefEntries({ name: "", goal: null, scope: { mode: null } })).toEqual([]));
});

describe("planning conversation mapping", () => {
  it("preserves all persisted messages in chronological transcript order", () => {
    expect(planningMessagesToChat([
      { role: "user", content: "first", created_at: 1 },
      { role: "assistant", content: "reply", created_at: 2 },
      { role: "user", content: "follow-up", created_at: 3 },
      { role: "assistant", content: "answer", created_at: 4 },
    ])).toEqual([
      { id: 1, role: "user", content: "first" },
      { id: 2, role: "assistant", content: "reply" },
      { id: 3, role: "user", content: "follow-up" },
      { id: 4, role: "assistant", content: "answer" },
    ]);
  });
});

describe("planning conflict presentation", () => {
  it("uses the supplied localized retry message for planning conflicts but preserves other error fallbacks", () => {
    const translate = (key: string) => ({ "Planning conflict": "规划已在其他位置更改，请重试。" }[key] || key);
    expect(planningErrorMessage(new LearningPlanApiError(LEARNING_PLAN_CONFLICT, 409), "Could not save the route draft.", translate)).toBe("规划已在其他位置更改，请重试。");
    expect(planningErrorMessage(new Error("upstream unavailable"), "Could not save the route draft.", translate)).toBe("Could not save the route draft.");
  });
});
