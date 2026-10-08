import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import MemoryWorkbench from "@/components/memory/MemoryWorkbench";
import { apiFetch } from "@/lib/api";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("next/link", () => ({ default: ({ children }: { children: React.ReactNode }) => <span>{children}</span> }));
vi.mock("next/dynamic", () => ({ default: () => ({ content }: { content: string }) => <div>{content}</div> }));
vi.mock("@/components/memory/MemoryRunPanel", () => ({ default: () => null }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, apiUrl: (url: string) => url, apiFetch: vi.fn() };
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

function setup(status: number) {
  vi.mocked(apiFetch).mockImplementation(async (url, options) => {
    if (options?.method === "PUT") return Response.json(status === 200 ? { saved: true } : { detail: "Memory storage unavailable" }, { status });
    if (String(url).endsWith("/overview")) return Response.json({ docs: [] });
    if (String(url).endsWith("/lines")) return Response.json({ lines: [] });
    return Response.json({ layer: "L2", key: "chat", content: "Original memory" });
  });
}

it("keeps the unsaved memory draft editable when the server rejects a save", async () => {
  setup(503);
  render(<MemoryWorkbench layer="L2" initialKey="chat" />);
  await screen.findByText("Original memory");
  fireEvent.click(screen.getByRole("button", { name: "Edit raw" }));
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Unsaved memory" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByText("Memory storage unavailable");
  expect(screen.getByRole("textbox")).toHaveValue("Unsaved memory");
  expect(screen.queryByText("Saved")).toBeNull();
  expect(screen.getByRole("button", { name: "Save" })).not.toBeDisabled();
});

it("updates the preview and exits editing after a successful save", async () => {
  setup(200);
  render(<MemoryWorkbench layer="L2" initialKey="chat" />);
  await screen.findByText("Original memory");
  fireEvent.click(screen.getByRole("button", { name: "Edit raw" }));
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Updated memory" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByText("Saved");
  expect(screen.queryByRole("textbox")).toBeNull();
  await waitFor(() => expect(screen.getByText("Updated memory")).toBeInTheDocument());
});
