import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import CategoryManager from "@/components/space/question-bank/CategoryManager";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (value: string) => value }),
}));

it("names tag actions and exposes their hints without native titles", async () => {
  render(
    <CategoryManager
      categories={[{ id: 1, name: "Algebra", created_at: 1, entry_count: 2 }]}
      onCreate={vi.fn(async () => true)}
      onRename={vi.fn(async () => true)}
      onDelete={vi.fn(async () => true)}
    />,
  );

  const rename = screen.getByRole("button", { name: "Rename" });
  expect(rename).not.toHaveAttribute("title");
  expect(document.getElementById(rename.getAttribute("aria-describedby")!)).toHaveTextContent(
    "Rename",
  );

  fireEvent.focus(rename);
  await waitFor(() =>
    expect(document.body.querySelector('[role="tooltip"].fixed')).toHaveTextContent("Rename"),
  );
  fireEvent.click(rename);
  expect(screen.getByRole("button", { name: "Save" })).not.toHaveAttribute("title");
  expect(screen.getByRole("button", { name: "Cancel" })).not.toHaveAttribute("title");
});
