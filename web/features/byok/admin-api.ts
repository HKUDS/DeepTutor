import { apiFetch, apiUrl } from "@/lib/api";

export type AdminByokService = {
  enabled: boolean;
  allowed_bindings: string[];
  allow_custom_endpoints?: boolean;
  allow_cloud?: boolean;
};

export type AdminByokPolicy = {
  version: number;
  enabled: boolean;
  default_source: Record<"llm" | "embedding" | "mineru", "platform" | "byok">;
  services: Record<"llm" | "embedding" | "mineru", AdminByokService>;
  endpoint_allowlist: string[];
  limits: {
    byok_requests_per_minute: number;
    max_single_request_tokens: number;
    max_pages_per_file: number;
  };
};

async function readError(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json();
    return String(body?.detail || fallback);
  } catch {
    return fallback;
  }
}

export async function fetchAdminByokPolicy(): Promise<{
  policy: AdminByokPolicy;
  auth_enabled: boolean;
  vault_available: boolean;
}> {
  const response = await apiFetch(apiUrl("/api/v1/admin/byok/policy"));
  if (!response.ok) throw new Error(await readError(response, "无法读取 BYOK 策略"));
  return response.json();
}

export async function saveAdminByokPolicy(policy: AdminByokPolicy): Promise<AdminByokPolicy> {
  const response = await apiFetch(apiUrl("/api/v1/admin/byok/policy"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ policy }),
  });
  if (!response.ok) throw new Error(await readError(response, "无法保存 BYOK 策略"));
  const data = await response.json();
  return data.policy as AdminByokPolicy;
}
