import { test } from "node:test";
import assert from "node:assert/strict";
import { readBody } from "../src/providers/body.js";
import { sse } from "../src/providers/sse.js";
import { withProviderLimit } from "../src/providers/limits.js";
import {
  planHistory,
  historyTokens,
  type HistoryInput,
} from "../src/context/history.js";
import { Conversation } from "../src/context/conversation.js";
import type { ProviderConfig, Round } from "../src/native/types.js";
import { createServer } from "node:http";
import { askUser } from "../src/tools/ask-user.js";
import { AskUserDraft } from "../src/tools/ask-user-draft.js";
import type { EngineEvent } from "../src/native/types.js";
import { complete } from "../src/providers/chat-completions.js";
import { gzipSync } from "node:zlib";

const signal = () => new AbortController().signal;
const provider: ProviderConfig = {
  endpoint: "http://fixture",
  model: "test",
  apiKey: "fixture",
  headers: {},
  format: "chat_completions",
  completion: {},
  stream: true,
  maxConcurrency: 1,
  requestsPerMinute: 600,
};
function bytes(text: string) {
  const data = new TextEncoder().encode(text);
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const byte of data) controller.enqueue(Uint8Array.of(byte));
      controller.close();
    },
  });
}

test("SSE handles fragmented UTF-8, comments, multiple data fields and CRLF", async () => {
  const events = [];
  for await (const event of sse(
    bytes(":keepalive\r\ndata: 中文😀\r\ndata: next\r\n\r\ndata: [DONE]\n\n"),
    signal(),
  ))
    events.push(event);
  assert.deepEqual(events, ["中文😀\nnext", "[DONE]"]);
});

test("bounded body reads and SSE reject stalled, malformed or oversized responses", async () => {
  assert.equal(await readBody(bytes("中文😀"), signal(), 100), "中文😀");
  await assert.rejects(
    readBody(bytes("x".repeat(100)), signal(), 20),
    /exceeds/,
  );
  let cancelled = false;
  await assert.rejects(
    readBody(
      new ReadableStream({
        cancel() {
          cancelled = true;
        },
      }),
      signal(),
      100,
      5,
    ),
    /timeout/,
  );
  assert.equal(cancelled, true);
  const collect = async () => {
    for await (const _ of sse(new ReadableStream(), signal(), 5)) {
      /* no events */
    }
  };
  await assert.rejects(collect(), /timeout/);
  await assert.rejects(
    readBody(
      new ReadableStream({
        start(c) {
          c.enqueue(Uint8Array.of(0xff));
          c.close();
        },
      }),
      signal(),
      10,
    ),
    /encoded/,
  );
});

test("model admission is shared, bounded, abortable and isolated by provider identity", async () => {
  let release!: () => void, entered!: () => void;
  const admitted = new Promise<void>((resolve) => {
    entered = resolve;
  });
  const first = withProviderLimit(provider, signal(), async () => {
    entered();
    await new Promise<void>((resolve) => {
      release = resolve;
    });
  });
  await admitted;
  let effects = 0;
  const controller = new AbortController();
  const waiting = withProviderLimit(provider, controller.signal, async () => {
    effects++;
  });
  await withProviderLimit(
    { ...provider, apiKey: "different-owner" },
    signal(),
    async () => {
      effects++;
    },
  );
  assert.equal(effects, 1);
  controller.abort(new Error("cancelled queue"));
  await assert.rejects(waiting, /cancelled queue/);
  release();
  await first;
  await withProviderLimit(provider, signal(), async () => {
    effects++;
  });
  assert.equal(effects, 2);
});

function history(endpoint: string): HistoryInput {
  return {
    groups: Array.from({ length: 6 }, (_, i) => ({
      messages: [
        { role: "user", content: `turn ${i} ` + "detail ".repeat(100) },
        { role: "assistant", content: "response " + "detail ".repeat(100) },
      ],
    })),
    summary: "previous summary",
    archivedTranscript: "original archived transcript",
    budget: 1500,
    recentBudget: 800,
    summaryBudget: 200,
    rebuildBudget: 4000,
    language: "zh",
    provider: { ...provider, endpoint, stream: false },
  };
}

