import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AddMaterialsDialog } from "@/components/reading/library/AddMaterialsDialog";

const fixture = vi.hoisted(() => ({ list: vi.fn(), add: vi.fn(), t: (key: string) => key }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: fixture.t }) }));
vi.mock("@/components/watching/WatchingBrowser", () => ({ WatchingBrowser: () => null }));
vi.mock("@/lib/reading-workspace-api", async (original) => ({
  ...await original<object>(), listReadingLibraryMaterials: fixture.list,
  addReadingWorkspaceMaterial: fixture.add,
}));

it("keeps the picker and search open while selecting multiple existing materials", async () => {
  fixture.list.mockResolvedValue({ materials: [
    { material_id: "one", title: "Lesson One", filename: "one.pdf", source_kind: "pdf" },
    { material_id: "two", title: "Lesson Two", filename: "two.pdf", source_kind: "pdf" },
  ] });
  const close = vi.fn();
  render(<AddMaterialsDialog mode="add" workspaceId="collection" onClose={close} onDone={() => {}} />);
  const toggle = screen.getByRole("button", { name: /Choose from material/ });
  fireEvent.click(toggle);
  await waitFor(() => expect(screen.getByRole("button", { name: /Lesson One/ })).toBeInTheDocument());
  const search = screen.getByPlaceholderText("Search your library");
  fireEvent.change(search, { target: { value: "Lesson" } });
  const one = screen.getByRole("button", { name: /Lesson One/ });
  const two = screen.getByRole("button", { name: /Lesson Two/ });
  fireEvent.click(one);
  fireEvent.click(two);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(search).toHaveValue("Lesson");
  expect(one).toBeDisabled();
  expect(two).toBeDisabled();
  expect(fixture.list).toHaveBeenCalledTimes(1);
  expect(fixture.add).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(close).toHaveBeenCalled();
  expect(fixture.add).not.toHaveBeenCalled();
});
