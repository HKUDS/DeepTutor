const DEFAULT_API_BASE_URL = "http://127.0.0.1:8001";

// HTTP/1.1 hop-by-hop headers describe one transport connection and must not
// be replayed on the independent frontend -> backend connection.
const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

type StreamingRequestInit = RequestInit & { duplex: "half" };

export interface UploadProxyDependencies {
  apiBaseUrl?: string;
  fetchImpl?: typeof fetch;
}

function forwardedHeaders(source: Headers, { request }: { request: boolean }) {
  const headers = new Headers(source);
  const connectionTokens = (headers.get("connection") || "")
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);

  for (const name of [...HOP_BY_HOP_HEADERS, ...connectionTokens]) {
    headers.delete(name);
  }
  if (request) headers.delete("host");
  return headers;
}

/**
 * Stream a large multipart upload to FastAPI without materializing it in the
 * Next.js process. The two matching App Router endpoints are excluded from
 * `proxy.ts`, whose automatic request clone otherwise truncates large batches.
 */
export async function forwardBackendUpload(
  request: Request,
  dependencies: UploadProxyDependencies = {},
): Promise<Response> {
  const apiBaseUrl =
    dependencies.apiBaseUrl ||
    process.env.DEEPTUTOR_API_BASE_URL ||
    DEFAULT_API_BASE_URL;
  const fetchImpl = dependencies.fetchImpl || globalThis.fetch;
  const incomingUrl = new URL(request.url);
  const upstreamUrl = new URL(
    incomingUrl.pathname + incomingUrl.search,
    apiBaseUrl,
  );

  const init: StreamingRequestInit = {
    method: request.method,
    headers: forwardedHeaders(request.headers, { request: true }),
    body: request.body,
    signal: request.signal,
    redirect: "manual",
    duplex: "half",
  };
  const upstream = await fetchImpl(upstreamUrl, init);

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: forwardedHeaders(upstream.headers, { request: false }),
  });
}
