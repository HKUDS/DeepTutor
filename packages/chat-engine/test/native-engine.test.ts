import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer, type ServerResponse } from "node:http";
import { mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runNative } from "../src/native/session.js";
import type {
  EngineEvent,
  JsonRecord,
  NativeInput,
} from "../src/native/types.js";
import { complete } from "../src/providers/chat-completions.js";
import { Conversation } from "../src/context/conversation.js";
import { ThinkFilter } from "../src/providers/think-filter.js";
import { workspaceTool } from "../src/tools/workspace.js";

function input(endpoint: string): NativeInput {
  return {
    config: {
      explorationBudget: 3,
      settlementBudget: 3,
      emptyRecoveryBudget: 2,
    },
    provider: {
      endpoint,
      apiKey: "fixture-secret",
      headers: {},
      model: "fixture",
      format: "chat_completions",
      completion: { max_tokens: 128 },
      stream: true,
      maxConcurrency: 2,
      requestsPerMinute: 600,
    },
    seed: {
      system: "System",
      history: [],
      snapshots: {},
      user: { role: "user", content: "Fixture" },
      contextWindow: 32000,
      outputTokens: 128,
      model: "fixture",
      route: { provider: "fixture", model: "fixture" },
    },
    tools: [],
    source: "chat",
    stage: "responding",
    sessionId: "test",
    workspace: null,
    skillRoots: {},
    rebindingTools: [],
    deferOutput: false,
    policyHooks: false,
    initialToolChoice: null,
    copy: {},
  };
}
function frame(
  response: ServerResponse,
  delta: JsonRecord,
  finish: string | null = null,
) {
  response.write(
    `data: ${JSON.stringify({ choices: [{ delta, finish_reason: finish }] })}\r\n\r\n`,
  );
}
function answer(response: ServerResponse, content = "Fixture answer") {
  frame(response, { content }, "stop");
  response.end("data: [DONE]\n\n");
}
async function server(
  handler: (
    body: JsonRecord,
    response: ServerResponse,
    count: number,
  ) => void | Promise<void>,
) {
  const requests: JsonRecord[] = [];
  const s = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString());
    requests.push(body);
    assert.equal(request.headers.authorization, "Bearer fixture-secret");
    response.writeHead(200, { "content-type": "text/event-stream" });
    try {
      await handler(body, response, requests.length);
    } catch (error) {
      response.destroy(error as Error);
    }
  });
  await new Promise<void>((resolve) => s.listen(0, "127.0.0.1", resolve));
  const address = s.address();
  assert.ok(address && typeof address !== "string");
  return {
    endpoint: `http://127.0.0.1:${address.port}/v1/chat/completions`,
    requests,
    close: async () => {
      s.closeAllConnections();
      await new Promise<void>((resolve) => s.close(() => resolve()));
    },
  };
}

test("native turn makes HTTP requests and maintains model history without Python model or context calls", async () => {
  const fixture = await server((_body, response) => answer(response));
  const events: EngineEvent[] = [],
    checkpoints: JsonRecord[] = [];
  try {
    const output = await runNative(
      input(fixture.endpoint),
      async (operation, args) => {
        if (operation === "event") {
          events.push(args.event as EngineEvent);
          return null;
        }
        if (operation === "checkpoint") {
          checkpoints.push(args.modelTurn as JsonRecord);
          return null;
        }
        throw new Error(`Unexpected Python port ${operation}`);
      },
      new AbortController().signal,
    );
    assert.equal(output.response, "Fixture answer");
    assert.equal(output.state.rounds, 1);
    assert.equal(output.legacyToolCalls, 0);
    assert.equal(fixture.requests.length, 1);
    assert.equal(
      events
        .filter((e) => e.type === "content")
        .map((e) => e.content)
        .join(""),
      output.response,
    );
    assert.equal(
      (checkpoints.at(-1)!.messages as JsonRecord[]).at(-1)!.role,
      "assistant",
    );
    assert.equal(output.contextBudget.counter, "character_estimate");
  } finally {
    await fixture.close();
  }
});

