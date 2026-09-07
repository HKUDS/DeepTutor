import test from "node:test";
import assert from "node:assert/strict";
import { forwardBackendUpload } from "../lib/streaming-upload-proxy";

type StreamingRequestInit = RequestInit & { duplex: "half" };

test("upload proxy streams the original body and preserves the backend response", async () => {
  const request = new Request(
    "http://frontend.test/api/knowledge-bases?source=web",
    {
      method: "POST",
      headers: {
        connection: "keep-alive, x-remove-me",
        "content-type": "multipart/form-data; boundary=example",
        cookie: "deeptutor_session=token",
        host: "frontend.test",
        "x-remove-me": "transport-only",
      },
      body: new Blob(["multipart bytes"]).stream(),
      duplex: "half",
    } as StreamingRequestInit,
  );

  const response = await forwardBackendUpload(request, {
    apiBaseUrl: "http://127.0.0.1:8123",
    fetchImpl: async (input, init) => {
      assert.equal(
        String(input),
        "http://127.0.0.1:8123/api/knowledge-bases?source=web",
      );
      assert.equal(init?.method, "POST");
      const headers = new Headers(init?.headers);
      assert.equal(
        headers.get("content-type"),
        "multipart/form-data; boundary=example",
      );
      assert.equal(headers.get("cookie"), "deeptutor_session=token");
      assert.equal(headers.has("connection"), false);
      assert.equal(headers.has("host"), false);
      assert.equal(headers.has("x-remove-me"), false);
      assert.equal((init as StreamingRequestInit).duplex, "half");
      assert.equal(await new Response(init?.body).text(), "multipart bytes");

      return new Response('{"task_id":"kb_init_1"}', {
        status: 202,
        headers: {
          connection: "close",
          "content-type": "application/json",
          "x-backend": "fastapi",
        },
      });
    },
  });

  assert.equal(response.status, 202);
  assert.equal(response.headers.get("content-type"), "application/json");
  assert.equal(response.headers.get("x-backend"), "fastapi");
  assert.equal(response.headers.has("connection"), false);
  assert.equal(await response.text(), '{"task_id":"kb_init_1"}');
});

test("upload proxy drops the client's Expect header before forwarding", async () => {
  // A proxy sitting in front of the browser (or curl past 1KB) adds
  // `Expect: 100-continue` once the body is large enough. Node answered it
  // already; replaying it makes undici throw and the forward dies mid-upload.
  const request = new Request(
    "http://frontend.test/api/knowledge-bases/kb/upload",
    {
      method: "POST",
      headers: {
        "content-type": "multipart/form-data; boundary=example",
        expect: "100-continue",
      },
      body: new Blob(["multipart bytes"]).stream(),
      duplex: "half",
    } as StreamingRequestInit,
  );

  const response = await forwardBackendUpload(request, {
    apiBaseUrl: "http://127.0.0.1:8123",
    fetchImpl: async (_input, init) => {
      assert.equal(new Headers(init?.headers).has("expect"), false);
      return new Response('{"task_id":"kb_upload_1"}', { status: 200 });
    },
  });

  assert.equal(response.status, 200);
});
