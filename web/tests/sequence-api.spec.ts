import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  checkSequenceAnswer,
  createSequenceProblem,
  explainSequenceStep,
  getSequenceOutline,
  placeSequenceStep,
  rebuildSequenceOutline,
  removeSequenceStep,
  requestSequenceHint,
  SequenceRequestError,
  type SequenceOutline,
  type SequenceProblem,
} from "@/lib/sequence-api";

const PROBLEM: SequenceProblem = {
  problem_id: "p1",
  question: "Rebuild the solution for $\\cos(x^2)$.",
  formulas: ["$\\cos(x^2)$"],
  steps: [
    { id: "s_a", explanation: "Apply the chain rule", math: "$-2x\\sin(x^2)$" },
    { id: "s_b", explanation: "A tempting mistake", math: "$2x\\cos(x)$" },
  ],
  placed_ids: [],
  solved: false,
  explanation: null,
  progress: { solved: 0, goal: 5 },
  sources: [{ title: "calculus/chain_rule.pdf" }],
};

const OUTLINE: SequenceOutline = {
  knowledge_base: "calculus",
  source: "files",
  modules: [
    { id: "m1", category: "", name: "Limits", topic: "limits", solved: 0, goal: 5 },
    { id: "m2", category: "Derivatives", name: "Chain rule", topic: "chain rule", solved: 2, goal: 5 },
  ],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const fetchMock = vi.fn();

beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState(null, "", "/learning");
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("sequence-api request mapping", () => {
  it("posts a scoped create request and returns the typed problem", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(PROBLEM));

    const problem = await createSequenceProblem("Calculus", "chain rule");

    expect(problem.problem_id).toBe("p1");
    expect(problem.steps).toHaveLength(2);
    expect(problem.progress).toEqual({ solved: 0, goal: 5 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/solution-sequence/problems?dt_workspace=");
    expect(init).toMatchObject({
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
    });
    expect(JSON.parse(init.body as string)).toEqual({
      knowledge_base: "Calculus",
      topic: "chain rule",
    });
  });

  it("maps a non-OK response with a detail sentence onto SequenceRequestError", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "Choose a knowledge base." }, 422));

    const error = await createSequenceProblem("", "chain rule").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(SequenceRequestError);
    expect((error as SequenceRequestError).status).toBe(422);
    expect((error as SequenceRequestError).message).toBe("Choose a knowledge base.");
  });

  it("keeps the status and falls back when the error body is not JSON", async () => {
    fetchMock.mockResolvedValueOnce(new Response("gateway said no", { status: 502 }));

    const error = await checkSequenceAnswer("p1", ["s_a"]).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(SequenceRequestError);
    expect((error as SequenceRequestError).status).toBe(502);
    expect((error as SequenceRequestError).message).toBe("The request failed.");
  });
});

describe("getSequenceOutline", () => {
  it("reads a saved outline with an uncached scoped GET", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(OUTLINE));

    await expect(getSequenceOutline("calculus")).resolves.toEqual(OUTLINE);

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(
      "/api/solution-sequence/outlines?knowledge_base=calculus&dt_workspace=",
    );
    expect(init).toMatchObject({ method: "GET", cache: "no-store" });
    expect(init.body).toBeUndefined();
  });

  it("maps only the exact not-read-yet 404 onto null", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "This knowledge base has not been read yet." }, 404),
    );

    await expect(getSequenceOutline("calculus")).resolves.toBeNull();
  });

  it("rethrows any other 404 instead of hiding it", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "That problem is no longer available." }, 404),
    );

    const error = await getSequenceOutline("calculus").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(SequenceRequestError);
    expect((error as SequenceRequestError).status).toBe(404);
    expect((error as SequenceRequestError).message).toBe("That problem is no longer available.");
  });

  it("posts a rebuild request with the knowledge base", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(OUTLINE));

    await expect(rebuildSequenceOutline("calculus")).resolves.toEqual(OUTLINE);

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/solution-sequence/outlines?dt_workspace=");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ knowledge_base: "calculus" });
  });
});

describe("answer-shape round trips", () => {
  it("url-encodes the problem id and keeps place and remove payloads apart", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ accepted: true, problem: PROBLEM }));

    const placed = await placeSequenceStep("p 1/evil", "s_a", 0);

    expect(placed.accepted).toBe(true);
    expect(placed.problem.problem_id).toBe("p1");
    let [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/solution-sequence/problems/p%201%2Fevil/place");
    expect(JSON.parse(init.body as string)).toEqual({ step_id: "s_a", index: 0 });

    fetchMock.mockResolvedValueOnce(jsonResponse(PROBLEM));

    const removed = await removeSequenceStep("p1", "s_a");

    // remove answers with the bare problem, not the { accepted, problem } wrapper.
    expect(removed.problem_id).toBe("p1");
    expect(removed).not.toHaveProperty("accepted");
    [url, init] = fetchMock.mock.calls[1];
    expect(String(url)).toContain("/api/solution-sequence/problems/p1/remove");
    expect(JSON.parse(init.body as string)).toEqual({ step_id: "s_a" });
  });

  it("sends the assembled order to check and returns marks", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ solved: false, marks: ["correct", "incorrect"], problem: PROBLEM }),
    );

    const result = await checkSequenceAnswer("p1", ["s_a", "s_b"]);

    expect(result.solved).toBe(false);
    expect(result.marks).toEqual(["correct", "incorrect"]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/solution-sequence/problems/p1/check");
    expect(JSON.parse(init.body as string)).toEqual({ step_ids: ["s_a", "s_b"] });
  });

  it("sends no hint body unless the client assembles steps itself", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ hint: "Look at the inner function." }));
    await expect(requestSequenceHint("p1")).resolves.toEqual({
      hint: "Look at the inner function.",
    });
    expect(fetchMock.mock.calls[0][1].body).toBeUndefined();

    fetchMock.mockResolvedValueOnce(jsonResponse({ hint: "Almost there." }));
    await requestSequenceHint("p1", ["s_a"]);
    const [url, init] = fetchMock.mock.calls[1];
    expect(String(url)).toContain("/api/solution-sequence/problems/p1/hint");
    expect(JSON.parse(init.body as string)).toEqual({ step_ids: ["s_a"] });
  });

  it("returns the explanation for a placed step", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ explanation: "The outer function goes first." }));

    await expect(explainSequenceStep("p1", "s_a")).resolves.toEqual({
      explanation: "The outer function goes first.",
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/solution-sequence/problems/p1/explain");
    expect(JSON.parse(init.body as string)).toEqual({ step_id: "s_a" });
  });

  it("surfaces the post-solve conflict as a typed 409", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "This solution is already complete." }, 409),
    );

    const error = await placeSequenceStep("p1", "s_a", 0).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(SequenceRequestError);
    expect((error as SequenceRequestError).status).toBe(409);
    expect((error as SequenceRequestError).message).toBe("This solution is already complete.");
  });
});
