import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fixture = vi.hoisted(() => ({
  params: {} as { bookId?: string; pageId?: string },
  get: vi.fn(),
  list: vi.fn(),
  getPage: vi.fn(),
  listLearningCaptures: vi.fn(),
  markVisited: vi.fn(),
  push: vi.fn(),
  replace: vi.fn(),
  notify: vi.fn(),
  t: (key: string) => key,
}));

vi.mock("next/navigation", () => ({
  useParams: () => fixture.params,
  useRouter: () => ({
    push: fixture.push,
    replace: fixture.replace,
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: fixture.t,
  }),
}));

vi.mock("@/lib/notifications", () => ({
  notify: fixture.notify,
}));

vi.mock("@/lib/book-api", () => ({
  BookApiError: class BookApiError extends Error {
    status = 500;
    code?: string;
  },
  bookApi: {
    get: fixture.get,
    list: fixture.list,
    getPage: fixture.getPage,
    listLearningCaptures: fixture.listLearningCaptures,
    markVisited: fixture.markVisited,
  },
}));

vi.mock("@/lib/use-book-stream", () => ({
  useBookStream: vi.fn(),
  bookEventKind: () => "",
  bookEventPageId: () => null,
}));

vi.mock("@/app/(workspace)/books/components/BookLibrary", () => ({
  default: () => <div data-testid="book-library" />,
}));
vi.mock("@/app/(workspace)/books/components/BookCreator", () => ({
  default: () => <div data-testid="book-creator" />,
}));
vi.mock("@/app/(workspace)/books/components/SpineEditor", () => ({
  default: () => <div data-testid="spine-editor" />,
}));
vi.mock("@/app/(workspace)/books/components/BookSidebar", () => ({
  default: () => <div data-testid="book-sidebar" />,
}));
vi.mock("@/app/(workspace)/books/components/BookGenerationActivity", () => ({
  default: () => <div data-testid="book-generation" />,
}));
vi.mock("@/app/(workspace)/books/components/BookPausedBanner", () => ({
  default: () => null,
}));
vi.mock("@/app/(workspace)/books/components/BookHealthBanner", () => ({
  default: () => null,
}));
vi.mock("@/app/(workspace)/books/components/BookChatPanel", () => ({
  default: () => null,
}));
vi.mock("@/app/(workspace)/books/components/LearningCapturePanel", () => ({
  default: () => null,
}));
vi.mock("@/app/(workspace)/books/components/PageReader", () => ({
  default: ({ page }: { page?: { id: string } | null }) => (
    <div data-testid="page-reader">{page?.id || "no-page"}</div>
  ),
}));

import BookPage from "@/app/(workspace)/books/BooksRoute";

function readyDetail() {
  const progress = {
    current_page_id: null,
    visited_page_ids: [],
    bookmarked_page_ids: [],
    quiz_attempts: {},
  };
  return {
    book: {
      id: "book-1",
      title: "A book",
      status: "ready",
      can_edit: true,
      revision: 1,
      metadata: {},
    },
    pages: [
      {
        id: "page-1",
        book_id: "book-1",
        title: "Chapter one",
        status: "ready",
        blocks: [],
        block_count: 0,
      },
    ],
    spine: null,
    progress,
    generation: null,
  };
}

beforeEach(() => {
  fixture.params = {};
  fixture.get.mockReset();
  fixture.list.mockReset().mockResolvedValue({ books: [], can_create: true });
  fixture.getPage.mockReset();
  fixture.listLearningCaptures
    .mockReset()
    .mockResolvedValue({ captures: [] });
  fixture.markVisited
    .mockReset()
    .mockResolvedValue({ progress: readyDetail().progress });
  fixture.push.mockReset();
  fixture.replace.mockReset().mockImplementation(() => {
    fixture.params = {};
  });
  fixture.notify.mockReset();
});

describe("book deep-link loading", () => {
  it("keeps a direct book URL in a book loading shell until details arrive", async () => {
    fixture.params = { bookId: "book-1" };
    let resolveDetails!: (value: ReturnType<typeof readyDetail>) => void;
    fixture.get.mockReturnValue(
      new Promise((resolve) => {
        resolveDetails = resolve;
      }),
    );

    render(<BookPage />);

    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByTestId("book-library")).not.toBeInTheDocument();
    expect(screen.queryByTestId("book-sidebar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("book-generation")).not.toBeInTheDocument();

    await act(async () => {
      resolveDetails(readyDetail());
    });

    expect(await screen.findByTestId("page-reader")).toHaveTextContent("page-1");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByTestId("book-library")).not.toBeInTheDocument();
  });

  it("opens the requested page directly after a page deep link loads", async () => {
    fixture.params = { bookId: "book-1", pageId: "page-1" };
    fixture.get.mockResolvedValue(readyDetail());

    render(<BookPage />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(await screen.findByTestId("page-reader")).toHaveTextContent("page-1");
    expect(screen.queryByTestId("book-library")).not.toBeInTheDocument();
  });

  it("still renders the library at the books root route", async () => {
    let resolveBooks!: (value: { books: never[]; can_create: boolean }) => void;
    fixture.list.mockReturnValue(
      new Promise((resolve) => {
        resolveBooks = resolve;
      }),
    );

    render(<BookPage />);

    expect(screen.getByTestId("book-library")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    await act(async () => {
      resolveBooks({ books: [], can_create: true });
    });
  });

  it("leaves loading and returns to the library when the book cannot be loaded", async () => {
    fixture.params = { bookId: "missing-book" };
    fixture.get.mockRejectedValue(new Error("Book not found"));
    let resolveBooks!: (value: { books: never[]; can_create: boolean }) => void;
    fixture.list.mockReturnValue(
      new Promise((resolve) => {
        resolveBooks = resolve;
      }),
    );

    render(<BookPage />);

    await waitFor(() => {
      expect(fixture.replace).toHaveBeenCalledWith("/books");
      expect(screen.getByTestId("book-library")).toBeInTheDocument();
    });
    await act(async () => {
      resolveBooks({ books: [], can_create: true });
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(fixture.notify).toHaveBeenCalledWith("Book not found", {
      tone: "error",
      durationMs: 8000,
    });
  });
});
