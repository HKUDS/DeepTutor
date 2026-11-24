import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import KbImportSummary from "@/components/knowledge/KbImportSummary";

const GERMAN: Record<string, string> = {
  "Unsupported file type": "Nicht unterstützter Dateityp",
};

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, string | number>) =>
      (GERMAN[key] ?? key).replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
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
            reason: "Unsupported file type",
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
      "course.zip/tools/setup.exe — Nicht unterstützter Dateityp",
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

it("lists a member twice without a React key clash", () => {
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  render(
    <KbImportSummary
      files={[]}
      report={{
        duplicates: [],
        renamed: [],
        rejected: [
          { file: "a.zip/x.pdf", reason: "Duplicate path in the archive" },
          { file: "a.zip/x.pdf", reason: "Duplicate path in the archive" },
        ],
      }}
    />,
  );
  expect(
    screen.getAllByText("a.zip/x.pdf — Duplicate path in the archive"),
  ).toHaveLength(2);
  expect(
    consoleError.mock.calls.some((call) =>
      String(call[0]).includes("same key"),
    ),
  ).toBe(false);
  consoleError.mockRestore();
});
