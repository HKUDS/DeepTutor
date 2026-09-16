import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import BookPage from "@/app/(workspace)/books/BooksRoute";
import { initI18n } from "@/i18n/init";

initI18n("en");

// A deep book URL, with the book's data still in flight.
vi.mock("next/navigation", () => ({
  useParams: () => ({ bookId: "bk-1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/book-api", () => ({
  BookApiError: class BookApiError extends Error {},
  bookApi: {
    list: vi.fn(() => Promise.resolve({ books: [], can_create: true })),
    get: vi.fn(() => new Promise(() => {})),
  },
}));

vi.mock("@/lib/use-book-stream", () => ({
  useBookStream: () => undefined,
  bookEventKind: () => "",
  bookEventPageId: () => "",
}));

describe("a deep book URL", () => {
  it("never renders the library it is not pointing at", async () => {
    render(<BookPage />);

    expect(await screen.findByText("Loading…")).toBeInTheDocument();
    // The library's own empty state is what the reader used to see first —
    // an empty list one level above the book they had asked for (#1440).
    expect(
      screen.queryByRole("button", { name: /new book/i })
    ).not.toBeInTheDocument();
  });
});
