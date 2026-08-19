import { forwardBackendUpload } from "@/lib/streaming-upload-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function POST(request: Request): Promise<Response> {
  return forwardBackendUpload(request);
}
