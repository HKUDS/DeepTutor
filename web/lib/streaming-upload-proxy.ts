import { resolveBackendApiBase } from "./backend-runtime-config";

// HTTP/1.1 hop-by-hop headers describe one transport connection and must not
// be replayed on the independent frontend -> backend connection.
//
// ``expect`` belongs here too: Node's server already answered the client's
// ``100-continue`` before this handler ever ran, so the negotiation is over.
// Replaying it is not merely redundant — undici rejects any request carrying
// the header ("expect header not supported"), which fails the forward *mid
// upload*. The browser, still writing the body, never reads that 500 and
// reports a bare "Failed to fetch". Only clients that add the header for
// large bodies are affected (curl past 1KB, and TUN/HTTP proxies in front of
// the browser), which is why the breakage looks size-dependent.
const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "expect",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

type StreamingRequestInit = RequestInit & { duplex?: "half" };

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
  const apiBaseUrl = dependencies.apiBaseUrl || resolveBackendApiBase();
  const fetchImpl = dependencies.fetchImpl || globalThis.fetch;
  const incomingUrl = new URL(request.url);
  const upstreamUrl = new URL(
    incomingUrl.pathname + incomingUrl.search,
    apiBaseUrl,
  );

  const init: StreamingRequestInit = {
    method: request.method,
    headers: forwardedHeaders(request.headers, { request: true }),
    signal: request.signal,
    redirect: "manual",
  };
  if (
    request.body !== null &&
    request.method !== "GET" &&
    request.method !== "HEAD"
  ) {
    init.body = request.body;
    init.duplex = "half";
  }
  const upstream = await fetchImpl(upstreamUrl, init);

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: forwardedHeaders(upstream.headers, { request: false }),
  });
}
