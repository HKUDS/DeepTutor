export type ByokService = "llm" | "embedding" | "mineru";
export type ByokSource = "platform" | "byok";

export type ByokProfile = {
  id: string;
  service: ByokService;
  name?: string;
  provider: string;
  model?: string;
  base_url?: string;
  dimension?: number;
  mode?: string;
  status?: string;
  configured?: boolean;
  generation?: number;
  updated_at?: string;
};

export type ByokStatus = {
  auth_enabled: boolean;
  vault_available: boolean;
  policy: {
    enabled: boolean;
    services: Record<ByokService, { enabled: boolean; allowed: boolean }>;
  };
  profiles: ByokProfile[];
  preferences: Partial<Record<ByokService, { source: ByokSource; profile_id?: string }>>;
  platform: Record<ByokService, boolean>;
};
