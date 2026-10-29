import test from "node:test";
import assert from "node:assert/strict";
import {
  extractTexAnnotationFromHtml,
  normalizeSelectedText,
  wrapLatexSource,
} from "../lib/selection-text";
import { quoteAttachment, quoteText } from "../lib/quote-attachments";
import { responderFromPreferences, sideChatTurnConfig } from "../lib/side-chat";

test("normalizes selected chat text without flattening paragraphs", () => {
  assert.equal(
    normalizeSelectedText("  first   line\r\n\r\n\r\n second\tline  "),
    "first line\n\nsecond line",
  );
});

test("wrapLatexSource matches Markdown math delimiters", () => {
  assert.equal(wrapLatexSource("a^2", false), "$a^2$");
  assert.equal(
    wrapLatexSource("I(\\theta) = a^2", true),
    "$$I(\\theta) = a^2$$",
  );
});

test("KaTeX annotation remaps to math that grounds in Markdown source", () => {
  const tex = "I(\\theta) = a^2 \\cdot P(\\theta) \\cdot (1 - P(\\theta))";
  const html = `<span class="katex"><span class="katex-mathml"><math><semantics><annotation encoding="application/x-tex">${tex}</annotation></semantics></math></span><span class="katex-html">I(θ)=a²</span></span>`;
  assert.equal(extractTexAnnotationFromHtml(html), tex);

  const source = `$$${tex}$$`;
  const selected = wrapLatexSource(
    extractTexAnnotationFromHtml(html) ?? "",
    true,
  );
  assert.equal(selected, source);
  assert.ok(source.includes(selected));
});

test("a quote travels as UTF-8 text and reads back unchanged", () => {
  const quote = quoteAttachment("  父进程中的 rc 是子进程 PID\n$x^2$  ");
  assert.ok(quote);
  assert.equal(quote.type, "quote");
  assert.equal(quote.text, "父进程中的 rc 是子进程 PID\n$x^2$");
  assert.equal(quoteText({ base64: quote.base64 }), quote.text);
  assert.equal(quoteAttachment("   "), null);
});

test("a side chat names its parent and who answers it", () => {
  const base = { parentSessionId: "parent-1", leafMessageId: 9 };
  assert.deepEqual(
    sideChatTurnConfig({ ...base, responder: { kind: "dito" } }),
    {
      selection_tutor_context: {
        parent_session_id: "parent-1",
        source_message_id: 9,
      },
      answer_by: "",
    },
  );
  assert.equal(
    sideChatTurnConfig({
      ...base,
      responder: { kind: "partner", id: "ada", name: "Ada" },
    }).answer_by,
    "partner:ada",
  );
  assert.deepEqual(
    sideChatTurnConfig({
      ...base,
      responder: { kind: "partner_group", id: "g1", name: "Study group" },
    }),
    {
      selection_tutor_context: {
        parent_session_id: "parent-1",
        source_message_id: 9,
      },
      answer_by: "",
      partner_discussion_group_id: "g1",
    },
  );
});

test("a reopened side chat keeps answering through whoever answered it", () => {
  assert.deepEqual(
    responderFromPreferences({ answer_by: "subagent:my-codex" }),
    {
      kind: "subagent",
      id: "my-codex",
      name: "my-codex",
    },
  );
  assert.deepEqual(
    responderFromPreferences({ side_chat_group_id: "g1", answer_by: "" }),
    {
      kind: "partner_group",
      id: "g1",
      name: "g1",
    },
  );
  assert.deepEqual(responderFromPreferences({}), { kind: "dito" });
});
