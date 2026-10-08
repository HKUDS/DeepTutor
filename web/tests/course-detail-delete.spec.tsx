import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import CourseDetailPage from "@/app/(utility)/courses/[courseId]/page";
import type { StudyCourse } from "@/lib/courses-api";

const fixture = vi.hoisted(() => ({
  course: null as StudyCourse | null,
  listCourses: vi.fn(),
  getCourseState: vi.fn(),
  deleteCourse: vi.fn(),
  listAllSessions: vi.fn(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: fixture.push }),
  useParams: () => ({ courseId: "course-1" }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/lib/courses-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/courses-api")>()),
  listCourses: (...args: unknown[]) => fixture.listCourses(...args),
  getCourseState: (...args: unknown[]) => fixture.getCourseState(...args),
  deleteCourse: (...args: unknown[]) => fixture.deleteCourse(...args),
}));
vi.mock("@/lib/session-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/session-api")>()),
  listAllSessions: (...args: unknown[]) => fixture.listAllSessions(...args),
}));

function makeCourse(): StudyCourse {
  return {
    id: "course-1",
    name: "Linear Algebra",
    description: "Vectors and matrices",
    color: "#C65D2E",
    created_at: 1,
    updated_at: 1,
    instructions: "",
    agent_notes: "",
    default_capability: "",
    default_persona: "",
    resources: [],
    syllabus: [],
    status: "active",
    archived_at: 0,
  };
}

async function openDeleteDialog() {
  fireEvent.click(screen.getByRole("button", { name: "Course actions" }));
  fireEvent.click(screen.getByRole("button", { name: "Delete course" }));
  return screen.findByRole("alertdialog");
}

beforeEach(() => {
  fixture.course = makeCourse();
  fixture.listCourses.mockImplementation(async () => [fixture.course!]);
  fixture.listAllSessions.mockImplementation(async () => []);
  fixture.getCourseState.mockImplementation(async () => null);
  fixture.deleteCourse.mockImplementation(async () => undefined);
  fixture.push.mockReset();
});

it("shows a visible error and stays on the course page when deletion fails", async () => {
  fixture.deleteCourse.mockImplementation(async () => {
    throw new Error("offline");
  });
  render(<CourseDetailPage />);
  await screen.findByText("Linear Algebra");

  const dialog = await openDeleteDialog();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Delete course" }),
  );

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("offline");
  expect(fixture.push).not.toHaveBeenCalled();
  // The dialog stays open so the failure is seen in context and retry is possible.
  expect(screen.getByRole("alertdialog")).toBeInTheDocument();
});

it("navigates back to the course list only after a successful deletion", async () => {
  render(<CourseDetailPage />);
  await screen.findByText("Linear Algebra");

  const dialog = await openDeleteDialog();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Delete course" }),
  );

  await waitFor(() =>
    expect(fixture.push).toHaveBeenCalledWith("/courses"),
  );
  expect(fixture.deleteCourse).toHaveBeenCalledWith("course-1");
  expect(screen.queryByRole("alert")).toBeNull();
});
