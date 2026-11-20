import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { PracticeImport } from "@/components/learning/practice/PracticeImport";
import { ensureLanguage, initI18n } from "@/i18n/init";
import * as api from "@/lib/practice-api";

vi.mock("@/lib/practice-api", async original => ({
  ...(await original<typeof api>()),
  previewQtiImport: vi.fn(),
  commitQtiImport: vi.fn(),
  previewPracticeImport: vi.fn(),
  commitPracticeImport: vi.fn(),
}));

function preview(): api.QtiImportPreview {
  return {
    token: "qti-preview-token",
    version: "3.0",
    packageValidation: "valid",
    counts: { ready: 2, review: 1, blocked: 1 },
    diagnostics: [],
    items: [
      { itemKey: "ready-a", memberPath: "items/a.xml", bankAdmission: "ready", diagnostics: [] },
      { itemKey: "ready-b", memberPath: "items/b.xml", bankAdmission: "ready", diagnostics: [] },
      { itemKey: "review-c", memberPath: null, bankAdmission: "review", diagnostics: [] },
      {
        itemKey: "blocked-d", memberPath: "items/d.xml", bankAdmission: "blocked",
        diagnostics: [{ code: "unsupported-interaction", severity: "error" }],
      },
    ],
  };
}

beforeEach(async () => {
  vi.resetAllMocks();
  await initI18n("en").changeLanguage("en");
  vi.mocked(api.previewQtiImport).mockResolvedValue(preview());
  vi.mocked(api.commitQtiImport).mockResolvedValue({ created: 1, duplicates: 0 });
});

it.each([
  { filename: "questions.xml", type: "application/xml", target: "bank" as const },
  { filename: "questions.zip", type: "application/zip", target: "mistakes" as const },
])("previews $filename as QTI with the selected target", async ({ filename, type, target }) => {
  render(<PracticeImport initialTarget="bank" onClose={vi.fn()} onImported={vi.fn()} />);
  fireEvent.change(screen.getByRole("combobox", { name: "Import into" }), {
    target: { value: target },
  });
  const file = new File(["QTI fixture"], filename, { type });
  fireEvent.change(screen.getByLabelText(/Choose a question file/), { target: { files: [file] } });

  expect(await screen.findByText(filename)).toBeVisible();
  expect(api.previewQtiImport).toHaveBeenCalledExactlyOnceWith(file, target);
  expect(api.previewPracticeImport).not.toHaveBeenCalled();
  expect(screen.getByRole("checkbox", { name: /ready-a/ })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: /ready-b/ })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: /ready-a/ })).toBeEnabled();
  for (const itemKey of ["review-c", "blocked-d"]) {
    expect(screen.getByRole("checkbox", { name: new RegExp(itemKey) })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: new RegExp(itemKey) })).toBeDisabled();
  }
  expect(screen.getByRole("button", { name: "Confirm import" })).toBeEnabled();
});

it("commits only selected ready items and prevents an empty selection", async () => {
  const onImported = vi.fn();
  render(<PracticeImport initialTarget="bank" onClose={vi.fn()} onImported={onImported} />);
  fireEvent.change(screen.getByLabelText(/Choose a question file/), {
    target: { files: [new File(["QTI fixture"], "questions.zip")] },
  });
  const first = await screen.findByRole("checkbox", { name: /ready-a/ });
  const second = screen.getByRole("checkbox", { name: /ready-b/ });
  const confirm = screen.getByRole("button", { name: "Confirm import" });
  fireEvent.click(first);
  fireEvent.click(second);
  expect(confirm).toBeDisabled();
  fireEvent.click(confirm);
  expect(api.commitQtiImport).not.toHaveBeenCalled();

  fireEvent.click(second);
  expect(confirm).toBeEnabled();
  fireEvent.click(confirm);
  await waitFor(() => expect(onImported).toHaveBeenCalledExactlyOnceWith("Imported 1 questions; skipped 0 duplicates."));
  expect(api.commitQtiImport).toHaveBeenCalledExactlyOnceWith("qti-preview-token", ["ready-b"]);
  expect(api.commitPracticeImport).not.toHaveBeenCalled();
});

it.each(["preview", "commit"] as const)("localizes QTI %s 503 errors instead of exposing server details", async stage => {
  await ensureLanguage("zh");
  await initI18n().changeLanguage("zh");
  const unavailable = new api.PracticeRequestError("Internal server dependency details", 503);
  if (stage === "preview") vi.mocked(api.previewQtiImport).mockRejectedValue(unavailable);
  else vi.mocked(api.commitQtiImport).mockRejectedValue(unavailable);
  const onImported = vi.fn();
  const { container } = render(<PracticeImport initialTarget="bank" onClose={vi.fn()} onImported={onImported} />);
  const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
  fireEvent.change(input, { target: { files: [new File(["QTI fixture"], "questions.xml")] } });
  if (stage === "commit") {
    await screen.findByRole("checkbox", { name: /ready-a/ });
    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));
  }

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "QTI 导入不可用。请在服务器上安装 qti 扩展依赖：pip install 'deeptutor[qti]'。",
  );
  expect(screen.queryByText("Internal server dependency details")).not.toBeInTheDocument();
  expect(onImported).not.toHaveBeenCalled();
});

it("requires explicit selection of a reviewable fill item for self-assessment", async () => {
  const result = preview();
  result.items[2] = {
    ...result.items[2], importable: true,
    question: "3.3 × 0.4 {{blank:blank-1}} 4.4 × 0.3", correctAnswer: "=",
  };
  vi.mocked(api.previewQtiImport).mockResolvedValue(result);
  render(<PracticeImport initialTarget="bank" onClose={vi.fn()} onImported={vi.fn()} />);
  fireEvent.change(screen.getByLabelText(/Choose a question file/), {
    target: { files: [new File(["fixture"], "comparison.zip")] },
  });
  const review = await screen.findByRole("checkbox", { name: /3.3 × 0.4/ });
  expect(review).toBeEnabled();
  expect(review).not.toBeChecked();
  expect(screen.getByText(/This fill question requires self-assessment/)).toBeVisible();
  fireEvent.click(review);
  fireEvent.click(screen.getByRole("button", { name: "Confirm import" }));
  await waitFor(() => expect(api.commitQtiImport).toHaveBeenCalledWith(
    "qti-preview-token", ["ready-a", "ready-b", "review-c"],
  ));
});

it("hides package and item diagnostics and internal XML paths", async () => {
  const result = preview();
  result.diagnostics = [{ code: "SOURCE_GUIDANCE_UNTRUSTED", severity: "warning" }];
  result.items[0].diagnostics = [{ code: "EXTERNAL_SCORING_REQUIRED", severity: "warning" }];
  vi.mocked(api.previewQtiImport).mockResolvedValue(result);
  render(<PracticeImport initialTarget="bank" onClose={vi.fn()} onImported={vi.fn()} />);
  fireEvent.change(screen.getByLabelText(/Choose a question file/), {
    target: { files: [new File(["fixture"], "questions.zip")] },
  });
  await screen.findByRole("checkbox", { name: /ready-a/ });
  for (const text of ["Diagnostic codes", "SOURCE_GUIDANCE_UNTRUSTED", "EXTERNAL_SCORING_REQUIRED", "items/a.xml"]) {
    expect(screen.queryByText(text)).not.toBeInTheDocument();
  }
  expect(screen.getByRole("button", { name: "Confirm import" })).toBeEnabled();
});
