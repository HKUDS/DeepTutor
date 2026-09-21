import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { SidebarShell } from "@/components/sidebar/SidebarShell";

const fixture = vi.hoisted(() => ({ push: vi.fn(), close: vi.fn() }));

vi.mock("@/hooks/useChatWorkspaces", () => ({ useChatWorkspaces: () => ({ workspaces: [], error: "" }) }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/co-writer",
  useRouter: () => ({ push: fixture.push }),
}));
vi.mock("next/image", () => ({ default: () => null }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/context/AppShellContext", () => ({
  useAppShell: () => ({
    sidebarCollapsed: false,
    setSidebarCollapsed: vi.fn(),
  }),
}));
vi.mock("@/components/layout/AppShell", () => ({
  useSidebarDrawer: () => ({ close: fixture.close }),
}));
vi.mock("@/hooks/useDevice", () => ({
  useDevice: () => ({ isMobile: false }),
}));
vi.mock("@/components/sidebar/VersionBadge", () => ({
  VersionBadge: () => null,
}));

it("loads conversation history while navigation remains usable, then preserves session actions", async () => {
  const onSelect = vi.fn();
  const onRename = vi.fn();
  const onOrganize = vi.fn();
  const { container } = render(
    <SidebarShell
      showSessions
      sessions={[
        {
          id: "session-1",
          session_id: "session-1",
          title: "Retained session",
          created_at: 1,
          updated_at: 1,
          message_count: 1,
          last_message: "Hello",
        },
      ]}
      onSelectSession={onSelect}
      onRenameSession={onRename}
      onDeleteSession={vi.fn()}
      onOrganizeSession={onOrganize}
    />,
  );
  expect(container.querySelector('[aria-busy="true"]')).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Co-Writer" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /More/ }));
  expect(screen.getByRole("link", { name: "Co-Writer" })).toHaveAttribute(
    "href",
    "/co-writer",
  );

  const history = await screen.findByText("Retained session");
  const scroller = history.closest(".overflow-y-auto");
  expect(scroller).toContainElement(
    screen.getByRole("link", { name: "Partners" }),
  );
  expect(scroller).not.toContainElement(
    screen.getByRole("link", { name: "Home" }),
  );
  expect(scroller).not.toContainElement(
    screen.getByRole("link", { name: "Settings" }),
  );

  fireEvent.click(await screen.findByText("Retained session"));
  expect(onSelect).toHaveBeenCalledWith("session-1");
  expect(fixture.close).toHaveBeenCalled();
  expect(container.querySelector('[aria-busy="true"]')).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Conversation actions" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "Pin" }));
  expect(onOrganize).toHaveBeenCalledWith("session-1", { pinned: true });

  fireEvent.click(screen.getByRole("button", { name: "Conversation actions" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "Rename chat" }));
  const input = screen.getByDisplayValue("Retained session");
  fireEvent.change(input, { target: { value: "Renamed session" } });
  await act(async () => {
    fireEvent.keyDown(input, { key: "Enter" });
  });
  expect(onRename).toHaveBeenCalledWith("session-1", "Renamed session");
});

it("keeps Home pinned even when a previous layout folded it into More", () => {
  localStorage.setItem(
    "deeptutor.sidebar.navLayout",
    JSON.stringify({
      order: ["/partners", "/chat", "/space"],
      collapsed: ["/chat"],
    }),
  );
  render(<SidebarShell />);
  expect(screen.getAllByRole("link", { name: "Home" })).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "Arrange Home" })).toBeNull();
  fireEvent.click(screen.getByRole("link", { name: "Home" }));
  expect(fixture.push).toHaveBeenCalledWith("/chat");
});

it("resizes with the keyboard, persists across mounts, and resets on double click", () => {
  const first = render(<SidebarShell />);
  const handle = screen.getByRole("separator", { name: "Resize sidebar" });
  fireEvent.keyDown(handle, { key: "ArrowRight" });
  expect(handle).toHaveAttribute("aria-valuenow", "230");
  expect(
    first.container
      .querySelector("aside")!
      .style.getPropertyValue("--sidebar-width"),
  ).toBe("230px");
  first.unmount();
  render(<SidebarShell />);
  const restored = screen.getByRole("separator", { name: "Resize sidebar" });
  expect(restored).toHaveAttribute("aria-valuenow", "230");
  fireEvent.keyDown(restored, { key: "Home" });
  fireEvent.keyDown(restored, { key: "ArrowLeft" });
  expect(restored).toHaveAttribute("aria-valuenow", "220");
  fireEvent.keyDown(restored, { key: "End" });
  fireEvent.keyDown(restored, { key: "ArrowRight" });
  expect(restored.getAttribute("aria-valuenow")).toBe(
    restored.getAttribute("aria-valuemax"),
  );
  fireEvent.doubleClick(restored);
  expect(restored).toHaveAttribute("aria-valuenow", "220");
});
