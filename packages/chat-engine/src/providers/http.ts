/** Small streaming HTTP transport; no SDK or fetch/Undici client lifetime. */
import { Agent as HttpAgent, request as httpRequest } from "node:http";
import { Agent as HttpsAgent, request as httpsRequest } from "node:https";
import { Readable } from "node:stream";
import { createBrotliDecompress, createGunzip, createInflate } from "node:zlib";

const options = {
  keepAlive: true,
  maxSockets: 128,
  maxTotalSockets: 128,
  maxFreeSockets: 8,
  timeout: 30_000,
};
const httpAgent = new HttpAgent(options),
  httpsAgent = new HttpsAgent(options);

export function post(
  endpoint: string,
  headers: Record<string, string>,
  payload: string,
  signal: AbortSignal,
): Promise<{
  status: number;
  ok: boolean;
  contentType: string;
  body: ReadableStream<Uint8Array>;
}> {
  signal.throwIfAborted();
  const url = new URL(endpoint);
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password
  )
    throw new Error("Invalid provider endpoint");
  return new Promise((resolve, reject) => {
    const secure = url.protocol === "https:";
    const request = (secure ? httpsRequest : httpRequest)(
      url,
      {
        method: "POST",
        signal,
        agent: secure ? httpsAgent : httpAgent,
        headers: { ...headers, "Content-Length": Buffer.byteLength(payload) },
      },
      (response) => {
        // Redirects never forward credentials to a different destination.
        const status = response.statusCode || 0;
        if (status >= 300 && status < 400) {
          response.destroy();
          reject(new Error("Model provider redirected the request"));
          return;
        }
        const encoding = String(
          response.headers["content-encoding"] || "",
        ).toLowerCase();
        const decompress =
          encoding === "gzip"
            ? createGunzip()
            : encoding === "deflate"
              ? createInflate()
              : encoding === "br"
                ? createBrotliDecompress()
                : null;
        if (encoding && encoding !== "identity" && !decompress) {
          response.destroy();
          reject(new Error("Unsupported provider content encoding"));
          return;
        }
        const stream = decompress ? response.pipe(decompress) : response;
        if (decompress) {
          response.on("error", (error) => decompress.destroy(error));
          decompress.on("close", () => response.destroy());
        }
        resolve({
          status,
          ok: status >= 200 && status < 300,
          contentType: String(response.headers["content-type"] || ""),
          body: Readable.toWeb(stream) as ReadableStream<Uint8Array>,
        });
      },
    );
    request.on("error", reject);
    request.end(payload);
  });
}
