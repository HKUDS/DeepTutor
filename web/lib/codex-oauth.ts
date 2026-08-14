import { apiFetch, apiUrl } from "@/lib/api";

export type CodexReasoningModel = {
  model: string;
  name: string;
  supported_reasoning_levels: string[];
  reasoning_effort: string | null;
};

export type CodexOAuthStatus = {
  connection: "disconnected" | "authorizing" | "connected" | "error";
  operation_id: string | null;
  operation_state:
    | "waiting"
    | "exchanging"
    | "fetching_models"
    | "completed"
    | "cancelled"
    | "expired"
    | "failed"
    | null;
  authorize_url: string | null;
  expires_in: number | null;
  callback_port: number | null;
  callback_forward_port: number | null;
  redirect_uri: string | null;
  model_count: number;
  catalog_source:
    | "live"
    | "fresh-cache"
    | "revalidated-cache"
    | "stale-cache"
    | null;
  catalog_fetched_at: number | null;
  active_model: string | null;
  models: CodexReasoningModel[];
  activated: boolean;
  error_code: string | null;
};

export type CodexLoginStart = {
  operation_id: string;
  authorize_url: string;
  expires_in: number;
  callback_port: number;
  callback_forward_port: number;
  redirect_uri: string;
  ssh_forward_command: string;
};

export type CodexRemoteGuidance = Omit<CodexLoginStart, "ssh_forward_command">;

export class CodexOAuthApiError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "CodexOAuthApiError";
    this.code = code;
  }
}

const BASE = "/api/v1/settings/providers/openai-codex";

export function isLoopbackHostname(hostname: string): boolean {
  const normalized = hostname.trim().toLowerCase().replace(/\.$/, "");
  if (
    normalized === "localhost" ||
    normalized.endsWith(".localhost") ||
    normalized === "::1" ||
    normalized === "[::1]"
  ) {
    return true;
  }

  const octets = normalized.split(".");
  return (
    octets.length === 4 &&
    octets[0] === "127" &&
    octets.every(
      (octet) =>
        /^\d+$/.test(octet) && Number(octet) >= 0 && Number(octet) <= 255,
    )
  );
}

export function buildSshForwardCommand(
  callbackPort: number,
  hostname: string,
  forwardPort: number,
): string {
  const serverHost = hostname.trim() || "<server-host>";
  return `ssh -N -L ${callbackPort}:127.0.0.1:${forwardPort} <ssh-user>@${serverHost}`;
}

export function codexRemoteGuidance(
  status: CodexOAuthStatus | null,
  loginStart: CodexLoginStart | null,
): CodexRemoteGuidance | null {
  if (status?.operation_state !== "waiting" || !status.operation_id) {
    return null;
  }
  const matchingStart =
    loginStart?.operation_id === status.operation_id ? loginStart : null;
  const authorizeUrl = status.authorize_url ?? matchingStart?.authorize_url;
  const expiresIn = status.expires_in ?? matchingStart?.expires_in;
  const callbackPort = status.callback_port ?? matchingStart?.callback_port;
  const callbackForwardPort =
    status.callback_forward_port ?? matchingStart?.callback_forward_port;
  const redirectUri = status.redirect_uri ?? matchingStart?.redirect_uri;
  if (
    !authorizeUrl ||
    expiresIn == null ||
    callbackPort == null ||
    callbackForwardPort == null ||
    !redirectUri
  ) {
    return null;
  }
  return {
    operation_id: status.operation_id,
    authorize_url: authorizeUrl,
    expires_in: expiresIn,
    callback_port: callbackPort,
    callback_forward_port: callbackForwardPort,
    redirect_uri: redirectUri,
  };
}

export async function requestCodex<T>(
  path: string,
  method: "GET" | "POST",
  fetchImpl: typeof apiFetch = apiFetch,
  body?: unknown,
): Promise<T> {
  const response = await fetchImpl(apiUrl(`${BASE}${path}`), {
    method,
    ...(body === undefined
      ? {}
      : {
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        }),
    skipAuthRedirect: true,
  });
  if (response.ok) {
    try {
      return (await response.json()) as T;
    } catch {
      throw new CodexOAuthApiError(
        "invalid_response",
        "Encore returned an invalid Codex OAuth response.",
      );
    }
  }

  let code = `http_${response.status}`;
  let message = "Codex request failed.";
  try {
    const payload = (await response.json()) as {
      detail?: { code?: string; message?: string };
    };
    if (payload.detail?.code) code = payload.detail.code;
    if (payload.detail?.message) message = payload.detail.message;
  } catch {
    // The UI renders only the stable code mapping below.
  }
  throw new CodexOAuthApiError(code, message);
}

export function getCodexStatus(): Promise<CodexOAuthStatus> {
  return requestCodex<CodexOAuthStatus>("/oauth/status", "GET");
}

export function startCodexLogin(): Promise<CodexLoginStart> {
  return requestCodex<CodexLoginStart>("/oauth/start", "POST");
}

export function cancelCodexLogin(): Promise<CodexOAuthStatus> {
  return requestCodex<CodexOAuthStatus>("/oauth/cancel", "POST");
}

export function refreshCodexModels(): Promise<CodexOAuthStatus> {
  return requestCodex<CodexOAuthStatus>("/models/refresh", "POST");
}

export function setCodexReasoningEffort(
  model: string,
  reasoningEffort: string | null,
  fetchImpl: typeof apiFetch = apiFetch,
): Promise<CodexOAuthStatus> {
  return requestCodex<CodexOAuthStatus>(
    "/models/reasoning-effort",
    "POST",
    fetchImpl,
    { model, reasoning_effort: reasoningEffort },
  );
}

export function logoutCodex(): Promise<CodexOAuthStatus> {
  return requestCodex<CodexOAuthStatus>("/oauth/logout", "POST");
}

export function shouldPollCodexStatus(status: CodexOAuthStatus): boolean {
  return (
    status.operation_state === "waiting" ||
    status.operation_state === "exchanging" ||
    status.operation_state === "fetching_models"
  );
}

export function codexErrorMessageKey(code: string | null): string {
  if (code === "catalog_unavailable" || code === "catalog_invalid") {
    return "codex.oauth.catalogFailed";
  }
  if (code === "inference_in_progress") {
    return "codex.oauth.inferenceActive";
  }
  if (code === "login_timeout") return "codex.oauth.callbackMissing";
  if (code === "callback_unavailable") {
    return "codex.oauth.callbackUnavailable";
  }
  if (code === "invalid_response") return "codex.oauth.invalidResponse";
  if (code === "reasoning_effort_unsupported") {
    return "codex.oauth.reasoningUnsupported";
  }
  if (
    code === "codex_model_not_found" ||
    code === "codex_catalog_unavailable"
  ) {
    return "codex.oauth.reasoningCatalogChanged";
  }
  if (code === "login_cancelled") return "codex.oauth.cancelled";
  if (code === "authorization_denied") return "codex.oauth.denied";
  return "codex.oauth.requestFailed";
}

export function codexStatusMessageKey(status: CodexOAuthStatus): string {
  if (status.error_code) return codexErrorMessageKey(status.error_code);
  if (shouldPollCodexStatus(status)) return "codex.oauth.waiting";
  if (status.activated && status.active_model) return "codex.oauth.activated";
  if (status.connection === "connected") return "codex.oauth.connected";
  if (status.operation_state === "cancelled") return "codex.oauth.cancelled";
  if (status.operation_state === "expired") return "codex.oauth.expired";
  return "codex.oauth.disconnected";
}
