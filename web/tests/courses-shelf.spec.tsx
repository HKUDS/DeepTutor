import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import CoursesShelf from "@/components/courses/CoursesShelf";
import { initI18n } from "@/i18n/init";

initI18n("en");

vi.mock("@/lib/courses-api", () => ({
  DEFAULT_COURSE_COLORS: ["#C65D2E"],
  listCourses: vi.fn(() =>
    Promise.reject(
      new Error("This learning account cannot use the reading surface.")
    )
  ),
  createCourse: vi.fn(),
}));

vi.mock("@/lib/session-api", () => ({
  listAllSessions: vi.fn(() => Promise.resolve([])),
}));

describe("courses shelf", () => {
  it("shows an authorization failure instead of an empty shelf", async () => {
    render(<CoursesShelf />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "This learning account cannot use the reading surface."
    );
    expect(
      screen.queryByRole("button", { name: "Create your first course" })
    ).not.toBeInTheDocument();
  });
});
