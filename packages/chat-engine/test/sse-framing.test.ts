import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { sse } from "../src/providers/sse.js";
import { complete } from "../src/providers/chat-completions.js";

function stream(text: string, fragmented = false) {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      const bytes = new TextEncoder().encode(text);
      if (fragmented) {
        for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
      } else controller.enqueue(bytes);
      controller.close();
    },
  });
}

async function collect(text: string, fragmented = false) {
  const events = [];
  for await (const event of sse(
    stream(text, fragmented),
    new AbortController().signal,
  ))
    events.push(event);
  return events;
}

for (const fragmented of [false, true]) {
  test(`SSE accepts CR, LF and CRLF independently (fragmented=${fragmented})`, async () => {
    assert.deepEqual(
      await collect(
        ":comment\rdata: 中文😀\rdata: next\r\rdata: second\n\ndata: third\r\n\r\n",
        fragmented,
      ),
      ["中文😀\nnext", "second", "third"],
    );
  });
}

test("a CR ending a chunk dispatches without waiting for another read", async () => {
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode("data: ready\r\r"));
    },
    cancel() {
      cancelled = true;
    },
  });
  const events = sse(body, new AbortController().signal, 30);
  try {
    assert.equal((await events.next()).value, "ready");
  } finally {
    await events.return(undefined);
  }
  assert.equal(cancelled, true);
});

test("line limit applies to individual lines rather than a coalesced read", async () => {
  const payload = "a".repeat(2_100_000);
  const events = await collect(`data: ${payload}\n\ndata: ${payload}\n\n`);
  assert.deepEqual(events, [payload, payload]);
});

test("line limits still reject one oversized line after an earlier event", async () => {
  await assert.rejects(
    collect(`data: valid\r\r: ${"x".repeat(4_194_305)}\r`),
    /line exceeds/,
  );
});

test("multiple data fields still share one event limit with CR framing", async () => {
  await assert.rejects(
    collect(
      `data: ${"x".repeat(2_100_000)}\rdata: ${"x".repeat(2_100_000)}\r\r`,
    ),
    /event exceeds/,
  );
});

test("EOF data shares the event limit with preceding terminated fields", async () => {
  await assert.rejects(
    collect(`data: ${"x".repeat(2_100_000)}\ndata: ${"x".repeat(2_100_000)}`),
    /event exceeds/,
  );
});

test("empty reads between CR and LF do not create an event boundary", async () => {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const text of [
        "data: first\r",
        "",
        "\ndata: second\r",
        "",
        "\n\r",
        "",
        "\n",
      ])
        controller.enqueue(new TextEncoder().encode(text));
      controller.close();
    },
  });
  const events = [];
  for await (const event of sse(body, new AbortController().signal))
    events.push(event);
  assert.deepEqual(events, ["first\nsecond"]);
});

test("the native HTTP completion preserves CR-framed text, tool identity and usage", async () => {
  let requests = 0;
  const server = createServer(async (request, response) => {
    for await (const _ of request) {
      /* drain request */
    }
    requests++;
    response.writeHead(200, { "content-type": "text/event-stream" });
    const frames = [
      {
        choices: [
          {
            delta: {
              content: "中文😀",
              tool_calls: [
                {
                  index: 0,
                  id: "call-1",
                  function: { name: "lookup", arguments: '{"key":' },
                },
              ],
            },
          },
        ],
      },
      {
        choices: [
          {
            delta: {
              tool_calls: [{ index: 0, function: { arguments: '"source"}' } }],
            },
            finish_reason: "tool_calls",
          },
        ],
      },
      {
        choices: [],
        usage: { prompt_tokens: 7, completion_tokens: 3, total_tokens: 10 },
      },
    ];
    response.end(
      frames.map((frame) => `data: ${JSON.stringify(frame)}\r\r`).join("") +
        "data: [DONE]\r\r",
    );
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  try {
    const result = await complete(
      {
        endpoint: `http://127.0.0.1:${address.port}`,
        model: "fixture",
        apiKey: "",
        headers: {},
        format: "chat_completions",
        completion: {},
        stream: true,
        maxConcurrency: 1,
        requestsPerMinute: 600,
        retryDelaysMs: [],
      },
      [],
      [],
      null,
      new AbortController().signal,
      async () => {},
    );
    assert.equal(result.text, "中文😀");
    assert.deepEqual(result.calls, [
      { id: "call-1", name: "lookup", arguments: '{"key":"source"}' },
    ]);
    assert.equal(result.usage.total_tokens, 10);
    assert.equal(result.finishReason, "tool_calls");
    assert.equal(requests, 1);
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
