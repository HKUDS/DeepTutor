import { EditorState } from "@codemirror/state";
import { CompletionContext } from "@codemirror/autocomplete";
import { describe, expect, it } from "vitest";

import {
  identifierCompletionSource,
  keywordCompletionSource,
  keywordsFor,
} from "@/components/code/completions";

describe("code completions", () => {
  it("offers python keywords and snippets for the typed prefix", async () => {
    const state = EditorState.create({ doc: "fo" });
    const context = new CompletionContext(state, 2, true);
    const result = await keywordCompletionSource("python")(context);

    expect(result).not.toBeNull();
    const labels = result?.options.map((option) => option.label);
    expect(labels).toContain("for");
    expect(labels?.some((label) => String(label).startsWith("fo"))).toBe(true);
  });

  it("does not offer C++ keywords for Python", () => {
    expect(keywordsFor("python")).not.toContain("namespace");
    expect(keywordsFor("cpp")).toContain("namespace");
  });

  it("offers identifiers already used in the document", async () => {
    const state = EditorState.create({ doc: "total = 1\npri" });
    const context = new CompletionContext(state, state.doc.length, true);
    const result = await identifierCompletionSource(context);

    expect(result).not.toBeNull();
    expect(result?.options.map((option) => option.label)).toContain("total");
  });
});
