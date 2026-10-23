import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import SaveToNotebookModal from "@/components/notebook/SaveToNotebookModal";
import { apiFetch } from "@/lib/api";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/components/common/PickerShell", () => ({ default: ({ open, children }: { open: boolean; children: React.ReactNode }) => open ? <div>{children}</div> : null }));
vi.mock("@/components/common/PickerHeader", () => ({ default: () => null }));
vi.mock("@/lib/notebook-api", () => ({ listNotebooks: async () => [{ id: "notes", name: "My notes", record_count: 0 }], createNotebook: vi.fn() }));
vi.mock("@/lib/api", () => ({ apiUrl: (url: string) => url, apiFetch: vi.fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const payload = { recordType: "chat" as const, title: "Title", userQuery: "Question", output: "Answer" };

it("allows another save after closing an in-flight save and reopening", async () => {
  vi.mocked(apiFetch).mockImplementation((_url, options) => new Promise((_resolve, reject) => {
    options?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  }));
  const onClose = vi.fn();
  const view = render(<SaveToNotebookModal open payload={payload} onClose={onClose} />);
  fireEvent.click(await screen.findByText("My notes"));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(1));
  await act(async () => view.rerender(<SaveToNotebookModal open={false} payload={payload} onClose={onClose} />));
  view.rerender(<SaveToNotebookModal open payload={payload} onClose={onClose} />);
  fireEvent.click(await screen.findByText("My notes"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).not.toBeDisabled());
});

it("aborts a pending save when the dialog component unmounts", async () => {
  let signal: AbortSignal | null = null;
  vi.mocked(apiFetch).mockImplementation((_url, options) => {
    signal = options?.signal ?? null;
    return new Promise(() => undefined);
  });
  const view = render(<SaveToNotebookModal open payload={payload} onClose={vi.fn()} />);
  fireEvent.click(await screen.findByText("My notes"));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(1));
  view.unmount();
  expect((signal as AbortSignal | null)?.aborted).toBe(true);
});

it("keeps successful saves and their callbacks working", async () => {
  vi.mocked(apiFetch).mockResolvedValue(new Response('data: {"type":"result","added_to_notebooks":["notes"],"summary":"Saved summary"}\n\n'));
  const onClose = vi.fn();
  const onSaved = vi.fn();
  render(<SaveToNotebookModal open payload={payload} onClose={onClose} onSaved={onSaved} />);
  fireEvent.click(await screen.findByText("My notes"));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ summary: "Saved summary" }));
  expect(onClose).toHaveBeenCalledTimes(1);
});