test("native workspace tool and ask_user execute, pause and resume with no Python tool dispatch", async () => {
  const root = await mkdtemp(join(tmpdir(), "native-tool-"));
  await writeFile(join(root, "fixture.txt"), "hello");
  const fixture = await server((body, response, count) => {
    if (count === 1) {
      frame(
        response,
        {
          tool_calls: [
            {
              index: 0,
              id: "list",
              function: { name: "workspace_list", arguments: "{}" },
            },
            {
              index: 1,
              id: "ask",
              function: {
                name: "ask_user",
                arguments: JSON.stringify({
                  questions: [
                    { id: "topic", prompt: "Topic?", options: ["Math"] },
                  ],
                }),
              },
            },
          ],
        },
        "tool_calls",
      );
      response.end("data: [DONE]\n\n");
    } else {
      const messages = body.messages as JsonRecord[];
      assert.match(
        String(messages.find((m) => m.tool_call_id === "list")?.content),
        /fixture.txt/,
      );
      assert.equal(
        messages.find((m) => m.tool_call_id === "ask")?.content,
        "User answered: Math",
      );
      answer(response);
    }
  });
  try {
    const value = input(fixture.endpoint);
    value.workspace = { root, id: "owner-a" };
    value.tools = ["workspace_list", "ask_user"].map((name) => ({
      schema: { type: "function", function: { name, parameters: {} } },
      native: true,
      sensitive: [],
    }));
    const output = await runNative(
      value,
      async (op) => {
        if (["event", "checkpoint"].includes(op)) return null;
        if (op === "wait_for_reply")
          return { resumed: true, content: "User answered: Math" };
        if (op === "after_tools") return {};
        throw new Error(`Unexpected legacy effect ${op}`);
      },
      new AbortController().signal,
    );
    assert.equal(output.nativeToolCalls, 2);
    assert.equal(output.legacyToolCalls, 0);
    assert.equal(output.state.rounds, 2);
  } finally {
    await fixture.close();
    await rm(root, { recursive: true });
  }
});

test("tool dispatcher rejects unadmitted names and deduplicates side effects", async () => {
  const fixture = await server((_body, response, count) => {
    if (count > 1) {
      answer(response);
      return;
    }
    frame(
      response,
      {
        tool_calls: ["a", "b", "c"].map((id, index) => ({
          index,
          id,
          function: {
            name: index < 2 ? "write_fixture" : "not_admitted",
            arguments: '{"value":1,"_workspace_id":"attacker"}',
          },
        })),
      },
      "tool_calls",
    );
    response.end("data: [DONE]\n\n");
  });
  let effects = 0;
  try {
    const value = input(fixture.endpoint);
    value.tools = [
      {
        schema: {
          type: "function",
          function: {
            name: "write_fixture",
            parameters: { required: ["value"] },
          },
        },
        native: false,
        sensitive: ["value"],
      },
    ];
    const output = await runNative(
      value,
      async (op, args) => {
        if (["checkpoint", "event"].includes(op)) {
          if (
            op === "event" &&
            (args.event as EngineEvent).type === "tool_call" &&
            (args.event as EngineEvent).metadata.tool_name === "write_fixture"
          )
            assert.equal(
              ((args.event as EngineEvent).metadata.args as JsonRecord).value,
              undefined,
            );
          return null;
        }
        if (op === "after_tools") return {};
        assert.equal(op, "legacy_tool");
        assert.equal(args.name, "write_fixture");
        assert.equal((args.args as JsonRecord)._workspace_id, undefined);
        effects++;
        return {
          content: "written",
          success: true,
          metadata: {},
          sources: [],
          pause: null,
          terminate: false,
          modelMessage: null,
        };
      },
      new AbortController().signal,
    );
    assert.equal(effects, 1);
    assert.equal(output.legacyToolCalls, 1);
    const messages = fixture.requests[1]!.messages as JsonRecord[];
    assert.equal(messages.filter((m) => m.role === "tool").length, 3);
  } finally {
    await fixture.close();
  }
});

test("provider never retries a broken stream after visible output", async () => {
  const fixture = await server((_body, response) => {
    frame(response, { content: "partial" });
    response.end();
  });
  try {
    await assert.rejects(
      complete(
        input(fixture.endpoint).provider,
        [],
        [],
        null,
        new AbortController().signal,
        async () => {},
      ),
      /closed before completion/,
    );
    assert.equal(fixture.requests.length, 1);
  } finally {
    await fixture.close();
  }
});

