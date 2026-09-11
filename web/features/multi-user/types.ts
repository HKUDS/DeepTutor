export type GrantPayload = {
  version: number;
  user_id: string;
  models: {
    llm: Array<Record<string, unknown>>;
  };
  knowledge_bases: Array<Record<string, unknown>>;
  skills: Array<Record<string, unknown>>;
  /** Admin-assigned partners the user may see & consult ([{ partner_id }]). */
  partners: Array<Record<string, unknown>>;
  /** null = default (all system tools), [] = none, array = whitelist. */
  enabled_tools: string[] | null;
  /** null = default (all MCP tools), [] = none, array = whitelist. */
  mcp_tools: string[] | null;
  /** null = follow deployment exec policy, false = always disabled. */
  exec_enabled: boolean | null;
  learning_policy: LearningPolicy | null;
};

export type LearningPolicy = {
  age_band: "6-8" | "9-12" | "13-15";
  locked_persona: "teacher";
  allowed_capabilities: Array<"chat" | "immersive_reading">;
  default_capability: "chat" | "immersive_reading";
  allowed_surfaces: Array<"chat" | "reading">;
  reading: {
    allow_upload: boolean;
    material_ids: string[];
    extensions: string[];
  };
};

export type ToolOption = { name: string; description?: string };

export type McpToolOption = {
  name: string;
  /** Provider grouping key; `server` is its pre-provider spelling. */
  provider_id?: string;
  server?: string;
  /** `"mcp"` today, `"cli"` once CLI-app providers land. */
  kind?: string;
  description?: string;
};

export type MultiUserResources = {
  models: {
    llm: Array<{
      profile_id: string;
      name: string;
      models?: Array<{ model_id: string; name: string; model?: string }>;
    }>;
  };
  knowledge_bases: Array<{
    resource_id: string;
    name: string;
    source: "admin";
  }>;
  skills: Array<{ name: string; description?: string; tags?: string[] }>;
  partners: Array<{ partner_id: string; name: string; description?: string }>;
  reading_materials: Array<{
    material_id: string;
    title: string;
    filename: string;
    render_mode: string;
  }>;
  reading_extensions: Array<{
    id: string;
    name: string;
    version: string;
  }>;
  tools: ToolOption[];
  mcp_tools: McpToolOption[];
};

export type BookPermissionLevel = "none" | "read" | "edit";

export type BookPermission = {
  create: boolean;
  default: "none" | "read";
  books: Record<string, BookPermissionLevel>;
};

export type AdminBook = {
  book_id: string;
  title: string;
  status: string;
  updated_at: number;
};
