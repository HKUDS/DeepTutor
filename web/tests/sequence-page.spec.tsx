import type { ComponentProps, ReactNode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import i18n from "i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SequencePage } from "@/components/learning/sequence/SequencePage";
import { initI18n } from "@/i18n/init";
import * as knowledge from "@/features/knowledge/api/client";
import * as sequenceApi from "@/lib/sequence-api";
import { SequenceRequestError, type SequenceOutline } from "@/lib/sequence-api";

vi.mock("next/link", () => ({
  default: ({ children, ...props }: ComponentProps<"a"> & { children?: ReactNode }) => (
    <a {...props}>{children}</a>
  ),
}));
vi.mock("next/dynamic", () => ({
  default:
    () =>
    ({ content }: { content: string }) => <div>{content}</div>,
}));
vi.mock("@/features/knowledge/api/client", () => ({
  listKnowledgeBases: vi.fn(),
}));
vi.mock("@/lib/sequence-api", async importOriginal => ({
  ...(await importOriginal<typeof sequenceApi>()),
  getSequenceOutline: vi.fn(),
  rebuildSequenceOutline: vi.fn(),
  createSequenceProblem: vi.fn(),
}));

initI18n("en");

const OUTLINE: SequenceOutline = {
  knowledge_base: "calculus",
  source: "files",
  modules: [
    { id: "m1", category: "", name: "Limits", topic: "limits", solved: 0, goal: 5 },
    { id: "m2", category: "Derivatives", name: "Chain rule", topic: "chain rule", solved: 2, goal: 5 },
  ],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(knowledge.listKnowledgeBases).mockResolvedValue([{ name: "calculus" }]);
});

describe("SequencePage outline phases", () => {
  it("stays idle with the knowledge-base picker until one is chosen", async () => {
    vi.mocked(knowledge.listKnowledgeBases).mockResolvedValue([
      { name: "calculus" },
      { name: "physics" },
    ]);

    render(<SequencePage />);

    const picker = await screen.findByRole("combobox", { name: "Knowledge base" });
    expect(picker).toHaveValue("");
    expect(screen.getByRole("option", { name: "physics" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Guided practice" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Read again" })).toBeNull();
    expect(sequenceApi.getSequenceOutline).not.toHaveBeenCalled();
  });

  it("walks loading → reading → ready and names an empty category", async () => {
    const saved = deferred<SequenceOutline | null>();
    const rebuilt = deferred<SequenceOutline>();
    vi.mocked(sequenceApi.getSequenceOutline).mockReturnValue(saved.promise);
    vi.mocked(sequenceApi.rebuildSequenceOutline).mockReturnValue(rebuilt.promise);

    render(<SequencePage />);

    // loading: the saved outline is being fetched, nothing to read again yet.
    await waitFor(() => expect(sequenceApi.getSequenceOutline).toHaveBeenCalledWith("calculus"));
    expect(screen.getByRole("button", { name: "Read again" })).toBeDisabled();
    expect(screen.queryByText("Reading the modules in this knowledge base…")).toBeNull();

    // reading: no saved outline, so the modules are rebuilt from the source.
    await act(async () => saved.resolve(null));
    expect(await screen.findByText("Reading the modules in this knowledge base…")).toBeInTheDocument();

    // ready: module cards show, and the server's empty category is named here.
    await act(async () => rebuilt.resolve(OUTLINE));
    expect(await screen.findByRole("heading", { name: "Derivatives" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Course" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /chain rule/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /limits/ })).toBeInTheDocument();
    expect(screen.getByText("Solved 2 of 5")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Read again" })).toBeEnabled();
    expect(screen.queryByText("Reading the modules in this knowledge base…")).toBeNull();
  });

  it("shows the failure state when the saved outline cannot be read", async () => {
    vi.mocked(sequenceApi.getSequenceOutline).mockRejectedValue(
      new SequenceRequestError(500, "The request failed."),
    );

    render(<SequencePage />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not read the modules in that knowledge base.");
    expect(sequenceApi.rebuildSequenceOutline).not.toHaveBeenCalled();
  });

  it("shows the failure state when rebuilding the outline fails", async () => {
    vi.mocked(sequenceApi.getSequenceOutline).mockResolvedValue(null);
    vi.mocked(sequenceApi.rebuildSequenceOutline).mockRejectedValue(
      new SequenceRequestError(422, "That knowledge base did not return any material."),
    );

    render(<SequencePage />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not read the modules in that knowledge base.");
    expect(sequenceApi.rebuildSequenceOutline).toHaveBeenCalledWith("calculus");
  });

  it("answers a server sentence in the learner's own language", async () => {
    const { ensureLanguage } = await import("@/i18n/init");
    await ensureLanguage("zh");
    await i18n.changeLanguage("zh");
    let view: ReturnType<typeof render> | undefined;
    try {
      vi.mocked(sequenceApi.getSequenceOutline).mockResolvedValue(OUTLINE);
      vi.mocked(sequenceApi.createSequenceProblem).mockRejectedValue(
        new SequenceRequestError(422, "Choose a knowledge base."),
      );

      view = render(<SequencePage />);

      fireEvent.click(await screen.findByRole("button", { name: /chain rule/ }));
      // The server's fixed English sentence doubles as the i18n key.
      expect(await screen.findByText("选择一个知识库。")).toBeInTheDocument();
      expect(screen.queryByText("Choose a knowledge base.")).toBeNull();
    } finally {
      // Unmount before the language flips back so the re-render cannot escape act.
      view?.unmount();
      await i18n.changeLanguage("en");
    }
  });
});
