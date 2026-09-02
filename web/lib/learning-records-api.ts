import { apiFetch, apiUrl } from "@/shared/api/client";

export interface ReadingProgressRecord {
  material_id: string;
  latest_locator: number;
  latest_percentage: number;
  furthest_locator: number;
  furthest_percentage: number;
  updated_at: number;
}

export interface ReadingActivityRecord {
  activity_id: string;
  material_id: string;
  extension_id: string;
  action: string;
  locator: number;
  result_type: "card" | "quiz" | "feedback" | "browser_speech";
  created_at: number;
}

export interface LearningRecords {
  progress: ReadingProgressRecord[];
  activities: ReadingActivityRecord[];
}

export async function listLearningRecords(): Promise<LearningRecords> {
  const response = await apiFetch(apiUrl("/api/mastery-paths/reading/records"));
  if (!response.ok) throw new Error("Failed to load learning progress");
  return response.json() as Promise<LearningRecords>;
}
