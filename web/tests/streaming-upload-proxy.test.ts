import test from "node:test";
import assert from "node:assert/strict";
import { forwardBackendUpload } from "../lib/streaming-upload-proxy";

type StreamingRequestInit = RequestInit & { duplex: "half" };

test("upload proxy streams the original body and preserves the backend response", async () => {
  const request = new Request(
    "http://frontend.test/api/v1/knowledge/create?source=web",
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
        "http://127.0.0.1:8123/api/v1/knowledge/create?source=web",
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
