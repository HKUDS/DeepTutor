import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import MessageThreadMarker from "@/features/chat/messages/MessageThreadMarker";
import { initI18n } from "@/i18n/init";
import type { SessionSummary } from "@/lib/session-api";

initI18n("en");

afterEach(cleanup);

function thread(
  id: string,
  overrides: Partial<SessionSummary> = {},
): SessionSummary {
  return {
    id,
    session_id: id,
    title: `Thread ${id}`,
    created_at: 1,
    updated_at: 0,
    message_count: 2,
    last_message: "",
    status: "idle",
    preferences: {
      session_kind: "selection_tutor",
      tutor_source_message_id: 7,
    },
    ...overrides,
  };
}

it("counts the message's threads and opens one from the popover", () => {
  const onOpen = vi.fn();
  render(
    <MessageThreadMarker
      threads={[thread("a"), thread("b")]}
      onOpen={onOpen}
      onDelete={vi.fn(async () => {})}
    />,
  );

  const trigger = screen.getByRole("button", {
    name: "Tutor threads on this message",
  });
  expect(trigger).toHaveTextContent("Little Tutor ×2");

  fireEvent.click(trigger);
  expect(screen.getByRole("dialog")).toBeTruthy();
  expect(screen.getAllByRole("button", { name: /Open tutor thread/ })).toHaveLength(2);

  fireEvent.click(
    screen.getByRole("button", { name: "Open tutor thread: Thread a" }),
  );
  expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ session_id: "a" }));
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("deletes a thread only after the inline confirmation", async () => {
  const onDelete = vi.fn(async () => {});
  render(
    <MessageThreadMarker
      threads={[thread("a")]}
      onOpen={vi.fn()}
      onDelete={onDelete}
    />,
  );

  fireEvent.click(
    screen.getByRole("button", { name: "Tutor threads on this message" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Delete tutor thread" }));
  expect(onDelete).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(onDelete).toHaveBeenCalledTimes(1));
  expect(onDelete).toHaveBeenCalledWith(expect.objectContaining({ session_id: "a" }));
});

it("keeps the row when deletion fails", async () => {
  const onDelete = vi.fn(async () => {
    throw new Error("still running");
  });
  render(
    <MessageThreadMarker
      threads={[thread("a")]}
      onOpen={vi.fn()}
      onDelete={onDelete}
    />,
  );

  fireEvent.click(
    screen.getByRole("button", { name: "Tutor threads on this message" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Delete tutor thread" }));
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));

  await waitFor(() => expect(onDelete).toHaveBeenCalled());
  expect(
    screen.getByRole("button", { name: "Open tutor thread: Thread a" }),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
});

it("disables deletion while the thread is answering", () => {
  render(
    <MessageThreadMarker
      threads={[thread("a", { status: "running" })]}
      onOpen={vi.fn()}
      onDelete={vi.fn(async () => {})}
    />,
  );

  fireEvent.click(
    screen.getByRole("button", { name: "Tutor threads on this message" }),
  );
  expect(screen.getByText("Running…")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Delete tutor thread" })).toBeDisabled();
});

it("renders nothing when the message has no threads", () => {
  const { container } = render(
    <MessageThreadMarker
      threads={[]}
      onOpen={vi.fn()}
      onDelete={vi.fn(async () => {})}
    />,
  );

  expect(container).toBeEmptyDOMElement();
});

it("detaches a thread from the message without deleting it", async () => {
  const onDetach = vi.fn(async () => {});
  render(
    <MessageThreadMarker
      threads={[thread("a")]}
      onOpen={vi.fn()}
      onDelete={vi.fn(async () => {})}
      onDetach={onDetach}
    />,
  );

  fireEvent.click(
    screen.getByRole("button", { name: "Tutor threads on this message" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Detach from this message" }));

  await waitFor(() => expect(onDetach).toHaveBeenCalledTimes(1));
  expect(onDetach).toHaveBeenCalledWith(expect.objectContaining({ session_id: "a" }));
  expect(screen.getByRole("button", { name: "Delete tutor thread" })).toBeTruthy();
});

it("offers no detach action when the surface cannot move anchors", () => {
  render(
    <MessageThreadMarker
      threads={[thread("a")]}
      onOpen={vi.fn()}
      onDelete={vi.fn(async () => {})}
    />,
  );

  fireEvent.click(
    screen.getByRole("button", { name: "Tutor threads on this message" }),
  );
  expect(screen.queryByRole("button", { name: "Detach from this message" })).toBeNull();
});