test("cancellation interrupts a provider stream and cannot start another round", async () => {
  const fixture = await server((_body, response) => {
    frame(response, { content: "partial" });
  });
  const controller = new AbortController();
  try {
    await assert.rejects(
      complete(
        input(fixture.endpoint).provider,
        [],
        [],
        null,
        controller.signal,
        async () => {
          controller.abort(new Error("cancelled"));
        },
      ),
      /cancelled/,
    );
    assert.equal(fixture.requests.length, 1);
  } finally {
    await fixture.close();
  }
});

test("context projects images, snapshots and tool budgets without mutating durable messages", () => {
  const seed = input("http://fixture").seed;
  seed.history = [
    {
      role: "user",
      content: [
        { type: "image_url", image_url: { url: "data:image/png;base64,same" } },
      ],
      _context_snapshot: "old",
    },
  ];
  seed.user = {
    role: "user",
    content: [
      { type: "image_url", image_url: { url: "data:image/png;base64,same" } },
      { type: "text", text: "current" },
    ],
  };
  const conversation = new Conversation(seed),
    before = JSON.stringify(conversation.messages);
  const projected = conversation.project([]);
  assert.equal(JSON.stringify(conversation.messages), before);
  assert.match(JSON.stringify(projected.messages), /already supplied/);
  assert.match(JSON.stringify(projected.messages), /now empty/);
  assert.ok(!JSON.stringify(projected.messages).includes("_context_snapshot"));
  seed.contextWindow = 200;
  seed.user = { role: "user", content: "x".repeat(3000) };
  seed.history = [];
  assert.throws(() => new Conversation(seed).project([]), /exceeds/);
});

test("native reads reject traversal, internal state and symlinks outside the admitted root", async () => {
  const root = await mkdtemp(join(tmpdir(), "native-root-")),
    outside = await mkdtemp(join(tmpdir(), "native-outside-"));
  await writeFile(join(outside, "secret.txt"), "not visible");
  await symlink(join(outside, "secret.txt"), join(root, "escape"));
  const value = input("http://fixture");
  value.workspace = { root, id: "owner-a" };
  try {
    for (const path of ["../secret.txt", ".deeptutor/settings.json", "escape"])
      await assert.rejects(
        workspaceTool(
          "workspace_read",
          { path },
          value,
          new AbortController().signal,
        ),
      );
    await writeFile(join(root, "unicode.txt"), "A😀中文B");
    const page = await workspaceTool(
      "workspace_read",
      { path: "unicode.txt", offset: 1, limit: 2 },
      value,
      new AbortController().signal,
    );
    assert.equal(page.content, "😀中");
  } finally {
    await rm(root, { recursive: true });
    await rm(outside, { recursive: true });
  }
});

test("inline thinking filter handles split tags without exposing them as content", () => {
  const filter = new ThinkFilter();
  const parts = ["<thi", "nk>private</th", "ink>answer"].flatMap((text) =>
    filter.feed(text),
  );
  parts.push(...filter.feed("", true));
  assert.equal(
    parts
      .filter(([kind]) => kind === "content")
      .map(([, s]) => s)
      .join(""),
    "answer",
  );
  assert.equal(
    parts
      .filter(([kind]) => kind === "thinking")
      .map(([, s]) => s)
      .join(""),
    "private",
  );
});

test("truncated tool batches never execute even syntactically complete calls", async () => {
  const fixture = await server((body, response, count) => {
    if (count > 1) {
      const results = (body.messages as JsonRecord[]).filter(
        (m) => m.role === "tool",
      );
      assert.equal(results.length, 2);
      assert.ok(results.every((m) => /truncated/.test(String(m.content))));
      answer(response, "Recovered safely");
      return;
    }
    frame(
      response,
      {
        tool_calls: [
          {
            index: 0,
            id: "complete",
            function: { name: "write_fixture", arguments: '{"value":1}' },
          },
          {
            index: 1,
            id: "partial",
            function: { name: "write_fixture", arguments: '{"value":' },
          },
        ],
      },
      "length",
    );
    response.end("data: [DONE]\n\n");
  });
  try {
    const value = input(fixture.endpoint);
    value.tools = [
      {
        schema: {
          type: "function",
          function: { name: "write_fixture", parameters: {} },
        },
        native: false,
        sensitive: [],
      },
    ];
    const output = await runNative(
      value,
      async (op) => {
        if (["event", "checkpoint"].includes(op)) return null;
        if (op === "after_tools") return {};
        assert.fail(`Truncated output must not execute ${op}`);
      },
      new AbortController().signal,
    );
    assert.equal(output.response, "Recovered safely");
    assert.equal(output.nativeToolCalls + output.legacyToolCalls, 0);
    assert.equal(fixture.requests.length, 2);
  } finally {
    await fixture.close();
  }
});

