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
  /** Resource-specific limits; 0 = unlimited for that period. */
  quota: {
    llm: {
      daily_tokens: number;
      monthly_tokens: number;
    };
    embedding: {
      daily_tokens: number;
      monthly_tokens: number;
    };
    mineru: {
      daily_pages: number;
      monthly_pages: number;
      max_pages_per_file: number;
    };
  };
  /** @deprecated Compatibility alias for quota.llm. */
  token_quota: {
    daily_tokens: number;
    monthly_tokens: number;
  };
};

export type ToolOption = { name: string; description?: string };

export type McpToolOption = {
  name: string;
  server?: string;
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
  tools: ToolOption[];
  mcp_tools: McpToolOption[];
};
