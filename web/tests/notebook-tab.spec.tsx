import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import ChatNotebookTab from "@/components/chat/home/ChatNotebookTab";

// Force a deterministic, English-labelled render with simple interpolation.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options
        ? key.replace(/\{\{(\w+)\}\}/g, (_m, name: string) =>
            String(options[name] ?? ""),
          )
        : key,
    i18n: { language: "en" },
  }),
}));

vi.mock("@/hooks/useAuthStatus", () => ({
  useAuthStatus: () => ({
    loading: false,
    statusAvailable: true,
    enabled: false,
    authenticated: true,
    isAdmin: false,
    userId: null,
    learningPolicy: null,
  }),
}));

vi.mock("@/lib/session-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/session-api")>()),
  getSession: vi.fn(async () => ({
    preferences: {
      mastery_path_id: "path-1",
      mastery_knowledge_point_id: "kp-1",
    },
  })),
}));

vi.mock("@/lib/learning-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/learning-api")>()),
  fetchMasteryMap: vi.fn(async () => ({ map: { modules: [] } })),
}));

const notes = vi.hoisted(() => ({
  getNote: vi.fn(),
  createNote: vi.fn(),
  saveNote: vi.fn(),
}));
vi.mock("@/lib/notes-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/notes-api")>()),
  ...notes,
}));

const lab = vi.hoisted(() => ({ runNotebookCell: vi.fn() }));
vi.mock("@/lib/notebook-lab-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/notebook-lab-api")>()),
  runNotebookCell: lab.runNotebookCell,
}));

// The board loads its applet from a CDN; the tab tests only need it to mount.
vi.mock("@/components/Geogebra", () => ({ default: () => null }));

// RichCodeBlock reads the code-block theme from the app shell.
vi.mock("@/context/AppShellContext", () => ({
  useAppShell: () => ({
    codeBlockTheme: "oneDark",
    codeBlockShowLineNumbers: false,
    codeBlockWrapLongLines: false,
  }),
}));

beforeEach(() => {
  window.localStorage.clear();
  notes.getNote.mockReset();
  notes.createNote.mockReset().mockResolvedValue({
    id: "doc-1",
    revision: 1,
    title: "Notebook",
    content: "",
  });
  notes.saveNote.mockReset().mockResolvedValue({
    id: "doc-1",
    revision: 2,
    title: "Notebook",
    content: "",
  });
  lab.runNotebookCell.mockReset().mockResolvedValue({
    stdout: "42",
    stderr: "",
    exit_code: 0,
    timed_out: false,
    error: "",
    artifacts: [],
  });
});

afterEach(() => {
  cleanup();
});

it("runs a code cell and shows its output", async () => {
  render(<ChatNotebookTab sessionId="session-1" />);

  const code = await screen.findByPlaceholderText("print('hello')");
  fireEvent.change(code, { target: { value: "print(6 * 7)" } });

  fireEvent.click(screen.getByRole("button", { name: "Run cell" }));

  await waitFor(() => expect(lab.runNotebookCell).toHaveBeenCalledTimes(1));
  expect(lab.runNotebookCell).toHaveBeenCalledWith(
    expect.objectContaining({ code: "print(6 * 7)", language: "python" }),
  );
  expect(await screen.findByText("42")).toBeInTheDocument();
});

it("adds note and code cells", async () => {
  render(<ChatNotebookTab sessionId="session-1" />);
  await screen.findByPlaceholderText("print('hello')");

  fireEvent.click(screen.getByRole("button", { name: /Note cell/ }));
  await waitFor(() =>
    expect(
      screen.getAllByPlaceholderText("Write a note, with $math$ in Markdown.")
        .length,
    ).toBe(2),
  );

  fireEvent.click(screen.getByRole("button", { name: /Code cell/ }));
  await waitFor(() =>
    expect(screen.getAllByPlaceholderText("print('hello')").length).toBe(2),
  );
});

it("binds the notebook to the knowledge point of the conversation", async () => {
  render(<ChatNotebookTab sessionId="session-1" />);
  // The header reports the bound point once preferences resolve.
  expect(await screen.findByText(/kp-1/)).toBeInTheDocument();
});

it("adds a GeoGebra board cell with an editable script", async () => {
  render(<ChatNotebookTab sessionId="session-1" />);
  await screen.findByPlaceholderText("print('hello')");

  fireEvent.click(screen.getByRole("button", { name: /Board cell/ }));
  // The board header offers its script toggle once the cell is added.
  const script = await screen.findByRole("button", { name: "Script" });
  expect(script).toBeInTheDocument();
});

it("shows a highlighted preview of a code cell", async () => {
  render(<ChatNotebookTab sessionId="session-1" />);
  const code = await screen.findByPlaceholderText("print('hello')");
  fireEvent.change(code, { target: { value: "print(6 * 7)" } });

  // The code cell's toggle is the second "Preview" (the note cell's is first).
  fireEvent.click(screen.getAllByRole("button", { name: "Preview" })[1]);

  await waitFor(() =>
    expect(document.querySelector(".md-code-block")).not.toBeNull(),
  );
});
