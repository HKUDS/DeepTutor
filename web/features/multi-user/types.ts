export type ModelAccessItem = {
  profile_id?: string;
  model_id?: string;
  name: string;
  model?: string;
  provider?: string;
  source?: "admin" | "user";
  available?: boolean;
};

export type ModelAccess = {
  llm: ModelAccessItem[];
  embedding: ModelAccessItem[];
  search: ModelAccessItem[];
};

export type GrantPayload = {
  version: number;
  user_id: string;
  models: {
    llm: Array<Record<string, unknown>>;
    embedding: Array<Record<string, unknown>>;
    search: Array<Record<string, unknown>>;
  };
  knowledge_bases: Array<Record<string, unknown>>;
  skills: Array<Record<string, unknown>>;
  spaces: Array<Record<string, unknown>>;
};

export type MultiUserResources = {
  models: {
    llm: Array<{
      profile_id: string;
      name: string;
      models?: Array<{ model_id: string; name: string; model?: string }>;
    }>;
    embedding: Array<{
      profile_id: string;
      name: string;
      models?: Array<{ model_id: string; name: string; model?: string }>;
    }>;
    search: Array<{ profile_id: string; name: string; provider?: string }>;
  };
  knowledge_bases: Array<{
    resource_id: string;
    name: string;
    source: "admin";
  }>;
  skills: Array<{ name: string; description?: string; tags?: string[] }>;
};
