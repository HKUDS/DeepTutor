import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ChatStateAdapterProvider, useChatStateAdapter } from "@/features/chat/ChatStateAdapter";

const mocks = vi.hoisted(() => ({ requests: [] as Record<string, unknown>[] }));
vi.mock("@/features/chat/transport/UnifiedTurnClient", () => ({
  UnifiedTurnClient: class {
    connected = true;
    connect() {}
    disconnect() {}
    setResumeState() {}
    send(message: Record<string, unknown>) { mocks.requests.push(message); }
  },
}));

function Harness() {
  const { state, newSession, setKBs, initializeKBs, sendMessage } = useChatStateAdapter();
  return <>
    <button onClick={() => newSession({ workspaceId: "school" })}>New</button>
    <button onClick={() => initializeKBs(state.sessionKey, "school", ["school:kb:physics"])}>Initialize</button>
    <button onClick={() => initializeKBs(state.sessionKey, "other", ["other:kb:private"])}>Stale workspace</button>
    <button onClick={() => setKBs([])}>Detach</button>
    <button onClick={() => void sendMessage("hello")}>Send</button>
    <output data-testid="selection">{JSON.stringify(state.knowledgeBases)}</output>
  </>;
}

beforeEach(() => { mocks.requests.length = 0; });

it("sends the initialized default through the real turn producer", async () => {
  render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
  fireEvent.click(screen.getByText("New"));
  fireEvent.click(screen.getByText("Initialize"));
  await waitFor(() => expect(screen.getByTestId("selection")).toHaveTextContent('school:kb:physics'));
  fireEvent.click(screen.getByText("Send"));
  expect(mocks.requests.find((request) => request.type === "start_turn")?.knowledge_bases)
    .toEqual(["school:kb:physics"]);
});

it("keeps explicit detach when an older catalog result arrives", async () => {
  render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
  fireEvent.click(screen.getByText("New"));
  fireEvent.click(screen.getByText("Detach"));
  fireEvent.click(screen.getByText("Initialize"));
  await waitFor(() => expect(screen.getByTestId("selection")).toHaveTextContent("[]"));
  fireEvent.click(screen.getByText("Send"));
  expect(mocks.requests.find((request) => request.type === "start_turn")?.knowledge_bases).toEqual([]);
});

it("ignores an initialization from a different workspace", async () => {
  render(<ChatStateAdapterProvider><Harness /></ChatStateAdapterProvider>);
  fireEvent.click(screen.getByText("New"));
  fireEvent.click(screen.getByText("Stale workspace"));
  expect(screen.getByTestId("selection")).toHaveTextContent("[]");
  fireEvent.click(screen.getByText("Initialize"));
  await waitFor(() => expect(screen.getByTestId("selection")).toHaveTextContent("school:kb:physics"));
});
