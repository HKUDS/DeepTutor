export type KnowledgeEngineGroup = "local" | "server" | "cloud";

const CLOUD_ENGINE_IDS = new Set(["pageindex", "ima"]);
const SERVER_ENGINE_IDS = new Set(["lightrag-server"]);
const LOCAL_ENGINE_IDS = new Set([
  "llamaindex",
  "pageindex-oss",
  "graphrag",
  "lightrag",
]);

/**
 * Keep the Knowledge Center grouping stable for the built-in engines while
 * still giving future providers a sensible home.
 */
export function knowledgeEngineGroup(provider: {
  id: string;
  requires_api_key?: boolean;
}): KnowledgeEngineGroup {
  if (CLOUD_ENGINE_IDS.has(provider.id)) return "cloud";
  if (SERVER_ENGINE_IDS.has(provider.id)) return "server";
  if (LOCAL_ENGINE_IDS.has(provider.id)) return "local";
  return provider.requires_api_key ? "cloud" : "local";
}