test("parallel tools publish completed results promptly and keep source order in model history", async () => {
  const { ToolDispatcher } = await import("../src/tools/dispatcher.js");
  let release!: () => void;
  const slow = new Promise<void>((resolve) => {
    release = resolve;
  });
  const published: string[] = [];
  const value = input("http://fixture");
  value.tools = ["slow", "fast"].map((name) => ({
    schema: { type: "function" as const, function: { name, parameters: {} } },
    native: false,
    sensitive: [],
  }));
  const dispatcher = new ToolDispatcher(
    value,
    async (_op, args) => {
      if (args.name === "slow") await slow;
      return {
        content: args.name,
        success: true,
        metadata: {},
        sources: [],
        pause: null,
        terminate: false,
        modelMessage: null,
      };
    },
    async (event) => {
      if (event.type === "tool_result") {
        published.push(event.content);
        if (event.content === "fast") release();
      }
    },
    new AbortController().signal,
  );
  const result = await dispatcher.run(
    [
      { id: "first", name: "slow", arguments: "{}" },
      { id: "second", name: "fast", arguments: "{}" },
    ],
    value.tools,
    1,
  );
  assert.deepEqual(published, ["fast", "slow"]);
  assert.deepEqual(
    result.messages.map((m) => m.tool_call_id),
    ["first", "second"],
  );
});

test("native reasoning tools use admitted credentials/context, count usage and never publish answer deltas", async () => {
  const { modelTool } = await import("../src/tools/model-tool.js");
  const events: EngineEvent[] = [];
  const fixture = await server((_body, response) => {
    frame(
      response,
      { content: "<think>private</think>Delegated answer" },
      "stop",
    );
    response.write(
      'data: {"choices":[],"usage":{"prompt_tokens":19,"completion_tokens":7}}\n\n',
    );
    response.end("data: [DONE]\n\n");
  });
  try {
    const config = input(fixture.endpoint);
    config.toolRuntime = Object.fromEntries(
      ["reason", "brainstorm"].map((name) => [
        name,
        {
          provider: config.provider,
          system: "Delegated system",
          context: "Trusted default context",
        },
      ]),
    );
    for (const name of ["reason", "brainstorm"]) {
      const result = await modelTool(
        name,
        { query: "Focus", topic: "Topic", api_key: "forged", model: "forged" },
        config,
        {},
        async (e) => {
          events.push(e);
        },
        new AbortController().signal,
      );
      assert.equal(result.content, "Delegated answer");
      assert.equal(result.usage?.prompt_tokens, 19);
      assert.equal(result.metadata.model, "fixture");
    }
    assert.equal(events.filter((e) => e.type === "content").length, 0);
    for (const request of fixture.requests) {
      assert.match(JSON.stringify(request.messages), /Trusted default context/);
      assert.equal(request.model, "fixture");
      assert.equal(request.tools, undefined);
    }
  } finally {
    await fixture.close();
  }
});

test("read_source only reads the scoped admission and rejects inherited ids", async () => {
  const { readSource } = await import("../src/tools/read-source.js");
  const config = input("http://127.0.0.1:1");
  config.toolRuntime = { read_source: { sources: { "nb-1": "私密😀" } } };
  const result = readSource(
    { source_id: "nb-1", source_index: { "nb-1": "forged" } },
    config,
  );
  assert.equal(result.content, "私密😀");
  assert.equal(result.metadata.char_count, 3);
  assert.equal(readSource({ source_id: "toString" }, config).success, false);
  assert.equal(readSource({ source_id: "nb-other" }, config).success, false);
});

