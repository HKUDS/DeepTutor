export const FRONTEND_HOST_HEADER = "x-deeptutor-frontend-host";

const UNTRUSTED_FORWARD_HEADERS = [
  "connection",
  "upgrade",
  "forwarded",
  "x-forwarded-host",
  "x-forwarded-proto",
  "x-forwarded-for",
  "x-forwarded-port",
  "x-forwarded-server",
  "x-real-ip",
  "x-client-ip",
  "x-host",
  "x-original-host",
  FRONTEND_HOST_HEADER,
];

export function prepareBackendForwardHeaders(
  source: Headers,
  { allowWebSocketUpgrade = false }: { allowWebSocketUpgrade?: boolean } = {},
): Headers {
  // NextRequest.nextUrl.host is the Next server's bind address in standalone
  // and source deployments. The HTTP Host header carries the requested
  // frontend host through Next's proxy, including when TLS ends upstream.
  const frontendHost = source.get("host");
  const headers = new Headers(source);
  const connectionTokens = (headers.get("connection") || "")
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
  const isWebSocketUpgrade =
    allowWebSocketUpgrade &&
    connectionTokens.includes("upgrade") &&
    headers.get("upgrade")?.trim().toLowerCase() === "websocket";

  for (const name of [...UNTRUSTED_FORWARD_HEADERS, ...connectionTokens]) {
    headers.delete(name);
  }
  // Next applies this header set to the original upgrade request before
  // proxying it. Restore only the WebSocket handshake, not other hop-by-hop
  // headers named by the client in Connection.
  if (isWebSocketUpgrade) {
    headers.set("connection", "Upgrade");
    headers.set("upgrade", "websocket");
  }
  if (frontendHost) headers.set(FRONTEND_HOST_HEADER, frontendHost);
  return headers;
}
