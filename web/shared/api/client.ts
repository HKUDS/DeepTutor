import { ApiError, type AppError, type AppErrorScope } from "./errors";
import { browserReturnPath, loginHref } from "../auth/return-url";

export interface RequestOptions extends RequestInit {
  scope?: AppErrorScope;
  skipAuthRedirect?: boolean;
}

let runtimeAuthEnabled = false;

export function apiUrl(path: string): string {
  return path;
}

export function wsUrl(path: string): string {
  return path;
}

export function parseAuthEnabled(raw: string | undefined): boolean {
  return /^(1|true|yes|on)$/i.test((raw ?? "").trim());
}

export function setRuntimeAuthEnabled(enabled: boolean): void {
  runtimeAuthEnabled = enabled;
}

export async function apiFetch(
  input: RequestInfo | URL,
  init?: RequestInit & { skipAuthRedirect?: boolean },
): Promise<Response> {
  const { skipAuthRedirect, ...fetchInit } = init ?? {};
  const response = await fetch(input, { credentials: "include", ...fetchInit });

  if (
    response.status === 401 &&
    runtimeAuthEnabled &&
    !skipAuthRedirect &&
    typeof window !== "undefined"
  ) {
    window.location.href = loginHref(browserReturnPath(window.location));
    return new Promise(() => {});
  }

  return response;
}

function correlationId(response: Response): string | undefined {
  return (
    response.headers.get("x-correlation-id") ??
    response.headers.get("x-request-id") ??
    undefined
  );
}

function messageFromBody(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const value = body as Record<string, unknown>;
  if (typeof value.message === "string" && value.message.trim())
    return value.message;
  if (typeof value.detail === "string" && value.detail.trim())
    return value.detail;
  if (value.detail && typeof value.detail === "object") {
    const detail = value.detail as Record<string, unknown>;
    if (typeof detail.message === "string" && detail.message.trim())
      return detail.message;
  }
  return fallback;
}

function normalizedHttpError(
  response: Response,
  body: unknown,
  scope: AppErrorScope,
): AppError {
  const value =
    body && typeof body === "object" ? (body as Record<string, unknown>) : {};
  const detail =
    value.detail && typeof value.detail === "object"
      ? (value.detail as Record<string, unknown>)
      : {};
  return {
    code:
      (typeof value.error_code === "string" && value.error_code) ||
      (typeof detail.error_code === "string" && detail.error_code) ||
      `http_${response.status}`,
    message: messageFromBody(body, response.statusText || "Request failed"),
    retryable:
      (typeof value.retryable === "boolean" && value.retryable) ||
      (typeof detail.retryable === "boolean" && detail.retryable) ||
      response.status === 408 ||
      response.status === 429 ||
      response.status >= 500,
    scope,
    correlationId:
      (typeof value.correlation_id === "string" && value.correlation_id) ||
      correlationId(response),
    status: response.status,
  };
}

async function responseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text.trim()) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

async function performRequest(
  input: RequestInfo | URL,
  options: RequestOptions = {},
): Promise<{ response: Response; body: unknown }> {
  const { scope = "network", ...init } = options;
  try {
    const response = await apiFetch(input, init);
    const body = await responseBody(response);
    if (!response.ok)
      throw new ApiError(normalizedHttpError(response, body, scope));
    return { response, body };
  } catch (error) {
    if (error instanceof ApiError) throw error;
    const aborted =
      error instanceof DOMException && error.name === "AbortError";
    throw new ApiError(
      {
        code: aborted ? "request_aborted" : "network_error",
        message: aborted
          ? "Request was cancelled"
          : "Unable to reach the server",
        retryable: !aborted,
        scope,
      },
      { cause: error },
    );
  }
}

export async function requestJson<T>(
  input: RequestInfo | URL,
  options: RequestOptions = {},
): Promise<T> {
  const { response, body } = await performRequest(input, options);
  if (body === undefined || typeof body === "string") {
    throw new ApiError({
      code: "invalid_response",
      message: "The server returned an invalid JSON response",
      retryable: true,
      scope: options.scope ?? "network",
      correlationId: correlationId(response),
      status: response.status,
    });
  }
  return body as T;
}

export async function requestVoid(
  input: RequestInfo | URL,
  options: RequestOptions = {},
): Promise<void> {
  await performRequest(input, options);
}

export async function requestBlob(
  input: RequestInfo | URL,
  options: RequestOptions = {},
): Promise<Blob> {
  const { scope = "network", ...init } = options;
  try {
    const response = await apiFetch(input, init);
    if (!response.ok) {
      const body = await responseBody(response);
      throw new ApiError(normalizedHttpError(response, body, scope));
    }
    return await response.blob();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    const aborted =
      error instanceof DOMException && error.name === "AbortError";
    throw new ApiError(
      {
        code: aborted ? "request_aborted" : "network_error",
        message: aborted
          ? "Request was cancelled"
          : "Unable to reach the server",
        retryable: !aborted,
        scope,
      },
      { cause: error },
    );
  }
}

/**
 * Parse a response, throwing FastAPI's ``detail`` as the message on failure.
 *
 * The status line alone ("500 Internal Server Error") tells a reader nothing;
 * the backend's own detail is what names the actual problem. Callers wanting
 * structured refusals (an error code, a log tail) parse the body themselves.
 */
export async function asJsonOrThrow(response: Response): Promise<any> {
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* the body was not JSON; the status line is all we have */
    }
    throw new Error(detail);
  }
  return response.json();
}
