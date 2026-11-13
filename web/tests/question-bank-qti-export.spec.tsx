import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import QuestionBankSection from "@/components/space/question-bank/QuestionBankSection";
import { initI18n } from "@/i18n/init";
import { exportQtiPackage } from "@/lib/practice-api";

const { bank } = vi.hoisted(() => ({
  bank: {
    selectedIds: new Set<number>(),
    pendingIds: new Set<number>(),
    items: [],
    stats: { total: 0 },
    searchInput: "",
    loading: false,
    refreshing: false,
    error: null,
    scope: { kind: "all" },
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/components/space/question-bank/useQuestionBank", () => ({
  useQuestionBank: vi.fn(() => bank),
}));
vi.mock("@/lib/practice-api", async original => ({
  ...(await original<typeof import("@/lib/practice-api")>()),
  exportQtiPackage: vi.fn(),
}));
vi.mock("@/components/space/SpaceSectionHeader", () => ({ default: () => null }));
vi.mock("@/components/space/question-bank/BankScopeRail", () => ({ default: () => null }));
vi.mock("@/components/space/question-bank/BankSelectionBar", () => ({ default: () => null }));
vi.mock("@/components/space/question-bank/BankToolbar", () => ({ default: () => null }));
vi.mock("@/components/space/question-bank/CategoryManager", () => ({ default: () => null }));
vi.mock("@/components/space/question-bank/QuestionCard", () => ({ default: () => null }));

beforeEach(async () => {
  vi.clearAllMocks();
  bank.selectedIds = new Set();
  await initI18n("en").changeLanguage("en");
  vi.mocked(exportQtiPackage).mockResolvedValue(undefined);
});

it("places QTI export before practice and disables export when nothing is selected", () => {
  render(<QuestionBankSection onPractice={vi.fn()} />);
  const exportButton = screen.getByRole("button", { name: "Export QTI package" });
  const practiceButton = screen.getByRole("button", { name: "Practice this page" });

  expect(exportButton.compareDocumentPosition(practiceButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(exportButton).toBeDisabled();
  fireEvent.click(exportButton);
  expect(exportQtiPackage).not.toHaveBeenCalled();
});

it("exports selected IDs, not the visible page or the practice action", async () => {
  bank.selectedIds = new Set([42, 7]);
  const onPractice = vi.fn();
  render(<QuestionBankSection onPractice={onPractice} />);
  const exportButton = screen.getByRole("button", { name: "Export QTI package" });

  expect(exportButton).toBeEnabled();
  fireEvent.click(exportButton);

  await waitFor(() => expect(exportQtiPackage).toHaveBeenCalledExactlyOnceWith([42, 7]));
  await waitFor(() => expect(screen.getByRole("button", { name: "Export QTI package" })).toBeEnabled());
  expect(onPractice).not.toHaveBeenCalled();
});