test("cancelling a slow parallel tool preserves the completed result before publication", async () => {
  const controller = new AbortController();
  const checkpoints: JsonRecord[] = [];
  const fixture = await server((_body, response) => {
    frame(
      response,
      {
        tool_calls: ["fast", "slow"].map((name, index) => ({
          index,
          id: name,
          function: { name, arguments: "{}" },
        })),
      },
      "tool_calls",
    );
    response.end("data: [DONE]\n\n");
  });
  const config = input(fixture.endpoint);
  config.tools = ["fast", "slow"].map((name) => ({
    native: false,
    sensitive: [],
    schema: { type: "function", function: { name, parameters: {} } },
  }));
  try {
    await assert.rejects(
      runNative(
        config,
        async (operation, args) => {
          if (operation === "checkpoint") {
            checkpoints.push(args.modelTurn as JsonRecord);
            return null;
          }
          if (operation === "legacy_tool") {
            if (args.name === "slow")
              await new Promise((_, reject) =>
                controller.signal.addEventListener(
                  "abort",
                  () => reject(controller.signal.reason),
                  { once: true },
                ),
              );
            return {
              content: "Completed side effect",
              success: true,
              metadata: {},
              sources: [],
              pause: null,
              terminate: false,
              modelMessage: null,
            };
          }
          if (operation === "event") {
            const event = args.event as EngineEvent;
            if (
              event.type === "tool_result" &&
              event.metadata.tool_name === "fast"
            ) {
              const messages = checkpoints.at(-1)!.messages as JsonRecord[];
              assert.equal(
                messages.find((m) => m.tool_call_id === "fast")!.content,
                "Completed side effect",
              );
              assert.match(
                String(
                  messages.find((m) => m.tool_call_id === "slow")!.content,
                ),
                /interrupted/,
              );
              controller.abort(new Error("cancel slow"));
            }
            return null;
          }
          throw new Error(`Unexpected ${operation}`);
        },
        controller.signal,
      ),
      /cancel slow/,
    );
    assert.equal(fixture.requests.length, 1);
  } finally {
    await fixture.close();
  }
});

test("a parallel native model-tool batch shares transport and includes subcall usage in the turn", async () => {
  const fixture = await server((body, response, count) => {
    if (count === 1) {
      frame(
        response,
        {
          tool_calls: ["reason", "brainstorm"].map((name, index) => ({
            index,
            id: name,
            function: {
              name,
              arguments: JSON.stringify(
                name === "reason" ? { query: "solve" } : { topic: "ideas" },
              ),
            },
          })),
        },
        "tool_calls",
      );
      response.end("data: [DONE]\n\n");
    } else
      answer(
        response,
        (body.messages as JsonRecord[])[0]?.content === "Delegate"
          ? "Observation"
          : "Final answer",
      );
  });
  try {
    const config = input(fixture.endpoint);
    config.tools = ["reason", "brainstorm"].map((name) => ({
      native: true,
      sensitive: [],
      schema: {
        type: "function",
        function: { name, parameters: { type: "object" } },
      },
    }));
    config.toolRuntime = Object.fromEntries(
      ["reason", "brainstorm"].map((name) => [
        name,
        { provider: config.provider, system: "Delegate", context: "Trusted" },
      ]),
    );
    const events: EngineEvent[] = [];
    const result = await runNative(
      config,
      async (operation, args) => {
        assert.ok(["event", "checkpoint"].includes(operation), operation);
        if (operation === "event") events.push(args.event as EngineEvent);
        return null;
      },
      new AbortController().signal,
    );
    assert.equal(result.nativeToolCalls, 2);
    assert.equal(result.legacyToolCalls, 0);
    assert.equal(result.usage.length, 4);
    assert.equal(result.response, "Final answer");
    assert.equal(
      events
        .filter((e) => e.type === "content")
        .map((e) => e.content)
        .join(""),
      "Final answer",
    );
    assert.deepEqual(
      (fixture.requests.at(-1)!.messages as JsonRecord[])
        .filter((m) => m.role === "tool")
        .map((m) => m.tool_call_id),
      ["reason", "brainstorm"],
    );
  } finally {
    await fixture.close();
  }
});

