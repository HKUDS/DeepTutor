import { apiFetch, apiUrl } from "@/lib/api";

export interface SettingsPreset {
  id: string;
  label: string;
  description: string;
  parser: string;
  resource_cost: "low" | "medium" | "high";
  credentials: string[];
  prerequisites: string[];
  unlocked_features: string[];
}

export interface SettingsPresetsPayload {
  schema_version: "deeptutor.settings-presets/v1";
  presets: SettingsPreset[];
}

export async function fetchSettingsPresets(): Promise<SettingsPresetsPayload> {
  const response = await apiFetch(apiUrl("/api/settings/presets"));
  if (!response.ok) {
    throw new Error(`Settings presets failed: HTTP ${response.status}`);
  }
  return (await response.json()) as SettingsPresetsPayload;
}
