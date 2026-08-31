import { apiFetch, apiUrl } from "@/lib/api";

export interface LearningRecord {
  [key: string]: unknown;
}

export async function listLearningRecords(): Promise<LearningRecord[]> {
  const response = await apiFetch(apiUrl("/api/v1/learning/records"));
  if (!response.ok) throw new Error("Failed to load learning progress");
  return response.json() as Promise<LearningRecord[]>;
}
