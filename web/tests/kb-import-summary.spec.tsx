import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import KbImportSummary from "@/components/knowledge/KbImportSummary";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, string | number>) =>
      key.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
        String(values?.[name] ?? `{{${name}}}`),
      ),
  }),
}));

it("summarises a re-imported course archive file by file", () => {
  render(
    <KbImportSummary
      files={["Week3/Slides.pdf"]}
      report={{
        duplicates: ["Week1/Slides.pdf", "Week2/Slides.pdf"],
        renamed: [
          { path: "Week1/Uebung (2).pdf", conflicts_with: "Week1/Uebung.pdf" },
        ],
        rejected: [
          {
            file: "course.zip/tools/setup.exe",
            reason: "Unsupported file type: .exe",
          },
        ],
      }}
    />,
  );

  expect(screen.getByText("New files: 1")).toBeTruthy();
  expect(
    screen.getByText(
      "Identical files already in this knowledge base, skipped: 2",
    ),
  ).toBeTruthy();
  expect(
    screen.getByText("Changed files stored next to the existing version: 1"),
  ).toBeTruthy();
  expect(
    screen.getByText("Week1/Uebung (2).pdf ← Week1/Uebung.pdf"),
  ).toBeTruthy();
  expect(
    screen.getByText("Not imported (unsupported or unsafe): 1"),
  ).toBeTruthy();
  expect(
    screen.getByText(
      "course.zip/tools/setup.exe — Unsupported file type: .exe",
    ),
  ).toBeTruthy();
});

it("renders nothing for an upload without archive outcomes", () => {
  const { container } = render(
    <KbImportSummary
      files={["notes.md"]}
      report={{ duplicates: [], renamed: [], rejected: [] }}
    />,
  );
  expect(container.innerHTML).toBe("");
});

it("renders nothing when the backend sent no report", () => {
  const { container } = render(<KbImportSummary files={[]} />);
  expect(container.innerHTML).toBe("");
});