test("native memory reads fixed scoped files, sees updates and keeps partner layers separate", async () => {
  const { mkdir } = await import("node:fs/promises");
  const { readMemory } = await import("../src/tools/read-memory.js");
  const root = await mkdtemp(join(tmpdir(), "native-memory-"));
  const own = join(root, "own"),
    shared = join(root, "shared");
  try {
    await mkdir(join(own, "L3"), { recursive: true });
    await mkdir(join(shared, "L3"), { recursive: true });
    await writeFile(join(own, "L3/preferences.md"), "Own preference 😀");
    await writeFile(join(shared, "L3/profile.md"), "Shared read-only");
    const config = input("http://127.0.0.1:1");
    config.toolRuntime = {
      read_memory: { memoryRoots: [own] },
      partner_read: { memoryRoots: [shared, own] },
    };
    const signal = new AbortController().signal;
    assert.equal(
      (await readMemory("read_memory", config, signal)).content,
      "Own preference 😀\n",
    );
    const partner = await readMemory("partner_read", config, signal);
    assert.match(
      partner.content,
      /Shared memory.*read-only[\s\S]*Shared read-only[\s\S]*Your own memory[\s\S]*Own preference/,
    );
    assert.equal(partner.metadata.has_shared, true);
    await writeFile(join(own, "L3/preferences.md"), "Updated");
    assert.equal(
      (await readMemory("read_memory", config, signal)).content,
      "Updated\n",
    );
    await symlink(join(shared, "L3/profile.md"), join(own, "L3/recent.md"));
    await assert.rejects(readMemory("read_memory", config, signal));
    assert.equal(
      await (
        await import("node:fs/promises")
      ).readFile(join(shared, "L3/profile.md"), "utf8"),
      "Shared read-only",
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("provider compatibility keeps tool use required and retries format rejection only before output", async () => {
  const bodies: JsonRecord[] = [];
  const fixture = createServer(async (request, response) => {
    const parts = [];
    for await (const part of request) parts.push(part);
    const body = JSON.parse(Buffer.concat(parts).toString());
    bodies.push(body);
    if (bodies.length === 1) {
      response.writeHead(400);
      response.end("Thinking mode does not support this tool_choice");
      return;
    }
    if (bodies.length === 2) {
      response.writeHead(400);
      response.end("response_format is not supported");
      return;
    }
    response.writeHead(200, { "content-type": "text/event-stream" });
    answer(response);
  });
  await new Promise<void>((resolve) => fixture.listen(0, "127.0.0.1", resolve));
  try {
    const address = fixture.address();
    assert.ok(address && typeof address !== "string");
    const config = input(`http://127.0.0.1:${address.port}/chat/completions`);
    config.provider.completion.response_format = { type: "json_object" };
    await complete(
      config.provider,
      [{ role: "user", content: "fixture" }],
      [{ type: "function", function: { name: "ask_user", parameters: {} } }],
      "ask_user",
      new AbortController().signal,
      async () => {},
    );
    assert.equal(bodies.length, 3);
    assert.equal(bodies[1]!.tool_choice, "required");
    assert.equal(bodies[2]!.tool_choice, "required");
    assert.equal(bodies[2]!.response_format, undefined);
  } finally {
    fixture.closeAllConnections();
    await new Promise<void>((resolve) => fixture.close(() => resolve()));
  }
});


test("a learner message received during a tool is read once before the next model round", async () => {
  const fixture = await server((_body, response, count) => {
    if (count > 1) return answer(response, "Only the discrete case.");
    frame(response, { tool_calls: [{ index: 0, id: "search-1", function: {
      name: "search_fixture", arguments: "{}",
    }}]}, "tool_calls");
    response.end("data: [DONE]\n\n");
  });
  const events: EngineEvent[] = [];
  let inbox: JsonRecord[] = [];
  try {
    const value = input(fixture.endpoint);
    value.userInputEnabled = true;
    value.tools = [{ schema: { type: "function", function: {
      name: "search_fixture", parameters: { type: "object", properties: {} },
    }}, native: false, sensitive: [] }];
    await runNative(value, async (op, args) => {
      if (op === "read_user_inputs") {
        const pending = inbox; inbox = []; return pending;
      }
      if (op === "event") { events.push(args.event as EngineEvent); return null; }
      if (op === "checkpoint") return null;
      if (op === "after_tools") return {};
      assert.equal(op, "legacy_tool");
      inbox.push({ command_id: "cmd-1", content: "Only cover the discrete case." });
      return { content: "found", success: true, metadata: {}, sources: [],
        pause: null, terminate: false, modelMessage: null };
    }, new AbortController().signal);
    assert.equal(fixture.requests.length, 2);
    assert.ok(!JSON.stringify(fixture.requests[0]).includes("Only cover the discrete case."));
    assert.ok(JSON.stringify(fixture.requests[1]).includes("Only cover the discrete case."));
    const read = events.filter((event) => event.metadata.trace_kind === "user_input");
    assert.equal(read.length, 1);
    assert.deepEqual(read[0]!.metadata.user_inputs, [{ command_id: "cmd-1", content: "Only cover the discrete case." }]);
  } finally { await fixture.close(); }
});

for (const repeated of [false, true]) {
  test(`finish checks preserve public explanations (repeated=${repeated})`, async () => {
    const explanation = "B also works under the assumption you raised.";
    const correction = "The question needs that assumption stated explicitly.";
    const fixture = await server((_body, response, count) =>
      answer(response, count === 1 ? explanation : correction),
    );
    const events: EngineEvent[] = [];
    let checks = 0;
    try {
      const config = input(fixture.endpoint);
      config.policyHooks = true;
      const output = await runNative(
        config,
        async (operation, args) => {
          if (operation === "event") events.push(args.event as EngineEvent);
          if (operation === "policy") {
            checks++;
            return {
              redirect:
                repeated || checks === 1
                  ? "Check the failed tool operation."
                  : "",
              override: null,
            };
          }
          return null;
        },
        new AbortController().signal,
      );
      const content = events
        .filter((e) => e.type === "content")
        .map((e) => e.content)
        .join("");
      assert.equal(content, explanation + correction);
      assert.ok(output.response.includes(explanation));
      assert.ok(output.response.includes(correction));
      assert.equal(output.completed, !repeated);
      assert.ok(events.every((e) => e.metadata?.answer_visible !== false));
      assert.equal(fixture.requests.length, 2);
    } finally {
      await fixture.close();
    }
  });
}

test("public answer survives a capability notice without duplication", async () => {
  const explanation = "B also satisfies the stated condition.";
  const notice = "The optional profile update was not saved.";
  const fixture = await server((_body, response) =>
    answer(response, explanation),
  );
  const events: EngineEvent[] = [];
  try {
    const config = input(fixture.endpoint);
    config.policyHooks = true;
    const output = await runNative(
      config,
      async (operation, args) => {
        if (operation === "event") events.push(args.event as EngineEvent);
        if (operation === "policy")
          return { redirect: "", override: notice + "\n\n" + explanation };
        if (operation === "publish_override") {
          events.push({
            type: "content",
            content: String(args.text),
            metadata: {},
          });
        }
        return null;
      },
      new AbortController().signal,
    );
    const content = events
      .filter((e) => e.type === "content")
      .map((e) => e.content)
      .join("");
    assert.equal(content, explanation + notice);
    assert.equal(output.response, explanation + "\n\n" + notice);
    assert.equal(output.completed, true);
  } finally {
    await fixture.close();
  }
});

test("forced tool choice preserves the accompanying explanation", async () => {
  const { modelRound } = await import("../src/native/model-round.js");
  const explanation = "Let us clarify your objection first.";
  const fixture = await server((_body, response) => {
    frame(response, { content: explanation });
    frame(
      response,
      {
        tool_calls: [
          {
            index: 0,
            id: "ask",
            function: {
              name: "ask_user",
              arguments: '{"questions":[{"id":"q","prompt":"Which premise?"}]}',
            },
          },
        ],
      },
      "tool_calls",
    );
    response.end("data: [DONE]\n\n");
  });
  try {
    const config = input(fixture.endpoint);
    config.initialToolChoice = "ask_user";
    const events: EngineEvent[] = [];
    const round = await modelRound(
      config,
      new Conversation(config.seed),
      [
        {
          type: "function",
          function: {
            name: "ask_user",
            description: "Clarify",
            parameters: { type: "object", properties: {} },
          },
        },
      ],
      async (event) => {
        events.push(event);
      },
      new AbortController().signal,
      false,
      true,
    );
    assert.equal(round.text, explanation);
    assert.equal(
      events
        .filter((e) => e.type === "content")
        .map((e) => e.content)
        .join(""),
      explanation,
    );
    assert.ok(events.every((e) => e.metadata?.answer_visible !== false));
    assert.equal(round.toolCalls.length, 1);
  } finally {
    await fixture.close();
  }
});
