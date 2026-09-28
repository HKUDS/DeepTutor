import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { expect, it, vi } from "vitest";
import NotebookConsole from "@/components/notebook/NotebookConsole";

const mocks = vi.hoisted(() => ({
  rename: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/notebook/NotebookRecordRow", () => ({
  default: () => null,
}));
vi.mock("@/components/notebook/useNotebookLibrary", () => ({
  useNotebookLibrary: () => ({
    notebooks: [
      { id: "notebook-1", name: "First notebook", record_count: 1 },
      { id: "notebook-2", name: "Second notebook", record_count: 2 },
    ],
    selectedId: "notebook-2",
    selected: {
      id: "notebook-2",
      name: "Second notebook",
      records: [],
    },
    loading: false,
    detailLoading: false,
    error: null,
    detailError: null,
    select: vi.fn(),
    reload: vi.fn(),
    create: vi.fn(),
    rename: mocks.rename,
    remove: vi.fn(),
    editRecord: vi.fn(),
    removeRecord: vi.fn(),
    relocateRecord: vi.fn(),
  }),
}));

it("renames a notebook from its sidebar row without using the record menu", async () => {
  render(<NotebookConsole initialNotebookId="notebook-2" />);

  const sidebar = screen.getByRole("navigation");
  const secondNotebookRow = within(sidebar)
    .getByText("Second notebook")
    .closest("div");
  expect(secondNotebookRow).not.toBeNull();

  const editButton = within(secondNotebookRow!).getByRole("button", {
    name: "Edit notebook",
  });
  fireEvent.click(editButton);
  const form = screen.getByRole("form", { name: "Edit notebook" });
  expect(form).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Notebook name"), {
    target: { value: "Renamed notebook" },
  });
  fireEvent.submit(form);

  await waitFor(() => {
    expect(
      screen.queryByRole("form", { name: "Edit notebook" }),
    ).not.toBeInTheDocument();
  });
  expect(mocks.rename).toHaveBeenCalledWith("notebook-2", {
    name: "Renamed notebook",
    description: "",
    color: "#6366F1",
  });
});
