import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SidebarNav } from "@/components/sidebar/SidebarNav";

const fixture = vi.hoisted(() => ({ multiUserMode: true }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/chat",
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/hooks/useAuthStatus", () => ({
  useAuthStatus: () => ({ enabled: fixture.multiUserMode }),
}));

beforeEach(() => {
  localStorage.clear();
  fixture.multiUserMode = true;
});

it("folds the fixed consoles into More for a first multi-user visitor", async () => {
  render(
    <SidebarNav collapsed={false} onHomeClick={vi.fn()} onNavigate={vi.fn()} />,
  );

  await act(async () => {});

  const more = screen.getByRole("button", { name: /^More/ });
  expect(more).toHaveAttribute("aria-expanded", "false");
  expect(more).toHaveTextContent("2");

  fireEvent.click(more);

  expect(more).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("link", { name: "Memory" })).toHaveAttribute(
    "href",
    "/memory",
  );
  expect(
    screen.getByRole("link", { name: "Knowledge Center" }),
  ).toHaveAttribute("href", "/knowledge-bases");
});

it("keeps the consoles visible in the single-user shell", () => {
  fixture.multiUserMode = false;

  render(
    <SidebarNav collapsed={false} onHomeClick={vi.fn()} onNavigate={vi.fn()} />,
  );

  expect(screen.getByRole("link", { name: "Memory" })).toHaveAttribute(
    "href",
    "/memory",
  );
  expect(screen.queryByRole("button", { name: "More" })).not.toBeInTheDocument();
});