test("native history summarizes only the removed prefix and retains complete recent turns", async () => {
  let request: Record<string, any> = {};
  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    request = JSON.parse(Buffer.concat(chunks).toString());
    res.end(
      JSON.stringify({
        choices: [
          { message: { content: "Faithful summary" }, finish_reason: "stop" },
        ],
      }),
    );
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  try {
    const input = history(`http://127.0.0.1:${address.port}`);
    const result = await planHistory(
      input,
      async (op) => {
        assert.equal(op, "event");
      },
      signal(),
    );
    assert.equal(result.summary, "Faithful summary");
    assert.ok(result.summarizedGroups > 0);
    assert.equal(result.retainedStart, result.summarizedGroups);
    assert.match(request.messages[0].content, /Chinese/);
    assert.match(request.messages[1].content, /original archived transcript/);
    assert.ok(!request.messages[1].content.includes("turn 5"));
    assert.ok(result.tokenCount <= input.budget);
    assert.equal(input.groups.length, 6);
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});

test("summary failure never advances the watermark, while bounded history preserves latest turn", async () => {
  const input = history("http://invalid");
  input.provider.format = "chat_completions";
  // Reject the model request before networking via an already-aborted signal.
  const controller = new AbortController();
  controller.abort(new Error("cancel history"));
  await assert.rejects(
    planHistory(input, async () => null, controller.signal),
    /cancel history/,
  );
  input.groups = input.groups.slice(0, 1);
  const retained = await planHistory(
    input,
    async () => {
      throw new Error("No summary needed");
    },
    signal(),
  );
  assert.equal(retained.summarizedGroups, 0);
  assert.equal(retained.retainedStart, 0);
  const image = {
    role: "user",
    content: [
      {
        type: "image_url",
        image_url: { url: "data:image/png;base64,fixture" },
      },
    ],
  };
  assert.ok(historyTokens([image, image]) < 5000);
});

test("context checkpoints compact request projection without erasing durable tool evidence", () => {
  const conversation = new Conversation({
    system: "system",
    history: [],
    user: { role: "user", content: "task" },
    snapshots: {},
    model: "fixture",
    route: {},
    contextWindow: 32000,
    outputTokens: 128,
  });
  const round: Round = {
    text: "",
    reasoning: "",
    toolCalls: [{ id: "a", name: "read", arguments: "{}" }],
    usage: {},
    finishReason: "tool_calls",
    trace: {},
    deferred: [],
    requestTools: [],
  };
  conversation.appendAssistant(round);
  conversation.appendTools(
    [{ role: "tool", tool_call_id: "a", content: "evidence" }],
    [
      {
        role: "user",
        content: [
          {
            type: "image_url",
            image_url: { url: "data:image/png;base64,fixture" },
          },
        ],
      },
    ],
  );
  conversation.appendAssistant({ ...round, text: "response", toolCalls: [] });
  const projected = conversation.project([]).messages;
  assert.equal(projected.at(-1)!.content, "response");
  assert.equal(projected.at(-2)!.role, "user");
  conversation.foldCheckpoint("summary of evidence");
  assert.ok(
    !JSON.stringify(conversation.project([]).messages).includes(
      '"tool_call_id"',
    ),
  );
  assert.match(JSON.stringify(conversation.checkpoint()), /evidence/);
  assert.match(
    JSON.stringify(conversation.project([]).messages),
    /summary of evidence/,
  );
});

test("ask_user preserves option uniqueness, explicit Other, ID repair and Unicode bounds", () => {
  const output = askUser({
    questions: [
      {
        id: "same",
        prompt: "Question",
        options: [
          " A ",
          "a",
          "Other",
          { label: "B", description: "same body" },
          { label: "C", description: " SAME  BODY " },
        ],
      },
      {
        id: "same",
        prompt: "😀".repeat(801),
        multiSelect: true,
        allow_free_text: false,
        options: ["Other"],
      },
    ],
  });
  const questions = output.pause!.questions as Record<string, any>[];
  assert.deepEqual(
    questions[0]!.options.map((o: { label: string }) => o.label),
    ["A", "B"],
  );
  assert.equal(questions[1]!.id, "same_2");
  assert.equal(questions[1]!.multi_select, true);
  assert.equal([...questions[1]!.prompt].length, 801);
  assert.equal(questions[1]!.options[0].label, "Other");
});

test("ask_user drafts appear before closing JSON and never shrink or execute effects", async () => {
  const events: EngineEvent[] = [],
    draft = new AskUserDraft(async (event) => {
      events.push(event);
    }, {});
  const call = {
    id: "question-1",
    name: "ask_user",
    arguments: '{"questions":[{"prompt":"Which topic?","options":["Math"',
  };
  await draft.observe(call);
  assert.equal(events.length, 1);
  assert.equal(events[0]!.metadata.trace_kind, "ask_user_draft");
  await draft.observe(
    { ...call, arguments: '{"questions":[{"prompt":"Which topic?"' },
    true,
  );
  assert.equal(events.length, 1);
  await draft.observe(
    { ...call, arguments: call.arguments + ',"Physics"]}]}' },
    true,
  );
  assert.equal(events.length, 2);
  await draft.observe(
    { ...call, arguments: call.arguments + ',"Physics"]}]}' },
    true,
  );
  assert.equal(events.length, 2);
});

test("HTTP provider retries only safe compatibility rejection and decodes compressed usage frames", async () => {
  const requests: Record<string, any>[] = [];
  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString());
    requests.push(body);
    assert.equal(req.headers.authorization, "Custom fixture authorization");
    if (body.stream_options) {
      res.writeHead(400);
      res.end("unsupported stream_options");
      return;
    }
    res.writeHead(200, {
      "content-type": "text/event-stream",
      "content-encoding": "gzip",
    });
    const data =
      [
        {
          choices: [
            {
              delta: { reasoning_content: "think", content: "中文😀" },
              finish_reason: "stop",
            },
          ],
        },
        {
          choices: [],
          usage: { prompt_tokens: 13, completion_tokens: 5, total_tokens: 18 },
        },
      ]
        .map((x) => `data: ${JSON.stringify(x)}\n\n`)
        .join("") + "data: [DONE]\n\n";
    res.end(gzipSync(data));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  try {
    const result = await complete(
      {
        ...provider,
        endpoint: `http://127.0.0.1:${address.port}`,
        headers: { authorization: "Custom fixture authorization" },
      },
      [],
      [],
      null,
      signal(),
      async () => {},
    );
    assert.equal(result.text, "中文😀");
    assert.equal(result.reasoning, "think");
    assert.equal(result.usage.total_tokens, 18);
    assert.equal(requests.length, 2);
    assert.equal(requests[1]!.stream_options, undefined);
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});

test("history summary rejection keeps the previous watermark and complete newest group", async () => {
  let calls = 0;
  const server = createServer(async (req, res) => {
    for await (const _ of req) {
      /* consume */
    }
    calls++;
    res.writeHead(401);
    res.end("fixture rejected");
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  try {
    const input = history(`http://127.0.0.1:${address.port}`);
    const result = await planHistory(input, async () => null, signal());
    assert.equal(calls, 1);
    assert.equal(result.summarizedGroups, 0);
    assert.equal(result.summary, input.summary);
    assert.ok(
      result.retainedStart > 0 && result.retainedStart < input.groups.length,
    );
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});

test("incomplete or tool-producing summaries cannot replace durable history", async () => {
  let finish = "length";
  const server = createServer(async (req, res) => {
    for await (const _ of req) {
      /* consume */
    }
    res.end(
      JSON.stringify({
        choices: [
          {
            message: {
              content:
                "A plausible complete sentence.\nBut missing the remaining facts",
              ...(finish === "tool_calls"
                ? {
                    tool_calls: [
                      {
                        id: "unexpected",
                        type: "function",
                        function: { name: "tool", arguments: "{}" },
                      },
                    ],
                  }
                : {}),
            },
            finish_reason: finish,
          },
        ],
      }),
    );
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  try {
    for (finish of [
      "length",
      "max_tokens",
      "max_output_tokens",
      "content_filter",
      "tool_calls",
    ]) {
      const value = history(`http://127.0.0.1:${address.port}`);
      const events: EngineEvent[] = [];
      const planned = await planHistory(
        value,
        async (_op, args) => {
          events.push(args.event as EngineEvent);
        },
        signal(),
      );
      assert.equal(planned.summary, value.summary, finish);
      assert.equal(planned.summarizedGroups, 0, finish);
      assert.equal(events.at(-1)!.metadata.call_state, "error", finish);
    }
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
